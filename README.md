# iterm-claude-layout

Keeps a running record of your iTerm2 windows, tabs and splits, and of the Claude Code session in each pane, so the whole layout can be rebuilt after a crash, a dead battery or an iTerm restart.

```
iterm-claude-layout restore            # rebuild the layout from before iTerm last started
iterm-claude-layout restore --dry-run  # show what would be opened
iterm-claude-layout list               # saved snapshots
```

## Install

```
uv tool install --editable .
iterm-claude-layout install
```

`install` registers the snapshot loop as an iTerm AutoLaunch script, so iTerm starts it at every launch. AutoLaunch scripts need iTerm's Python runtime; `install` asks iTerm to download it if it is missing. To start the loop without restarting iTerm, run `iterm-claude-layout daemon &`. It stops when iTerm quits, and AutoLaunch takes over at the next launch.

## How it works

The loop saves a snapshot each time a layout change has held still for 3 seconds, and every 15 seconds otherwise. Waiting for the layout to settle keeps an iTerm quit, which tears windows down, from being recorded. A snapshot records:

- each window's frame
- tab order and any title set with Edit Tab Title
- the split tree with each pane's size and working directory
- for panes running Claude, the session ID, working directory and launch flags

Panes are matched to Claude sessions through the tty each `claude` process runs on and Claude's live session registry (`~/.claude/sessions`). A snapshot is written only when something changed, synced to disk with `F_FULLFSYNC`, and the newest 500 are kept in `~/Library/Application Support/iterm-claude-layout/snapshots`.

`restore` picks the newest snapshot from before the running iTerm started that still has a Claude session to bring back. It then:

1. skips sessions that are still running, including those in tabs closed within iTerm's undo window
2. recreates windows, tabs, splits, sizes and tab titles
3. runs `claude --resume` in each pane

Each session gets back:

- the permission mode and effort it last had, read from the end of its transcript (bypass sessions get `--dangerously-skip-permissions`)
- `--model` and `--add-dir` if they were on its original command line

When Claude asks whether to trust the folder (it asks every time in `~`), `restore` moves the selection to Yes and confirms it. Panes that were not running Claude reopen as shells in their last directory.

## Limits

- A model switched with `/model` inside a session is not carried over.
- The layout is only as fresh as the last snapshot: about 15 seconds behind at most, or 3 seconds after a layout change.

## Tests

```
uv pip install -e '.[test]' && pytest
```

`test_roundtrip.py` drives the running iTerm. It opens a scratch window, snapshots it, closes it, restores it and compares the result. It is skipped outside iTerm.
