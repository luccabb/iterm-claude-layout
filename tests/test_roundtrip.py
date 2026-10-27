import asyncio
import os

import iterm2
import pytest

from iterm_claude_layout import restore, snapshot

pytestmark = pytest.mark.skipif(os.environ.get("TERM_PROGRAM") != "iTerm.app", reason="needs a running iTerm2")


def shape(node):
    if "children" in node:
        return [node["vertical"], [shape(child) for child in node["children"]]]
    return node["cwd"]


def sizes(node):
    return [(leaf["cols"], leaf["rows"]) for leaf in snapshot.leaves(node)]


async def settle_paths(sessions, expected):
    for _ in range(120):
        paths = [await s.async_get_variable("path") for s in sessions]
        if paths == expected:
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"panes never reached {expected}, saw {paths}")


def test_snapshot_then_restore_rebuilds_the_same_layout(tmp_path):
    dirs = []
    for name in ("left", "top-right", "bottom-right", "second-tab"):
        (tmp_path / name).mkdir()
        dirs.append(str((tmp_path / name).resolve()))

    async def run(connection):
        app = await iterm2.async_get_app(connection)
        window = await iterm2.Window.async_create(connection)
        await app.async_refresh()
        window = app.get_window_by_id(window.window_id)
        try:
            left = window.current_tab.current_session
            top_right = await left.async_split_pane(vertical=True)
            bottom_right = await top_right.async_split_pane(vertical=False)
            cols = left.grid_size.width + top_right.grid_size.width
            left.preferred_size = iterm2.Size(cols // 3, left.grid_size.height)
            for session in (top_right, bottom_right):
                session.preferred_size = iterm2.Size(cols - cols // 3, session.grid_size.height)
            await window.current_tab.async_update_layout()
            second = await window.async_create_tab()
            await second.async_set_title("roundtrip")
            sessions = [left, top_right, bottom_right, second.current_session]
            for session, path in zip(sessions, dirs):
                await session.async_send_text(f"cd {path}\n")
            await settle_paths(sessions, dirs)
            before = await snapshot.capture(app, [window])
        finally:
            await window.async_close(force=True)

        rebuilt, _ = await restore.build(connection, restore.plan(before, set()))
        try:
            await settle_paths([s for tab in rebuilt[0].tabs for s in tab.sessions], dirs)
            after = await snapshot.capture(app, rebuilt)
        finally:
            for w in rebuilt:
                await w.async_close(force=True)

        (b,), (a,) = before["windows"], after["windows"]
        assert all(abs(x - y) <= 20 for x, y in zip(a["frame"], b["frame"])), (a["frame"], b["frame"])
        assert [t["title"] for t in a["tabs"]] == [None, "roundtrip"]
        assert [shape(t["layout"]) for t in a["tabs"]] == [shape(t["layout"]) for t in b["tabs"]]
        for ta, tb in zip(a["tabs"], b["tabs"]):
            for (ca, ra), (cb, rb) in zip(sizes(ta["layout"]), sizes(tb["layout"])):
                assert abs(ca - cb) <= 1 and abs(ra - rb) <= 1, (sizes(ta["layout"]), sizes(tb["layout"]))

    iterm2.run_until_complete(run)
