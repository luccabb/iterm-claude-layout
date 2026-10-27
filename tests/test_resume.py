import json

import pytest

from iterm_claude_layout import claude

SID = "11111111-2222-3333-4444-555555555555"


def entry(**fields):
    return json.dumps(fields) + "\n"


def test_last_state_reads_the_newest_entries_across_chunk_boundaries(tmp_path):
    path = tmp_path / f"{SID}.jsonl"
    path.write_text(
        entry(type="permission-mode", permissionMode="bypassPermissions", sessionId=SID)
        + entry(type="assistant", effort="max", message={"content": "x" * 300})
        + entry(type="permission-mode", permissionMode="auto", sessionId=SID)
        + entry(type="user", message={"content": '{"type":"assistant","effort":"low"}'})
        + entry(type="assistant", effort="medium", message={"content": "y" * 300})
        + entry(type="system", subtype="turn_duration")
    )
    assert claude.last_state(path, chunk=64) == ("auto", "medium")


@pytest.mark.parametrize("argv, mode, effort, expected", [
    (["claude", "--dangerously-skip-permissions"], "bypassPermissions", "xhigh", ["--dangerously-skip-permissions"]),
    (["claude", "--dangerously-skip-permissions"], "auto", "max", ["--allow-dangerously-skip-permissions", "--effort", "max"]),
    (["claude"], "plan", None, ["--permission-mode", "plan"]),
    (["claude", "--model", "opus", "--effort", "low", "fix"], None, None, ["--effort", "low", "--model", "opus"]),
    (["claude", "--dangerously-skip-permissions", "--resume", "old"], None, None, ["--dangerously-skip-permissions"]),
])
def test_resume_args_bring_back_the_last_mode_and_effort(argv, mode, effort, expected):
    assert claude.resume_args(argv, SID, mode, effort, "auto", "xhigh") == expected + ["--resume", SID]
