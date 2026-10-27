# iterm-claude-layout

Keeps a running record of your iTerm2 windows, tabs and splits, and of the Claude Code session in each pane, so the whole layout can be rebuilt after a crash, a dead battery or an iTerm restart.

## Requirements

- macOS and iTerm2 with the Python API turned on: iTerm2 → Settings → General → Magic → Enable Python API. Tested on iTerm2 3.6.9.
- Claude Code. Tested with 2.1.311. The tool relies on Claude's live session registry in `~/.claude/sessions`.
- [uv](https://docs.astral.sh/uv/)

## Turn it on

1. Install the command from a clone, editable, so the iTerm script runs the clone and `git pull` updates it:
   ```
   git clone git@github.com:luccabb/iterm-claude-layout.git ~/code/iterm-claude-layout
   uv tool install --editable ~/code/iterm-claude-layout
   ```
2. Register the snapshot loop with iTerm:
   ```
   iterm-claude-layout install
   ```
   This puts it in iTerm's AutoLaunch folder, so iTerm starts it at every launch and stops it when iTerm quits. If iTerm's Python runtime is missing, iTerm offers to download it. Accept.
3. Start it now, without restarting iTerm:
   ```
   nohup iterm-claude-layout daemon >/dev/null 2>&1 &
   ```
   This copy runs until iTerm quits. From the next launch on, iTerm runs it.
4. Check that it is recording:
   ```
   tail -3 ~/Library/Application\ Support/iterm-claude-layout/daemon.log
   iterm-claude-layout list
   ```

To update, run `git pull` in the clone, then restart iTerm, or stop the loop with `pkill -f 'iterm[-_]claude[-_]layout'` and repeat step 3.

To turn it off, delete `~/Library/Application Support/iTerm2/Scripts/AutoLaunch/iterm_claude_layout.py` and run `pkill -f 'iterm[-_]claude[-_]layout'`.

## After a crash

Open iTerm, then:

```
iterm-claude-layout restore --dry-run   # what it would open
iterm-claude-layout restore
```

`restore` uses the newest snapshot from before iTerm last started.

Sometimes you want something back that you closed while iTerm kept running, such as a window or tab you closed after `/exit`ing its Claude sessions. Use the newest snapshot regardless of launch:

```
iterm-claude-layout restore --latest
```

Or pick a snapshot by hand:

```
iterm-claude-layout list
iterm-claude-layout restore --snapshot ~/Library/Application\ Support/iterm-claude-layout/snapshots/<file>
```

Each restore uses one snapshot. Things closed at different times may need separate `--snapshot` restores.

## How it works

```
while iTerm runs                              after a crash or dead battery
────────────────                              ─────────────────────────────
iTerm layout ─────┐                           iterm-claude-layout restore
                  ├──► snapshot on disk ────► rebuild windows, tabs, splits
Claude sessions ──┘    (history kept)         + claude --resume in each pane
```

### Recording

The snapshot loop talks to iTerm through iTerm's Python API.

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
2. Leaves out what is still open:
   - A window whose Claude sessions have all ended is rebuilt whole.
   - From a window with a session still running, only the tabs whose sessions have all ended come back, in a new window.
   - Sessions in tabs closed within iTerm's undo window still count as running.
3. Recreates the windows, tabs and splits at the same sizes, and sets the tab titles.
4. Runs `cd <dir> && claude --resume <id>` in each pane. Each session gets:
   - the permission mode and effort it last had, read from the end of its transcript (bypass sessions get `--dangerously-skip-permissions`)
   - `--model` and `--add-dir`, if they were on the original command line
5. Answers Claude's folder trust prompt when it appears (in `~` it appears every time), and reports which sessions came back.

Panes that were not running Claude reopen as shells in their last directory.

## Troubleshooting

- **`There was a problem connecting to iTerm2`:** the Python API is off; see Requirements.
- **`no snapshot from before this iTerm launch`:** iTerm has not restarted since the loop started recording. For something closed during this launch, use `--latest` or `--snapshot`.
- **`nothing to restore: everything in it is still open`:** those Claude sessions are still running. iTerm keeps a closed tab's processes alive so the close can be undone. `/exit` the sessions before closing, or bring the tab back with ⌘Z (Undo Close).
- **A Claude pane comes back as a plain shell:** its session was still running somewhere, or its transcript is gone. Claude deletes transcripts older than `cleanupPeriodDays`.
- **A session is reported `not confirmed`:** it did not reach Claude's prompt within two minutes. Look at that pane.

## Limits

- iTerm2 only. tmux and other terminals are not supported.
- Plain-shell panes reopen in their last directory, but whatever ran in them is not restarted and their scrollback is not restored.
- A model switched with `/model` inside a session is not carried over.
- The layout is only as fresh as the last snapshot: about 15 seconds behind at most, or 3 seconds after a layout change.

## Tests

```
uv run --extra test pytest
```

The test drives the running iTerm:

1. It opens a scratch window with nested splits and a titled tab.
2. It snapshots the window, closes it, and restores it from the snapshot.
3. It checks that the structure, pane sizes, folders and title match.

It is skipped outside iTerm.
