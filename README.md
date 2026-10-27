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

```
while iTerm runs                              after a crash or dead battery
────────────────                              ─────────────────────────────
iTerm layout ─────┐                           iterm-claude-layout restore
                  ├──► snapshot on disk ────► rebuild windows, tabs, splits
Claude sessions ──┘    (history kept)         + claude --resume in each pane
```

### Recording

The snapshot loop runs inside iTerm and talks to it through iTerm's Python API.

1. After a layout change has held still for 3 seconds, and every 15 seconds otherwise, it reads:
   - each window's frame
   - the tabs in order, with any title set with Edit Tab Title
   - each tab's split tree, with pane sizes and working directories
2. It matches panes to Claude sessions:
   - iTerm reports the tty of each pane.
   - Claude's registry (`~/.claude/sessions`) maps each running process to its session ID.
   - `ps` gives each process's tty and launch flags.
3. It writes a JSON snapshot when something changed, synced to disk with `F_FULLFSYNC` and tagged with the iTerm launch it came from. The newest 500 are kept in `~/Library/Application Support/iterm-claude-layout/snapshots`.

Waiting for the layout to settle means an iTerm quit, which tears windows down, is never saved as the layout.

### Restoring

`iterm-claude-layout restore`:

1. Picks the newest snapshot from before the running iTerm started that still has a Claude session to bring back. Empty snapshots from launches in between are skipped.
2. Leaves out sessions that are still running, including those in tabs closed within iTerm's undo window.
3. Recreates the windows, tabs and splits at the same sizes, and sets the tab titles.
4. Runs `cd <dir> && claude --resume <id>` in each pane. Each session gets:
   - the permission mode and effort it last had, read from the end of its transcript (bypass sessions get `--dangerously-skip-permissions`)
   - `--model` and `--add-dir`, if they were on the original command line
5. Answers Claude's folder trust prompt when it appears (in `~` it appears every time), and reports which sessions came back.

Panes that were not running Claude reopen as shells in their last directory.

## Limits

- A model switched with `/model` inside a session is not carried over.
- The layout is only as fresh as the last snapshot: about 15 seconds behind at most, or 3 seconds after a layout change.

## Tests

```
uv pip install -e '.[test]' && pytest
```

`test_roundtrip.py` drives the running iTerm. It opens a scratch window, snapshots it, closes it, restores it and compares the result. It is skipped outside iTerm.
