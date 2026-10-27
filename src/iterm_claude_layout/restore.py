from __future__ import annotations

import asyncio
import copy
import shlex
import time
from pathlib import Path

import iterm2

from . import claude, snapshot

READY = ("shift+tab to cycle", "? for shortcuts")


def pick(snapshots: list[tuple[Path, dict]], current: dict, live: set[str], latest: bool) -> tuple[Path, dict] | None:
    """The newest snapshot from before the running iTerm started (any snapshot with latest=True)
    that still has a Claude session to bring back, else the newest such snapshot at all."""
    candidates = [(path, snap) for path, snap in snapshots if latest or snap.get("iterm") != current]
    for path, snap in reversed(candidates):
        if any("claude" in leaf and leaf["claude"]["session_id"] not in live
               for window in snap["windows"] for tab in window["tabs"] for leaf in snapshot.leaves(tab["layout"])):
            return path, snap
    return candidates[-1] if candidates else None


def plan(snap: dict, live: set[str]) -> list[dict]:
    """Windows and tabs to open, with the command each pane should run; tabs already fully running are dropped."""
    default_mode, default_effort = claude.defaults()
    windows = []
    for window in snap["windows"]:
        tabs = []
        for tab in copy.deepcopy(window["tabs"]):
            panes = list(snapshot.leaves(tab["layout"]))
            if all(p.get("claude", {}).get("session_id") in live for p in panes):
                continue
            for pane in panes:
                session = pane.get("claude")
                if session and session["session_id"] not in live and claude.transcript(session["session_id"]):
                    pane["command"] = claude.resume_command(session, default_mode, default_effort)
                else:
                    pane.pop("claude", None)
                    if pane.get("cwd"):
                        pane["command"] = f"cd {shlex.quote(pane['cwd'])}"
            tabs.append(tab)
        if tabs:
            windows.append({**window, "tabs": tabs})
    return windows


async def build(connection: iterm2.Connection, windows: list[dict]) -> tuple[list[iterm2.Window], list[tuple[dict, str]]]:
    app = await iterm2.async_get_app(connection)
    created, results = [], []
    for spec in windows:
        window, tab = await _ready(app, (await iterm2.Window.async_create(connection)).window_id)
        created.append(window)
        x, y, width, height = spec["frame"]
        await window.async_set_frame(iterm2.Frame(iterm2.Point(x, y), iterm2.Size(width, height)))
        active = None
        for i, tab_spec in enumerate(spec["tabs"]):
            if i:
                _, tab = await _ready(app, window.window_id, (await window.async_create_tab()).tab_id)
            panes = await _split(tab.current_session, tab_spec["layout"])
            for session, leaf in panes:
                session.preferred_size = iterm2.Size(leaf["cols"], leaf["rows"])
            await tab.async_update_layout()
            if tab_spec.get("title"):
                await tab.async_set_title(tab_spec["title"])
            for session, leaf in panes:
                if leaf.get("command"):
                    await session.async_send_text(leaf["command"] + "\n")
                if "claude" in leaf:
                    results.append((leaf, await _settle(session)))
                if leaf.get("active"):
                    await session.async_activate(select_tab=False)
            if tab_spec.get("active"):
                active = tab
        if spec.get("fullscreen"):
            await window.async_set_fullscreen(True)
        if active is not None:
            await active.async_select()
    return created, results


async def _ready(app: iterm2.App, window_id: str, tab_id: str | None = None) -> tuple[iterm2.Window, iterm2.Tab]:
    """A just-created window or tab, once iTerm has reported it and its first session."""
    for _ in range(50):
        window = app.get_window_by_id(window_id)
        tab = app.get_tab_by_id(tab_id) if tab_id else window.current_tab if window else None
        if tab is not None and tab.current_session is not None:
            return window, tab
        await asyncio.sleep(0.1)
        await app.async_refresh()
    raise RuntimeError(f"iTerm never reported window {window_id}")


async def _split(session: iterm2.Session, node: dict) -> list[tuple[iterm2.Session, dict]]:
    if "children" not in node:
        return [(session, node)]
    panes = [session]
    for _ in node["children"][1:]:
        panes.append(await panes[-1].async_split_pane(vertical=node["vertical"]))
    out = []
    for pane, child in zip(panes, node["children"]):
        out += await _split(pane, child)
    return out


async def _settle(session: iterm2.Session, timeout: float = 120) -> str:
    """Wait for a resumed session to come up, answering the folder trust prompt if it appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        contents = await session.async_get_screen_contents()
        lines = [contents.line(i).string.replace("\x00", " ").strip() for i in range(contents.number_of_lines)]
        bottom = [line for line in lines if line][-8:]
        if any(marker in line for line in bottom for marker in READY):
            return "resumed"
        if any("No conversation found" in line for line in lines):
            return "transcript not found"
        text = " ".join(bottom)
        if "Enter to confirm" in text and "trust" in text.lower():
            selected = next((line for line in bottom if line.startswith("❯")), "")
            on_yes = selected.lstrip("❯ ").lstrip("0123456789. ").startswith("Yes")
            await session.async_send_text("\r" if on_yes else "\x1b[B")
            await asyncio.sleep(0.5)
    return "not confirmed"


def describe(windows: list[dict]) -> str:
    out = []
    for w, window in enumerate(windows, 1):
        out.append(f"window {w}")
        for t, tab in enumerate(window["tabs"], 1):
            out.append(f"  tab {t}" + (f" [{tab['title']}]" if tab.get("title") else ""))
            for pane in snapshot.leaves(tab["layout"]):
                label = pane.get("title") or ""
                out.append(f"    {pane.get('command', '(empty)')}" + (f"   # {label}" if label else ""))
    return "\n".join(out)
