# Connection Manager - Feature Specification

A cross-platform tabbed terminal connection manager built with Qt 6 and PySide6.

**Target platforms:** Linux, macOS, Windows

---

## 1. Connection Types

### SSH
- Username/password authentication
- Private key authentication (with file browser)
- SSH agent forwarding
- X11 forwarding (Linux/macOS)
- Compression (configurable level 1-9)
- Keep-alive interval (0-3600 seconds)
- Port forwarding / tunneling:
  - Local port forward (local port -> remote host:port)
  - Dynamic forwarding (SOCKS proxy)
  - Multiple tunnels per connection
- Implemented via paramiko or asyncssh (no expect dependency)

### Telnet
- Username/password authentication
- Configurable timeout
- Implemented via telnetlib3 (asyncio)

### Local Shell
- Spawns user's default shell
- Linux/macOS: PTY via `os.openpty()`
- Windows: ConPTY via `pywinpty`
- Inherits parent environment

---

## 2. Host Management

### Host Tree
- Left panel with hierarchical group/host tree (QTreeView)
- Drag-and-drop reordering of hosts between groups
- Collapsible groups with persisted expand/collapse state
- Context menu: connect, edit, delete, duplicate, copy address
- Expand all / collapse all

### Host Properties
- Display name and description
- Hostname/IP and port (validated 1-65535)
- Connection type selector (SSH / Telnet / Local)
- Per-host terminal colors (font color, background color)
- Per-host terminal type override
- Backspace/delete key behavior selection
- Automatic commands on connect (multi-line, with delay syntax `##D=<seconds>`)

### Import / Export
- Export all hosts to file (JSON or TOML)
- Import hosts from file
- Preserves full host configuration including credentials

---

## 3. Terminal

### Display
- Terminal emulation: **unresolved, see §14**. Neither candidate is viable as shipped —
  pyte has no alternate screen; termqt has no truecolor, mouse reporting or bracketed paste.
  Assume a custom widget over an extended parser, and spike it before committing to the port.
- Configurable font (default: monospace)
- Per-terminal font zoom (Ctrl+scroll, Ctrl+=/Ctrl+-, Ctrl+0 to reset), clamped to
  0.25x-4.0x, which is the range VTE itself honours. Zoom is per-terminal, not global,
  and is not persisted across restarts.
- Configurable foreground and background colors (global default + per-host override)
- Transparency (where supported by platform)
- Configurable scrollback buffer (1-1,000,000 lines, default 10000)
- Terminal type (TERM) configurable globally and per-host

### Text Operations
- Drag and drop of files onto a terminal inserts shell-quoted local paths (space-separated
  for multiple), with no trailing newline. Non-`file://` URIs are inserted as URIs; dropped
  plain text is inserted verbatim.
- Copy (Ctrl+Shift+C / Cmd+C on macOS)
- Paste (Ctrl+Shift+V / Cmd+V on macOS)
- Copy and paste (combined action)
- Copy all terminal content
- Select all
- Right-click paste (configurable)
- Auto-copy selection to clipboard (configurable)
- Customizable word separator characters for double-click selection

### Search
- Find text in terminal (Ctrl+F)
- Find next (Ctrl+G / F3)
- Find previous (Ctrl+H / Shift+F3)

### URL Detection
- `file:line[:col]` locations are matched and opened in an editor on Ctrl+click
  (`editor-command`, else `$VISUAL`/`$EDITOR` with `+LINE`, else `xdg-open`). Local sessions
  only; relative paths resolve against the terminal's working directory, from OSC 7 when the
  shell emits it and otherwise from the pty's foreground process.
- Regex-based detection and highlighting of:
  - HTTP/HTTPS/FTP/SFTP URLs
  - www.* addresses
  - Email addresses
  - IPv4 and IPv6 addresses
- Clickable links (open in system default browser)

### Session Logging
- Per-terminal toggle
- Configurable log directory
- Logs laid out as `<log-path>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`, mirroring the
  host tree. Identity comes from the host entry, not the tab label, so a renamed tab does
  not move its log. The user is a path segment rather than part of the filename because
  host names are free text and no separator character is collision-proof.
- Session header records `user@host:port` so provenance survives the file being moved
- Separate toggle for local shell logging
- Captures what the terminal receives, so full-screen applications on the alternate screen
  are subject to the same limits as Copy All (see §3 Buffer Management)

### Buffer Management
- Buffer viewer window (`view_buffer`): the scrollback in a `Gtk.TextView`, with
  search-and-highlight, keyboard selection, Copy Selection / Copy All / Save As / Refresh.
  Reads the buffer through the vertical adjustment's row bounds, which leaves any existing
  terminal selection intact.
- Save buffer to text file (Ctrl+Shift+S)
- Reset terminal
- Reset and clear terminal

---

## 4. Tab & Pane Management

### Tabs (QTabWidget)
- Tab labels show the host name, with the program's window title (OSC 0/2) appended when set
  and `tab-title-from-terminal` is on. An explicit rename pins the label against later titles.
- The label's *identity* (host name, or an explicit rename) is kept separate from what it
  renders. Clone, cluster-console selection, notebook moves and session logging all read the
  identity, so a program-set title -- which a remote host controls -- cannot influence them.
- Titles are sanitised (non-printable characters removed, whitespace collapsed, truncated) and
  markup-escaped before reaching any `set_markup` path.
- Multiple concurrent connections as tabs
- Drag-and-drop tab reordering
- Detachable tabs
- Tab scrollbar when many tabs open
- Middle-click to close tab
- Tab close button
- Close confirmation (configurable, separate setting for middle-click)
- Auto-close behavior: Never / Always / Only if no errors
- Rename tab
- Clone connection (Ctrl+Shift+D)
- Reconnect to same host (Ctrl+N)
- Quick tab access: Alt+1 through Alt+9
- Next tab (Ctrl+Tab), previous tab (Ctrl+Shift+Tab)
- Cycle tabs at boundaries (configurable)
- Tab label shows connection name with visual state indicator

### Split Panes (QSplitter)
- Horizontal split (side-by-side)
- Vertical split (stacked)
- Unsplit (merge back)
- Independent terminal in each pane

---

## 5. Cluster Mode

- Dialog to select target terminals from all open connections
- Select all / select none / invert selection
- Multi-line command input
- Send command to all selected terminals simultaneously
- Command history (Ctrl+Up / Ctrl+Down to navigate)
- Selected terminals highlighted in tab bar during cluster session

---

## 6. SSH Connection Handling

- Direct SSH via paramiko or asyncssh — no expect, no prompt scraping
- Authentication methods: password, private key, SSH agent, keyboard-interactive
- Host key verification with known_hosts management
- Automatic reconnection on disconnect (configurable)
- Per-host custom command sequences with configurable delays (sent post-authentication)
- Data bridge: SSH channel <-> terminal widget via async I/O

---

## 7. Security

### OSC 52 Clipboard
- Off by default (`osc52-clipboard`). When on, sessions are spawned under a relay process
  that observes the child's output for `OSC 52` and forwards clipboard writes to the
  application over a Unix socket; when off the spawn path is unchanged.
- VTE implements no OSC 52 and exposes no hook for unhandled OSC sequences, so seeing the
  bytes before VTE does is the only option. A separate process keeps VTE's read path in C
  and prevents a stall there from reaching the interface.
- The read direction (`OSC 52 ... ;?`) is never answered, and only the clipboard and
  primary selections are honoured. Payloads are size-capped and strictly base64-validated.

### Credential Storage
- Platform keyring via `keyring` library:
  - Linux: Secret Service (GNOME Keyring / KWallet)
  - macOS: Keychain
  - Windows: Windows Credential Locker
- No custom crypto, no key files on disk
- Password entry fields masked in UI

### SSH Security Options
- Private key authentication
- SSH agent forwarding toggle
- X11 forwarding toggle (Linux/macOS)
- Compression toggle
- Host key verification (strict by default)

---

## 8. Configuration & Preferences

### Application Behavior
- Confirm on close tab
- Confirm on middle-click close
- Confirm before exit
- Start with local terminal on launch
- Update window title dynamically (with custom title text)
- Check for updates on startup

### Keyboard Shortcuts
- All shortcuts user-customizable via preferences dialog
- Key capture UI for recording new bindings
- Custom command shortcuts (separate from built-in shortcuts)
- Platform-aware defaults (Ctrl on Linux/Windows, Cmd on macOS)

### Default Shortcuts
| Shortcut | Action |
|---|---|
| Ctrl+Shift+C | Copy |
| Ctrl+Shift+V | Paste |
| Ctrl+Shift+A | Copy all |
| Ctrl+Shift+S | Save buffer |
| Ctrl+F | Find |
| Ctrl+G | Find next |
| Ctrl+H | Find previous |
| Ctrl+Tab | Next tab |
| Ctrl+Shift+Tab | Previous tab |
| Ctrl+W | Close tab |
| Ctrl+N | Reconnect |
| Ctrl+Return | Connect to selected host |
| Ctrl+= | Zoom in |
| Ctrl+- | Zoom out |
| Ctrl+0 | Normal size |
| Ctrl+Shift+K | Reset and clear |
| Ctrl+Shift+D | Clone connection |
| Ctrl+Shift+N | New local terminal |
| Ctrl+R | Refresh |
| Ctrl+Q | Quit |
| Ctrl+, | Preferences |
| F1 | About |
| F11 | Fullscreen |
| Alt+1-9 | Jump to tab 1-9 |

### Persistence
- Config directory:
  - Linux: `~/.config/connection-manager/`
  - macOS: `~/Library/Application Support/connection-manager/`
  - Windows: `%APPDATA%\connection-manager\`
- TOML for preferences
- SQLite for host definitions and UI state
- Window size, position, and panel widths remembered
- Group expand/collapse state remembered
- Toolbar and panel visibility remembered

---

## 9. Menus & Toolbar

### Toolbar
- New local terminal
- Connect to selected host
- Add / Edit / Delete host
- Horizontal split / Vertical split / Unsplit
- Preferences
- Find
- Cluster mode

### Terminal Context Menu
- Copy / Paste / Copy & Paste
- Select all / Copy all
- Save buffer
- Split horizontal / vertical
- Reset / Reset & clear
- Clone / Reconnect / Close
- Toggle session logging
- Custom commands submenu

### Host Tree Context Menu
- Connect
- Copy address to clipboard
- Add host to group
- Edit / Delete / Duplicate host
- Expand all / Collapse all

---

## 10. Internationalization

### Supported Locales
- English (en_US)
- German (de_DE)
- French (fr_FR)
- Italian (it_IT)
- Korean (ko_KO)
- Polish (pl_PL)
- Portuguese (pt_BR)
- Russian (ru_RU)

### Implementation
- Qt Linguist (.ts/.qm files) for UI strings
- All UI strings wrapped in `self.tr()` for translation
- Runtime locale override via environment or preferences

---

## 11. Desktop Integration

### Linux
- XDG .desktop file (Network category)
- Application icon in system pixmaps
- System tray integration (optional)

### macOS
- .app bundle with proper Info.plist
- Application icon (.icns)
- macOS menu bar integration (About, Preferences, Quit in app menu)
- Cmd key bindings

### Windows
- Start menu shortcut via installer
- Application icon (.ico)
- System tray integration (optional)
- Native file dialogs

---

## 12. Packaging & Distribution

### Python Package
- pip-installable with pyproject.toml
- Entry point: `connection-manager` CLI command

### Platform Packages
- **Linux:** AppImage or Flatpak for universal distribution, .deb for Debian/Ubuntu
- **macOS:** .dmg with .app bundle (via py2app or briefcase)
- **Windows:** .msi or .exe installer (via briefcase or PyInstaller)

### Runtime Dependencies
- Python 3.10+
- PySide6
- paramiko or asyncssh
- keyring
- pywinpty (Windows only)
- terminal emulation library — undecided, see §14 (pyte as shipped is insufficient)
- telnetlib3 (for telnet support)

### Build System
- pyproject.toml with hatchling or setuptools
- Platform packaging via briefcase (BeeWare) or platform-specific tools

---

## 13. Command Line

- Accepts hostnames as arguments for direct connection on launch
- `--log-level` flag for log verbosity (DEBUG, INFO, WARNING)
- Logging to stderr via Python logging module
- `--version` flag
- `--config-dir` override for portable mode

---

## 14. Architectural Considerations

### Terminal Emulation (the hard part)

This is the dominant cost and the dominant risk of the port. No prebuilt cross-platform
terminal widget exists at VTE's quality level. The candidates below were measured rather
than assumed (2026-08-22; baseline is the current GTK app on VTE 0.76 / GTK 3.24.41).

#### Candidate evaluation

| Capability | VTE 0.76 (today) | pyte 0.8.2 | termqt 1.1 |
|---|---|---|---|
| Alternate screen (`DECSET 1049`) | yes | **not implemented** | yes |
| Mouse reporting (1000/1002/1006) | yes | modes tracked, behaviour is yours to write | no |
| Bracketed paste (2004) | yes | mode tracked, wrapping is yours to write | no |
| Truecolor (`SGR 38;2;r;g;b`) | yes | yes | no, 256-colour only |
| Scrollback + selection | yes | `HistoryScreen`, no separate alt buffer | basic |
| OSC 8 hyperlinks | yes | no | no |
| Regex search | yes (PCRE2) | no | no |
| Throughput | hundreds of MB/s (C) | 1.5-1.9 MB/s (measured) | comparable |
| Provenance | GNOME, 20+ years | last release 2023-11 | 2,888 LOC, one maintainer, 2025-05 |

`qtermwidget` was also considered and rejected: no PySide6 bindings are published, and it is
Konsole-derived and Linux-only, which fails the Windows target outright.

#### Measured detail: pyte has no alternate screen

`ESC[?1049h` is a no-op, and leaving the alt screen does not restore the primary buffer:

```
after ESC[?1049h : 'PRIMARY-CONTENT'   <- should be blank
after ESC[?1049l : 'ALT-CONTENT'       <- should restore 'PRIMARY-CONTENT'
HistoryScreen in alt: no separate alt buffer
```

The last line matters most. With no separate alt buffer, every redraw frame from a
full-screen application is pushed into scrollback, so scrollback becomes unusable while
running exactly the class of tool (agent CLIs, vim, k9s) that motivates the port.

Throughput is adequate for a TUI redrawing at 60fps (~880 full 80x24 screens/sec) but means
bulk output — `cat` of a large log, a verbose build — pegs a core for tens of seconds on
the UI thread. VTE does that instantly.

#### What the port must rebuild

Capabilities the current app gets for free from VTE, which become implementation work:

- Selection model, including Shift-override of application mouse grabs, and word/line/block modes
- Bracketed paste wrapping (works today; absent from both candidates)
- Alternate screen and its interaction with scrollback
- Text extraction APIs backing Copy All / Save Buffer / search
- `bell`, `window-title-changed`, `current-directory-uri-changed` (OSC 7) signals
- Font scaling, hyperlink matching, wide and combining character handling, reflow on resize

Every improvement tracked in issues #14-#26 depends on some part of this substrate. Doing
those improvements "in the rewrite instead" means building the substrate first.

#### Effort

Measured from the current tree: `app.py` is 4,865 lines with ~322 direct toolkit calls
(210 `Gtk.`, 64 `Gdk.`, 24 `Vte.`), plus 2,634 lines of Glade and 2,104 lines of tests.
Toolkit-free logic (`conf`, `Host`, `HostUtils`, encryption, `urlregex`) is roughly 600
lines, so about 80% of the application is rewritten, before the new scope this spec adds.

| Work | Estimate |
|---|---|
| Terminal widget to daily-usable parity | 4-10 weeks, plus a long bug tail |
| Host tree, dialogs, tabs, splits, cluster, preferences | 3-5 weeks |
| SSH via paramiko/asyncssh (tunnels, host keys, agent) | 2-3 weeks |
| Config and credential migration from `~/.gcm` | ~1 week |
| i18n: 8 locales, `.po` to `.ts`/`.qm` | ~1 week |
| Cross-platform packaging and real Windows/macOS testing | 2-4 weeks |
| Test suite rewrite | 1-2 weeks |

Approximately 3-6 months of focused solo work. The line counts are measured; the durations
are judgement, not measurement. The terminal row dominates the total under any assumptions.

#### What the port genuinely buys

- **Windows and macOS.** VTE cannot go there. This is the only justification that carries
  the cost on its own.
- **Dropping `ssh.expect`.** Replacing prompt-scraping with a real SSH library is a
  correctness and security improvement independent of the toolkit.
- **Owning the byte stream.** OSC 52 (#25) and true raw session recording need a ~200-line
  PTY relay under VTE; they are free once the widget reads the stream directly. The hardest
  item on the current backlog is the easiest one after a port.

#### Decision

- The port is justified by cross-platform reach, not by terminal ergonomics. Terminal
  ergonomics get **worse before better**, because VTE's substrate has to be rebuilt first.
- Do not block the GTK fixes (#14-#26) on it. #14 is active clipboard data loss and #15 is
  a dead keybinding; both are trivial. The behaviour they define becomes the specification
  for the Qt terminal widget, so the work carries forward as policy rather than code.
- Before committing to the port, run a spike on the terminal widget alone: alt screen,
  mouse reporting, bracketed paste, truecolor and selection, driven by a real agent CLI.
  If the spike does not reach daily-usable, the rest of the plan does not matter.
- If Windows reach is the actual driver, note that WSLg already runs the GTK application on
  Windows desktops unmodified. That is not a substitute for a native macOS build.

#### Remaining constraints (unchanged by toolkit choice)

- Content that scrolls *inside* a full-screen application is redrawn in place and never
  reaches the terminal linearly. It is unrecoverable by any terminal emulator, Qt or GTK.
- For SSH connections, the terminal widget reads/writes directly to the SSH channel — no
  local PTY needed.
- For local shell, a PTY bridge is needed: `os.openpty()` on Unix, `pywinpty` on Windows.

### SSH: paramiko vs asyncssh
- **paramiko:** Mature, synchronous (can be threaded), widely used, extensive documentation. Better community support and more battle-tested.
- **asyncssh:** Asyncio-native, cleaner API for concurrent connections, built-in support for many SSH features. Better fit if the app is async throughout.
- Either eliminates the expect dependency and works cross-platform.
- Host key verification, agent forwarding, and tunneling are handled natively by both libraries.

### Credential Storage
- The `keyring` library abstracts platform credential stores:
  - Linux: Secret Service API (GNOME Keyring, KWallet)
  - macOS: Keychain
  - Windows: Windows Credential Locker
- No custom encryption code. No key files on disk.
- Credentials are protected by the OS session — unlocked when the user logs in.

### Configuration
- **TOML** for preferences (human-readable, native in Python 3.11+, use `tomli` for 3.10).
- **SQLite** for host definitions: supports sorting, filtering, atomic writes, and scales to thousands of hosts without corruption risk.
- Separate files for preferences, hosts, and UI state so they can be managed independently (backup, sync, reset).

### Async Architecture
- SSH connections, data transfer, and reconnection benefit from async I/O.
- Qt's event loop can integrate with asyncio via `qasync` or `asyncio.QEventLoop`.
- Keep the UI layer synchronous (Qt signals/slots) and push async work into a service layer.
- If paramiko (synchronous), use `QThread` or `concurrent.futures` instead of asyncio.

### Testing
- Separate logic from UI: host management, config parsing, credential handling, SSH setup should all be testable without a display.
- Use `pytest` with `pytest-asyncio` if going async.
- Qt widget tests via `pytest-qt` for integration testing.
- Mock SSH connections with paramiko's test utilities or asyncssh's test server.

### Packaging Strategy
- **briefcase** (BeeWare) can produce native packages for all three platforms from a single Python project. Worth evaluating despite Toga being insufficient — briefcase is toolkit-agnostic and works with PySide6.
- **PyInstaller** is the fallback for Windows/macOS if briefcase doesn't meet needs.
- **AppImage** or **Flatpak** for Linux distribution beyond .deb.
