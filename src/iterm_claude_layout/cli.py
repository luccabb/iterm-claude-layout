from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import iterm2

from . import claude, daemon, restore, snapshot, store

AUTOLAUNCH = Path.home() / "Library" / "Application Support" / "iTerm2" / "Scripts" / "AutoLaunch" / "iterm_claude_layout.py"
WRAPPER = """import sys

sys.path.append({src!r})

import iterm2
from iterm_claude_layout.daemon import main

iterm2.run_forever(main)
"""


async def _current(connection) -> dict:
    app = await iterm2.async_get_app(connection)
    pid = await app.async_get_variable("pid")
    return {"pid": pid, "started": snapshot.started(pid)}


def _summary(snap: dict) -> str:
    tabs = [t for w in snap["windows"] for t in w["tabs"]]
    panes = [p for t in tabs for p in snapshot.leaves(t["layout"])]
    sessions = sum("claude" in p for p in panes)
    return f"{len(snap['windows'])} windows, {len(tabs)} tabs, {len(panes)} panes, {sessions} Claude sessions"


def cmd_restore(args) -> int:
    code = 0

    async def run(connection):
        nonlocal code
        live = {c["session_id"] for c in claude.live_sessions().values()}
        if args.snapshot:
            chosen = (args.snapshot, store.load_one(args.snapshot))
        else:
            chosen = restore.pick(store.load_all(), await _current(connection), live, args.latest)
        if chosen is None:
            print("no snapshot from before this iTerm launch; see `iterm-claude-layout list`, or pass --latest")
            code = 1
            return
        path, snap = chosen
        windows = restore.plan(snap, live)
        taken = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap["taken_at"]))
        print(f"snapshot {path.name} taken {taken}: {_summary(snap)}")
        if not windows:
            print("nothing to restore: everything in it is still open")
            return
        print(restore.describe(windows))
        if args.dry_run:
            return
        _, results = await restore.build(connection, windows)
        failed = [(leaf, status) for leaf, status in results if status != "resumed"]
        print(f"resumed {len(results) - len(failed)}/{len(results)} Claude sessions")
        for leaf, status in failed:
            print(f"  {leaf['claude']['session_id']} ({leaf.get('title') or 'untitled'}): {status}")
        code = 1 if failed else 0

    iterm2.run_until_complete(run, retry=False)
    return code


def cmd_list(_args) -> int:
    snapshots = store.load_all()
    if not snapshots:
        print(f"no snapshots in {store.SNAPSHOTS}")
        return 0
    for path, snap in snapshots[-40:]:
        taken = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap["taken_at"]))
        print(f"{path.name}  {taken}  iTerm pid {snap['iterm']['pid']}  {_summary(snap)}")
    return 0


def cmd_snapshot(_args) -> int:
    async def run(connection):
        snap = await snapshot.capture(await iterm2.async_get_app(connection))
        last = store.latest_fingerprint()
        fp = store.save(snap, last)
        print(f"{'unchanged' if fp == last else 'saved'} {fp}: {_summary(snap)}")

    iterm2.run_until_complete(run, retry=False)
    return 0


def cmd_daemon(_args) -> int:
    iterm2.run_until_complete(daemon.main, retry=False)
    return 0


def cmd_install(_args) -> int:
    AUTOLAUNCH.parent.mkdir(parents=True, exist_ok=True)
    AUTOLAUNCH.write_text(WRAPPER.format(src=str(Path(__file__).resolve().parents[1])))
    print(f"wrote {AUTOLAUNCH}")
    runtimes = list(AUTOLAUNCH.parents[2].glob("iterm2env*"))
    if not runtimes:
        async def install_runtime(connection):
            await iterm2.MainMenu.async_select_menu_item(
                connection, iterm2.MainMenu.Scripts.Manage.INSTALL_PYTHON_RUNTIME.value.identifier)

        iterm2.run_until_complete(install_runtime, retry=False)
        print("asked iTerm to install its Python runtime; AutoLaunch scripts need it")
    print("iTerm starts the snapshot loop at every launch; `iterm-claude-layout daemon &` runs it until then")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="iterm-claude-layout",
        description="Snapshot iTerm2 windows, tabs and splits with the Claude session in each pane, and rebuild them.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("restore", help="rebuild the layout from before iTerm last started and resume its sessions")
    r.add_argument("--snapshot", type=Path, help="restore this snapshot file")
    r.add_argument("--latest", action="store_true", help="use the newest snapshot, even one from the running iTerm")
    r.add_argument("--dry-run", action="store_true", help="print what would be opened and exit")
    r.set_defaults(func=cmd_restore)
    sub.add_parser("list", help="list saved snapshots").set_defaults(func=cmd_list)
    sub.add_parser("snapshot", help="save a snapshot now").set_defaults(func=cmd_snapshot)
    sub.add_parser("daemon", help="run the snapshot loop in the foreground").set_defaults(func=cmd_daemon)
    sub.add_parser("install", help="register the snapshot loop as an iTerm AutoLaunch script").set_defaults(
        func=cmd_install)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
