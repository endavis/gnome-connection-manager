# Using terminals in GCM

Copy, paste, selection and scrollback behave differently depending on what is running
inside the tab. Most of what looks like broken copy/paste is a full-screen application
holding the mouse, or the alternate screen having no scrollback of its own. This page
covers both, plus the shortcut table and how to change it.

## Selecting text

Click and drag selects, as in any terminal. `Ctrl+Shift+C` copies the selection.

Set **`auto-copy-selection`** if you would rather skip that second step — every selection
goes to the clipboard the moment you finish dragging, and `Ctrl+Shift+C` becomes
unnecessary. It is off by default:

```ini
[options]
auto-copy-selection = true
```

### When an application has taken the mouse

Full-screen applications can enable mouse reporting, which routes click and drag to the
application instead of the terminal. Dragging then scrolls a pane or moves a cursor
rather than selecting text, and it looks like selection has stopped working.

**Hold `Shift` while dragging** to force a local selection. `Shift` bypasses mouse
reporting and hands the drag back to the terminal.

What you get is an ordinary terminal selection, not a special mode: `Ctrl+Shift+C`
copies it, `auto-copy-selection` picks it up on its own if you have that on, and it
behaves like any other selection everywhere else. The only unusual part is the `Shift`
needed to make it.

Not every full-screen application does this — see [What agent CLIs
do](#what-agent-clis-do) below. If plain dragging already selects, nothing has taken the
mouse and `Shift` is unnecessary.

### Reaching scrollback

`Shift+PageUp` and `Shift+PageDown` move through the scrollback a page at a time. These
work while an application is running, which the plain keys may not, because unmodified
`PageUp`/`PageDown` are usually delivered to the application.

## What Copy All actually copies

**Copy All** (`Ctrl+Shift+A`) copies a different amount depending on which screen is
active. This is a property of how terminals work, not a limitation of GCM:

| Active screen | Copy All returns |
|---|---|
| Primary (a shell, ordinary command output) | The whole scrollback buffer |
| Alternate (a full-screen application) | The visible screen only |

Full-screen applications run on the *alternate screen*, which has no scrollback of its
own. There is nothing above the visible rows to copy, so Copy All returns just what you
can see.

Your primary-screen scrollback is not lost while a full-screen application runs — it is
only unreachable. Quitting the application switches back and the scrollback is intact.

## What cannot be recovered

Content that scrolls **inside** a full-screen application never reaches the terminal as
lines. The application redraws its own viewport in place, so the terminal only ever sees
the current frame. Once the application has drawn over it, that content is gone as far as
the terminal is concerned, and no terminal emulator can retrieve it.

When you need the full record of a session, use the application's own export — a
`/export` command, a session transcript, or a `--print` style flag — rather than the
terminal's scrollback.

GCM's own **session logging** (per host, or `log-local` for local consoles) records what
the terminal receives, so it captures ordinary command output but is subject to the same
limitation for full-screen applications.

Logs are laid out under `log-path` (default `~/.gcm/logs`) mirroring your host tree:

```
<log-path>/<group>/<host name>/<user>-<YYYYMMDD>-<NNN>.log
```

```
~/.gcm/logs/Home Tech/OPNsense/OPNA/endavis/OPNA-TS/root-20260823-001.log
~/.gcm/logs/1. Projects/pyproject-template/session-20260823-001.log
```

The name comes from the **host entry**, never the tab label, so renaming a tab does not
change where its session is logged. Hosts with no user set use `session` as the filename.
The `-NNN` counter distinguishes repeated sessions on the same day. Each log opens with a
header naming the host and where it connected (`user@host:port`), so a file stays
identifiable after it is moved or renamed.

## Pasting

Paste is `Ctrl+Shift+V`, or right-click if `paste-right-click` is on.

Pasted text that ends in a newline submits itself the moment it lands, which turns a
prompt you meant to review into a command that already ran. GCM strips trailing newlines
before delivering a paste. Multi-line content still pastes as multiple lines; only the
final terminator is removed.

Large or multi-line pastes show a preview first, so a wrong clipboard does not flood the
session. **Paste as One Line** in the Edit and right-click menus joins the lines instead,
for when you want a multi-line snippet to arrive as one command.

```ini
[options]
paste-strip-trailing-newline = true   ; drop trailing newlines
paste-confirm-lines = 5               ; preview above this many lines; 0 disables
paste-confirm-bytes = 8192            ; preview above this many bytes; 0 disables
```

Applications that support bracketed paste are told the content is a paste rather than
typing, which stops a shell from executing each line as it arrives. GCM preserves that
framing.

## Recording a session in full

The session log records what the terminal *displayed*, so anything redrawn in place —
a progress bar, a full-screen application's frames — collapses to its final state.

Raw recording captures the byte stream instead, exactly as it arrived:

```ini
[options]
raw-session-log = true
```

It writes two files alongside the text log, numbered independently of it:

```
<log-path>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.raw      the bytes, exactly as they arrived
<log-path>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.timing   one line per write: <delay> <bytes>
```

The timing file is what makes the recording replayable. Concatenated bytes lose the
write boundaries, and those are what separate one frame from the next — without them a
whole full-screen session reads back as just its final screen. The counts cut the stream
back into the original writes; the delays replay it at its original speed.

The format matches `script -t`, so `scriptreplay` can play a recording directly. It skips
the first line of a typescript, which ours does not have, so feed it a blank one:

```sh
{ printf '\n'; cat session.raw; } > /tmp/replay.raw
scriptreplay --timing=session.timing --typescript=/tmp/replay.raw
```

**A raw file is not something you read.** Measured, a full-screen application's stream
is around 90% escape sequences. It is a faithful record for replaying or post-processing,
not a transcript — the text log remains the readable one. Recordings are also larger, and
contain everything the terminal received.

Like OSC 52, this runs sessions under a small relay process. With both preferences off,
sessions are spawned exactly as before.

### Turning a recording into a transcript

A recording is faithful but not readable. **Save Transcript**, in the Edit menu and the
terminal's right-click menu, rebuilds a linear log of what was actually displayed —
what you usually want after a session with a full-screen application in it.

It replays the recording through a hidden terminal, so it only works on a session that
was recorded: turn on `raw-session-log` before the session, not after. The transcript is
offered as a text file beside the recording.

It is worth knowing what it can and cannot recover:

- **Anything outside a full-screen application is exact.** Ordinary shell output is
  reconstructed line for line from the terminal's own scrollback, with no guessing.
- **Inside a full-screen application it is a best effort.** There is no scrollback on the
  alternate screen, so the only record of what scrolled past is the difference between
  one frame and the next. Content that scrolled, and pages that were turned, come back;
  a screen that was replaced by a wholly different one *and* redrawn from blank in
  between can lose a page. It errs towards missing a line rather than repeating one — a
  transcript that repeats a status bar every frame is worse than one with a gap.
- **The last screen is included**, because it was never scrolled past. Titles and status
  bars that were on it appear in the transcript; they were on the screen.
- **The terminal's current size is used.** A session that was resized part-way through
  replays at today's size, and long lines may wrap differently than they did.

Replay takes a while on a long session. The terminal parses about 60 frames a second and
feeding it faster just makes it skip frames, so the progress dialog can cancel — you get
a transcript of everything replayed so far.

`scriptreplay` remains the way to watch a recording play back at its original speed; the
transcript is for reading and grepping afterwards.

## Letting applications set the clipboard (OSC 52)

Applications ask a terminal to set the system clipboard with an escape sequence called
OSC 52. `tmux` (with `set-clipboard on`), neovim, helix and lazygit all use it — it is
how a copy inside a full-screen application reaches your desktop clipboard, including
over SSH.

VTE does not implement OSC 52, so this is **off by default**:

```ini
[options]
osc52-clipboard = true
```

With it on, sessions run under a small relay process that watches the output for the
sequence and hands the payload to GCM. With it off, sessions are spawned exactly as
before — the relay is not involved at all.

Two deliberate restrictions, because the sequence is written by whatever runs in the
terminal, **including a remote host**:

- **The read direction is ignored.** `OSC 52` can also ask the terminal to send the
  clipboard *back* to the application. GCM never answers, as most terminals do not — a
  remote host must not be able to read your clipboard.
- **Only the clipboard and primary selections are honoured.** Cut buffers are ignored.

Turning the preference off stops clipboard writes immediately, including from sessions
that were already running when it was on.

## Viewing the buffer without the mouse

`Ctrl+Shift+F`, **Edit → View Buffer**, or **Ver buffer** in the right-click menu opens the
scrollback in a plain text window.

This is the answer when selection is awkward: an application holding the mouse cannot
interfere, ordinary keyboard selection works, and `Ctrl+A` / `Ctrl+C` do what you expect.
Type in the search box to highlight every match; `Enter`, `F3` or `Ctrl+G` step through
them, `Shift` with either goes backwards, and the search wraps. `Escape` closes the window.

Buttons cover **Copy Selection** (falls back to everything when nothing is selected),
**Copy All**, **Save As** and **Refresh** — the window is a snapshot, so refresh after new
output arrives.

Inside a full-screen application it shows the visible screen, for the same reason Copy All
does: the alternate screen has no scrollback. That is still easier to work with than a
terminal selection.

The viewer keeps colour, bold, italic, underline and strikethrough, so output where
colour carries meaning — test results, diffs, log levels — reads the same as it did in
the terminal. It uses the terminal's own background, so light text stays legible instead
of vanishing against a pale window. Copying and saving still produce plain text: colour belongs on screen, not
in your clipboard or a file.

Opening the viewer does not disturb any selection you already had in the terminal.

## Tab titles

Tabs show the host name. When the running program advertises a window title, it is appended:

```
prod-web-01: npm run build
prod-web-01: ✳ Claude Code
```

The host name always stays in front, so tabs remain identifiable — several sessions of the
same tool would otherwise look identical. Titles are truncated, and the full text is in the
tab's tooltip.

**Renaming a tab wins.** Once you rename a tab, programs stop changing its label.

Turn the behaviour off entirely with:

```ini
[options]
tab-title-from-terminal = false
```

The title is display only. It never affects where sessions are logged, what a cloned tab
connects to, or which console a cluster command targets — those all use the tab's identity,
which is the host name or your explicit rename. This matters because a window title is set by
whatever runs in the terminal, including a remote host over SSH.

Note that not every program sets a title: of the agent CLIs measured above, only Claude Code
does, and it advertises a fixed string rather than per-task status.

## Finding a console among many

Once the tabs stop fitting, the tab strip grows arrows and most of your sessions are off
screen. The **▾ button at the far right of the tab strip** lists all of them. It sits outside
the arrows, so it does not scroll away with the tabs. The same list is in the menu bar under
**Terminal → Open Consoles**.

```
◀ │ web-01 │ db-02: htop │ claude: gcm │ ▶ │ ▾
                                              │
   ┌──────────────────────────────────────────┘
   │ ● [ALT+1] web-01
   │   [ALT+2] db-02: htop
   │   [ALT+3] claude: gcm
   │   [ALT+4] deploy-runner        ← struck through: the session has exited
```

Each row shows what the tab shows, including any title the program set — which is what tells
several sessions of the same tool apart. Choosing a row raises that console and gives it the
keyboard.

The list also carries state you would otherwise have to go looking for:

| Row | Means |
| --- | --- |
| Marked with a dot | The console that currently has the keyboard |
| **Bold** | Rang the bell and you have not looked at it yet |
| ~~Struck through~~ | The session behind it has exited |
| `[ALT+1]` … `[ALT+9]` | The key that jumps straight there, as you have it configured |

The keys are read from your `[shortcuts]` config, not hardcoded, so a rebound key shows the
key you actually use. They address a position *within one pane*, which is why the numbering
restarts under each heading once you have split the window — with a split, the list groups
consoles by pane and tells you which pane each one is in.

## Dropping files onto a terminal

Drag a file from a file manager onto a terminal and its path is inserted at the cursor,
shell-quoted. Drop several and you get a space-separated list.

```
/home/you/src/app.py '/home/you/my notes.txt'
```

Nothing is executed — no newline is appended, so the text sits at the prompt for you to
review, the same rule paste follows. Handy for `@`-referencing files in an AI CLI.

Non-file URLs are inserted as URLs rather than converted to paths. Dragged plain text goes
in exactly as it came, without quoting, since it is text rather than a path.

## Opening file:line from output

Compilers, linters, test runners and AI CLIs all print locations like
`src/app.py:42` or `src/app.py:42:7`. Ctrl+click one to open it in your editor.

```ini
[options]
editor-command = code --goto {file}:{line}:{col}
```

`{file}`, `{line}` and `{col}` are substituted. With no template set, GCM uses `$VISUAL`
or `$EDITOR` with the `+LINE` convention that vi, vim, nano and emacs understand, and
falls back to `xdg-open` — which cannot jump to a line.

Two deliberate limits:

- **Local sessions only.** A path printed by a remote host does not exist on your machine,
  so Ctrl+click does nothing in an SSH session rather than opening the wrong file.
- **The name needs an extension.** `src/app.py:42` matches; `Makefile:12` does not. Without
  that requirement, ordinary output like `host:22` would be treated as a file.

Relative paths resolve against the terminal's working directory, taken from OSC 7 if your
shell emits it and otherwise read from the running process — so plain `cd` is tracked with
no shell configuration.

## Font zoom

`Ctrl+scroll` zooms, as do `Ctrl+=` and `Ctrl+-`. `Ctrl+0` returns to normal size.

Zoom applies to **one terminal**, not the whole application, so a wide log in one tab does
not shrink the shell in the next. The scale is limited to 0.25x–4.0x and is not saved
across restarts. To change the font itself, use Preferences.

## Scrollback

The scrollback buffer defaults to 10000 lines and is configurable from 1 to 1,000,000:

```ini
[options]
buffer-lines = 10000
```

Depth costs very little memory — the buffer is paged out to a compressed temporary file
rather than held in RAM, so raising it further is cheap. It applies to the primary screen
only, for the reason described above.

## Keyboard shortcuts

Every shortcut below is user-configurable under `[shortcuts]` in `~/.gcm/gcm.conf`, or
through the shortcut editor in Preferences.

| Default | Command | Also in a menu |
|---|---|---|
| `Ctrl+Shift+C` | `copy` | yes |
| `Ctrl+Shift+V` | `paste` | yes |
| `Ctrl+Shift+A` | `copy_all` | yes |
| `Ctrl+S` | `save` | no |
| `Ctrl+F` | `find` | yes |
| `Ctrl+G` | `find_next` | yes |
| `Ctrl+H` | `find_back` | yes |
| `Ctrl+Tab` | `console_next` | yes |
| `Ctrl+Shift+Tab` | `console_previous` | yes |
| `Ctrl+W` | `console_close` | yes |
| `Ctrl+N` | `console_reconnect` | yes |
| `Ctrl+Return` | `connect` | yes |
| `Ctrl+Shift+K` | `reset` | yes |
| `Ctrl+Shift+D` | `clone` | yes |
| `Ctrl+Shift+N` | `new_local` | yes |
| `F11` | `fullscreen` | yes |
| `Ctrl+Shift+F` | `view_buffer` | yes |
| `Ctrl+=` | `zoom_in` | yes |
| `Ctrl+-` | `zoom_out` | yes |
| `Ctrl+0` | `zoom_reset` | yes |
| `Alt+1`–`Alt+9` | `console_1`–`console_9` | no |

To rebind, set the key against the command name:

```ini
[shortcuts]
CTRL+SHIFT+B = copy_all
```

If a shortcut appears to do nothing, check whether your desktop or OS claims that
combination first — a global hotkey is consumed before GCM ever sees the key, and
`Ctrl+Shift+<letter>` combinations are a common source of this. Rebinding to a free
combination is the fix.

### Sending a custom sequence for a key

Terminals encode keys the traditional way, which loses modifiers on some of them. `Shift+Enter`
reaches a program as exactly the same byte as `Enter`, so an application cannot offer
"Shift+Enter for a newline, Enter to submit" — the two are indistinguishable.

Bind the combination to the bytes you want instead:

```ini
[keys]
SHIFT+RETURN = \n
ALT+RETURN = \x1b\r
```

Key names follow `[shortcuts]`. Values may use `\n`, `\r`, `\t` and `\xNN` escapes.

Which sequence an application wants varies, so there is no useful default — `\n` is the
common choice for "newline rather than submit", but check what yours expects.

A combination already used by a shortcut or by an application accelerator is **refused**,
with a line in the log saying so. Those keys never reach the terminal, so a binding on one
would appear to do nothing. A shortcut also wins if you later rebind one onto a key that
had a custom sequence.

### Terminal shortcuts versus application accelerators

Commands in the table above are *terminal* shortcuts: they are read from your config and,
where the command also appears in a menu, the menu's accelerator is derived from the same
value. Rebinding a command therefore moves its menu accelerator too, and the two can never
disagree.

A few application-level commands carry fixed accelerators that are not part of
`[shortcuts]`, because they are not terminal commands:

| Accelerator | Command |
|---|---|
| `Ctrl+Q` | Quit |
| `Ctrl+R` | Refresh host list |
| `Ctrl+E` | Edit host |
| `Ctrl+Shift+H` | Add host |
| `Ctrl+,` | Preferences |
| `Ctrl+Shift+U` | Cluster mode |
| `Ctrl+Shift+S` | Save buffer |
| `F1` | About |

Avoid rebinding a terminal shortcut onto one of these. Window accelerators are dispatched
before the focused terminal sees the key, so the application command would win and the
terminal binding would never fire.

## What agent CLIs do

Terminal behaviour varies more than it looks, and it decides whether you need `Shift` to
select. Measured directly from the escape sequences each tool emits at startup:

| | Alternate screen | Mouse tracking | Bracketed paste | OSC 52 |
|---|---|---|---|---|
| Claude Code | yes | **yes** | yes | no |
| `agy` | yes | no | yes | no |
| `codex` | no | no | yes | no |

What this means in practice:

- **Claude Code** is the one that takes the mouse. Plain dragging goes to the application;
  hold `Shift` to select. Copy All returns the visible screen only, since it is on the
  alternate screen.
- **`agy`** runs full-screen but leaves the mouse alone, so dragging selects normally.
  Copy All is still limited to the visible screen.
- **`codex`** stays on the primary screen and leaves the mouse alone. Selection, scrollback
  and Copy All all behave as they do at a shell prompt.

None of them use OSC 52, so clipboard integration over SSH is not something they rely on.
All three enable bracketed paste, so multi-line pastes arrive framed rather than being
executed line by line.
