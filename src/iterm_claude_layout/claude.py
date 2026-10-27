from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
BYPASS_FLAGS = {"--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"}
KEPT_FLAGS = {"--model", "--add-dir"}


def processes() -> dict[int, tuple[str, list[str]]]:
    out = subprocess.run(["ps", "-axo", "pid=,tty=,command="], capture_output=True, text=True, check=True).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            procs[int(parts[0])] = (parts[1], parts[2].split())
    return procs


def live_sessions(procs: dict | None = None) -> dict[str, dict]:
    """Interactive Claude sessions running right now, keyed by the tty they run on."""
    procs = processes() if procs is None else procs
    by_tty: dict[str, dict] = {}
    for f in (HOME / "sessions").glob("*.json"):
        try:
            entry = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        proc = procs.get(entry.get("pid"))
        if entry.get("kind") != "interactive" or not proc or "claude" not in " ".join(proc[1][:2]):
            continue
        tty, argv = proc
        current = by_tty.get(tty)
        if current is None or entry.get("startedAt", 0) > current["started_at"]:
            by_tty[tty] = {"session_id": entry["sessionId"], "cwd": entry["cwd"], "argv": argv,
                           "started_at": entry.get("startedAt", 0)}
    return by_tty


def transcript(session_id: str) -> Path | None:
    return next((HOME / "projects").glob(f"*/{session_id}.jsonl"), None)


def last_state(path: Path, chunk: int = 1 << 20) -> tuple[str | None, str | None]:
    """The most recent permission mode and effort recorded in a transcript."""
    mode = effort = None
    with open(path, "rb") as f:
        end = f.seek(0, os.SEEK_END)
        carry = b""
        while end > 0 and (mode is None or effort is None):
            start = max(0, end - chunk)
            f.seek(start)
            lines = (f.read(end - start) + carry).split(b"\n")
            carry = lines.pop(0) if start > 0 else b""
            for line in reversed(lines):
                if mode is None and b'"permission-mode"' in line:
                    mode = _field(line, "permission-mode", "permissionMode") or mode
                elif effort is None and b'"assistant"' in line and b'"effort"' in line:
                    effort = _field(line, "assistant", "effort") or effort
            end = start
    return mode, effort


def _field(line: bytes, entry_type: str, key: str):
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry.get(key) if entry.get("type") == entry_type else None


def defaults() -> tuple[str, str | None]:
    try:
        settings = json.loads((HOME / "settings.json").read_text())
    except (OSError, ValueError):
        settings = {}
    return settings.get("permissions", {}).get("defaultMode", "default"), settings.get("effortLevel")


def resume_args(argv: list[str], session_id: str, mode: str | None, effort: str | None,
                default_mode: str, default_effort: str | None) -> list[str]:
    """Flags that bring a session back in the mode and effort it last had."""
    allow_bypass, argv_mode, argv_effort, kept = False, None, None, []
    i = 1
    while i < len(argv):
        flag, value = argv[i], argv[i + 1] if i + 1 < len(argv) else None
        if flag in BYPASS_FLAGS:
            allow_bypass = True
            argv_mode = argv_mode or ("bypassPermissions" if flag == "--dangerously-skip-permissions" else None)
        elif flag == "--permission-mode" and value:
            argv_mode, i = value, i + 1
        elif flag == "--effort" and value:
            argv_effort, i = value, i + 1
        elif flag in KEPT_FLAGS and value:
            kept, i = kept + [flag, value], i + 1
        i += 1
    mode = mode or argv_mode
    effort = effort or argv_effort
    args = []
    if mode == "bypassPermissions":
        args.append("--dangerously-skip-permissions")
    else:
        if allow_bypass:
            args.append("--allow-dangerously-skip-permissions")
        if mode and mode != default_mode:
            args += ["--permission-mode", mode]
    if effort and effort != default_effort:
        args += ["--effort", effort]
    return args + kept + ["--resume", session_id]


def resume_command(claude: dict, default_mode: str, default_effort: str | None) -> str:
    path = transcript(claude["session_id"])
    mode, effort = last_state(path) if path else (None, None)
    args = resume_args(claude["argv"], claude["session_id"], mode, effort, default_mode, default_effort)
    return f"cd {shlex.quote(claude['cwd'])} && claude {shlex.join(args)}"
