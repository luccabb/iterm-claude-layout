from __future__ import annotations

import os
import subprocess
import time

import iterm2

from . import claude


async def capture(app: iterm2.App, only: list[iterm2.Window] | None = None) -> dict:
    sessions = claude.live_sessions()
    windows = []
    for window in app.windows if only is None else only:
        frame = await window.async_get_frame()
        current_tab = window.current_tab
        tabs = []
        for tab in window.tabs:
            title = await tab.async_get_variable("titleOverrideFormat") or await tab.async_get_variable("titleOverride")
            tabs.append({
                "title": title or None,
                "active": current_tab is not None and tab.tab_id == current_tab.tab_id,
                "layout": await _node(tab.root, tab.active_session_id, sessions),
            })
        windows.append({
            "frame": [frame.origin.x, frame.origin.y, frame.size.width, frame.size.height],
            "fullscreen": await window.async_get_fullscreen(),
            "tabs": tabs,
        })
    pid = await app.async_get_variable("pid")
    return {"taken_at": time.time(), "iterm": {"pid": pid, "started": started(pid)}, "windows": windows}


async def _node(node, active_id: str | None, sessions: dict) -> dict:
    if isinstance(node, iterm2.Splitter):
        return {"vertical": node.vertical,
                "children": [await _node(child, active_id, sessions) for child in node.children]}
    leaf = {
        "cols": node.grid_size.width,
        "rows": node.grid_size.height,
        "cwd": await node.async_get_variable("path"),
        "title": await node.async_get_variable("autoName"),
        "job": await node.async_get_variable("commandLine"),
        "active": node.session_id == active_id,
    }
    found = sessions.get(os.path.basename(await node.async_get_variable("tty") or ""))
    if found:
        leaf["claude"] = {k: found[k] for k in ("session_id", "cwd", "argv")}
    return leaf


def started(pid: int) -> str:
    out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True)
    return out.stdout.strip()


def leaves(node: dict):
    if "children" in node:
        for child in node["children"]:
            yield from leaves(child)
    else:
        yield node
