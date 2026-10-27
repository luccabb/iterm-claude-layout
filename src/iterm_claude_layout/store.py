from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path.home() / "Library" / "Application Support" / "iterm-claude-layout"
SNAPSHOTS = ROOT / "snapshots"
KEEP = 500
VOLATILE = {"taken_at", "fingerprint", "title", "job", "active"}


def fingerprint(snapshot: dict) -> str:
    def stable(value):
        if isinstance(value, dict):
            if "claude" in value:
                value = {k: v for k, v in value.items() if k != "cwd"}
            return {k: stable(v) for k, v in value.items() if k not in VOLATILE}
        if isinstance(value, list):
            return [stable(v) for v in value]
        return value

    return hashlib.sha256(json.dumps(stable(snapshot), sort_keys=True).encode()).hexdigest()[:16]


def save(snapshot: dict, last: str | None) -> str:
    """Write the snapshot unless it matches the last one; returns the current fingerprint."""
    fp = fingerprint(snapshot)
    if fp == last:
        return fp
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(snapshot['taken_at']))}-{fp[:8]}.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({**snapshot, "fingerprint": fp}, f, indent=1)
        f.flush()
        fcntl.fcntl(f.fileno(), fcntl.F_FULLFSYNC)
    os.replace(tmp, path)
    dir_fd = os.open(SNAPSHOTS, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    for old in sorted(SNAPSHOTS.glob("*.json"))[:-KEEP]:
        old.unlink()
    return fp


def load_all() -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(SNAPSHOTS.glob("*.json")):
        try:
            out.append((path, json.loads(path.read_text())))
        except (OSError, ValueError):
            continue
    return out


def load_one(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def latest_fingerprint() -> str | None:
    snapshots = load_all()
    return snapshots[-1][1].get("fingerprint") if snapshots else None


def lock():
    """Hold an exclusive lock so only one snapshot loop runs; None if another has it."""
    ROOT.mkdir(parents=True, exist_ok=True)
    f = open(ROOT / "daemon.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f
