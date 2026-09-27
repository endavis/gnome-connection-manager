# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at the migration to
[pyproject-template](https://github.com/endavis/pyproject-template); earlier history is in
the git log.

## [Unreleased]

### Added
- A host can run a command on this computer before connecting and another after
  disconnecting, such as bringing a VPN up and down, set on the host dialog's Commands
  tab. Connecting waits for the first, in the host's tab, and goes ahead only when it
  succeeds. The second runs once the session ends, however it ends, quitting GCM
  included. `{name}`, `{address}`, `{port}`, `{user}`, `{group}` and `{type}` are
  replaced by the host's own values, quoted for the shell
- **Hide input** in the cluster window, for a password sent to several consoles at once.
  The box becomes a single line that masks what you type, and what you send from it is
  not kept for `Ctrl+Up` to bring back. The terminal guide now describes the cluster
  window, which only its shortcut table had named
- VNC hosts. A host of type **vnc** shows its remote desktop in the tab, drawn by gtk-vnc
  and scaled to fit, logging in with the host's password and user or asking for them. A
  line above the desktop says why a connection failed or ended, and the tab ends as a
  terminal's does. While the desktop has the keyboard it gets every key, GCM's shortcuts
  included. Without gtk-vnc's bindings, GCM runs a VNC viewer in a terminal tab instead,
  and without either it says so
- Web hosts. A host of type **web** opens a web page, such as a server's management
  console or a switch's admin page, in your browser through `xdg-open`, and no tab. Its
  address is the URL, or a host name opened over `https://` with its port unless it is
  443. Without `xdg-open`, or when it reports a failure, GCM says so
- RDP hosts. A host of type **rdp** opens its remote desktop through FreeRDP, `xfreerdp3`
  or else `xfreerdp`, in a window of FreeRDP's own. Its tab shows what FreeRDP prints and
  takes its questions, and GCM types a stored password at FreeRDP's prompt rather than
  putting it on the command line. The certificate question on a first connection is left
  to you, as ssh's host key question is. Without FreeRDP, GCM says so and opens nothing
- A tab you are not watching is now marked when its output stops, not only when it rings
  the bell, so an agent CLI working in another tab shows when it has finished a turn. Of
  Claude Code, `codex`, `agy` and Copilot CLI, only `codex` rings the bell, but all four
  stop drawing when they are done. **Mark tab when output stops for N seconds** sets how
  long to wait, 5 by default, and 0 turns it off. A tab whose session ends while you are
  not watching is marked too. **Notify when the bell rings** is now **Notify when a
  console needs attention**, and covers all three
- The README says what GCM does, with a screenshot of the window and a feature list, before
  it explains how to build it. It also links the specification and the architecture
  decisions, which existed and were linked from nowhere
- `docs/HOSTS-AND-FOLDERS.md`: the server tree, written for a user. Making, renaming and
  deleting folders (and what deleting one takes with it), where a drop lands and which
  drops are refused, the order a folder keeps and how Sort by Name gives it back, host
  ids, and what export and import carry
- The terminal guide now covers **Copy screen if there is no selection**, the three bell
  settings and the window flag, **Word separator**, and what GCM does with a `gcm.conf` it
  cannot read -- including why it refuses to start rather than start empty
- Continuous integration, for the first time: tests, linting, type checking, security
  scanning and a dependency audit on every pull request
- `doit` as the task runner, replacing `just`
- Pre-commit hooks, including conventional-commit enforcement
- A private Xvfb for the tests that drive real GTK windows, so they no longer take over
  the developer's desktop
- A stable `id` on every saved host, so a host can be referred to from outside its own
  record and still be found after a rename or a move. Existing configurations get one
  the first time they are read; nothing reads the field yet (ADR-0001)
- Folders in the server tree can be created, renamed and deleted: New Folder and Rename
  Folder in the tree's right-click menu and the Servers menu, and `F2` to rename. Renaming
  a folder no longer means editing every host in it, and a folder stays when its last
  host leaves (ADR-0002)
- Hosts and folders can be dragged between folders in the server tree. A drop that would
  put a folder inside itself, or a host beside another of the same name, is refused
- The server tree can be put in any order: drop a host or folder on the line between two
  rows and it stays there. A folder you never arrange keeps sorting by name, and Sort by
  Name hands one back to that (ADR-0002)

### Changed
- Custom commands are listed by name in the terminal menu and the menubar, in folders,
  and one without a key is kept and sent from the menus. A command can name the values of
  the tab's host, `{name}`, `{address}` and the rest, typed as they are, and `{?Label}`
  asks for a value as it is sent. `gcm.conf` keeps each as a `[snippet <id>]` record,
  which may give it a name, a folder and a description; GCM takes up the old
  `shortcutN` and `commandN` pairs once, and writes each command with a key back as a
  pair for an older GCM
- Connection types moved out of `app.py` into `utils/connections.py`, one class per type,
  and the host dialog lists them from there rather than from the glade file. A new type
  adds a class instead of a branch in each place that compared a host's type by name.
  Every host opens with the same command as before
- A connection type can have settings of its own. The host dialog shows them on a page
  of that type's own while it is chosen, and a host saves them in its section of
  `gcm.conf` as `<type>.<name>`, so copying, exporting and importing a host carry them.
  No type has any yet: VNC and RDP in a tab will be the first. An option with a dot in
  its name in a host's section is now kept when GCM saves, rather than dropped
- A tab can hold something other than a terminal, which VNC, web views and RDP in a tab
  will need. Every tab is opened the same way, and what acts on a tab first asks whether
  it holds a terminal: one that does not can be renamed, closed, split and moved between
  panes, and terminal actions leave it alone. Nothing opens such a tab yet
- `docs/SPEC.md` says at the top that it specifies a Qt 6 port that is not being built, so
  it can no longer be mistaken for a description of the program. It was the only account of
  folders anywhere
- Configuration lives in `~/.config/gcm/` on a new installation, honouring
  `$XDG_CONFIG_HOME` where it is set. One that already has `~/.gcm/` goes on using it, in
  place: nothing is copied or moved, and moving the directory yourself is all it takes to
  switch. `.gcm.key` and the default log root follow `gcm.conf`, and an existing
  installation's logs stay where they are, since its log path is written into `gcm.conf`
  on every save
- A tab's label is cut at 30 characters, so one long name no longer pushes the other tabs
  behind the scroll arrows at the ends of the tab strip. The cut is only what is drawn:
  the tooltip and the open-console list still give the whole label, and renaming or
  closing a tab asks about the tab's own name
- Collapsed folders in the server tree are remembered by folder rather than by row
  position, so a change in the shape of the tree no longer leaves the wrong folders
  collapsed. The positional setting is still written for older versions
- Folders in the server tree are stored as records of their own in `gcm.conf`, with each
  host filed under one by id. `group` is still written, derived from the folder, so older
  versions read the file unchanged. An existing configuration converts the first time it
  is read, and nothing changes on screen (ADR-0002)
- Custom-key parsing and font-scale clamping moved out of `app.py` into
  `utils/shortcuts.py`, tested without the `gi` stub
- Session-log naming moved out of `app.py` into `utils/logpaths.py`, with the log root
  passed in rather than read from `conf`
- `Host` and `HostUtils` moved out of `app.py` into `utils/hosts.py`; their passphrase
  and legacy-format flag are now arguments rather than defaults read from globals
- Password encryption moved out of `app.py` into `utils/crypto.py`, where it is tested
  directly rather than through the `gi` stub that hid a real fault in it
- Python floor raised from 3.8 to 3.12, matching what was actually being used and tested
- Default branch renamed from `master` to `main`
- Buffer size and Show the program title in the tab now reach the consoles already open
  when Preferences is closed with OK, not only the ones opened afterwards. Shrinking the
  buffer drops the oldest lines of a session that holds more
- So do the font, the colours, Transparency, Word separator and Audible bell. A host with
  colours of its own keeps them, and a console keeps its zoom when the font changes

### Fixed
- A custom command that held a backslash and an n came back from a restart with a new
  line in their place. One saved now comes back as it was written; one saved before
  cannot say which it held, and is kept as GCM has been sending it. The menubar also
  left out each `_` in a command
- Ctrl+click on a link did nothing where GIO finds no browser, as under WSLg: GTK raised
  `Operation not supported` and nothing opened. Links now open through `xdg-open`, as web
  hosts do. An email address now opens as `mailto:user@example.com`, not
  `mailto://user@example.com`, which a URI parser reads as a user at a host, with no
  address in it. And a scheme in capitals, such as `MAILTO:`, now reaches its handler:
  `xdg-open` looks one up by the scheme as written, and found none
- With the keyboard in the server tree or the search box, a console shortcut acted in the
  pane of the last terminal GCM had given the keyboard to: a new tab's, say, or the one
  left showing by a split. Clicking into a terminal did not count, so after a click into
  the other pane, Ctrl+W closed a tab in the first. A shortcut now acts in the pane you
  were last in
- An item chosen from a terminal's menu acted on the terminal with the keyboard. After a
  split, with the keyboard in one pane, the menu of a terminal in the other pane pasted
  into, cleared, cloned or closed the terminal you were typing in. It now acts on the
  terminal you opened it on
- A console shortcut could act on a tab other than the one in use. Once a tab's menu had
  been opened and dismissed, the next paste went into that tab, or Ctrl+W closed it,
  though another tab was showing and had the keyboard. Clone, Reset and Reconnect by key
  acted on the last tab whose menu had been opened, and did nothing before any had been.
  A shortcut now acts on the tab showing in the pane you are typing in, and an item in a
  tab's menu on that tab
- The account of how stored passwords are encrypted, in `utils/crypto.py` and `AGENTS.md`,
  named the cipher mode as CTR. It is OFB. The two agree on the first 16 bytes only, so
  code written from that account would read a password shorter than 16 bytes and garble
  any longer one
- A host with a stored password trusted a host key it had not seen before, without
  asking. GCM answered ssh's question itself and went on to type the password, so a first
  connection sent the stored password to whichever server answered. The question is now
  yours, as it is for a host without a stored password, and GCM types the password once
  you have answered `yes` or pasted the fingerprint. To have new keys trusted without the
  question, add `-o StrictHostKeyChecking=accept-new` to the host's **Extra arguments**;
  ssh still refuses a key that has changed
- A host with a stored password whose ssh was killed by a signal ended with the status of
  a clean exit, so **Only on clean exit** closed its tab. It now ends with 128 and the
  signal's number, as a shell reports it, so Ctrl+C at the host key question leaves the
  tab open
- A host with a stored password showed nothing that came before its login: the banner,
  telnet's own lines, and on a first connection ssh's question about the host's key,
  which GCM answers for you. The key's fingerprint, and ssh's warning that it had been
  added to the known hosts, never reached the tab, though the key was trusted all the
  same. A tab now shows all of it as it arrives, as for a host without a stored
  password. That includes the prompts GCM answers, but never the password
- A host with a stored password that could not connect left an empty tab, with nothing to
  say why. The error ssh or telnet gave, such as a name that does not resolve or a port
  that does not answer, never reached the tab. It does now, as it always did for a host
  without a stored password
- **Close console** set to **Only on clean exit** never closed a tab. It asked the terminal
  for the exit status in a way VTE no longer supports, which failed on every session end
  and left the tab open. It now goes by the status the session ended with, and a tab it
  keeps open is marked like any other whose session ends while you are not watching
- With **Close console** set to **Always** or **Only on clean exit**, closing a tab by hand
  raised an error. It showed only on stderr, and the tab closed anyway
- An SSH host whose key check failed ended with the status of a clean exit, so **Only on
  clean exit** would have closed the tab over the message. It now ends with ssh's own
  status
- Two copies of GCM opening the same host at the same moment, one logging the session and
  the other only recording it, can no longer give both sessions the same number
- Two tabs for one host opened together -- by naming it twice on the command line, say --
  no longer record into the same `.raw` when text logging is off. Each takes a number of
  its own
- A session's raw recording and its timing file now take the same number as its text log.
  They were numbered separately, so after a session that was not recorded, the next one
  wrote `002.log` beside `001.raw`. A reconnected tab now adds to its recording instead of
  starting another, the way its text log already carries on in the same file
- `docs/TABLE_OF_CONTENTS.md` had a "For Users" section listing eight documents about
  pyproject-template and none about GCM, because it filters on frontmatter and none of this
  project's nine documents had any. They have it now, under headings of their own -- Using
  GCM and Working on GCM -- with the template's list kept separately and labelled as what it
  is. `mkdocs.yml` was missing the hosts-and-folders guide and the ADRs; tests now hold the
  nav and the docs directory to each other
- The README no longer writes the version out -- twice, in prose and in an `apt install`
  command, outside the test that keeps the other four copies in step. `make deb` names the
  file it wrote, and the install command takes a glob
- The README's development-phase roadmap claimed the test suite was still to be written,
  as did `docs/PROJECT_STRUCTURE.md` in two places. The roadmap is gone from the front page
  and the claims are corrected; the lint and test figures that used to be quoted are left
  to `doit check`, which keeps them
- Unticking the checkbox on a host's Commands page discarded the commands when the
  dialog was closed; the tick is now stored separately, so it only decides whether
  they run
- The README and the developing guide still told a reader to install and use `just`
- Session logs were written to `logs/session/` rather than the host's own directory
- The encryption key protecting saved host passwords was generated with `random.random()`
- Saving a preference containing a double quote raised `SyntaxError` and silently failed
- Every translation catalog carried duplicate message definitions, which `msgfmt` rejects
- The application reported version 1.2.1 while the package said 1.2.0 and the `.deb` 1.2.2
- Passwords in a config predating the `version` key all decrypted to nothing: the legacy
  XOR helpers raised `TypeError` on Python 3 and swallowed it, and test shims hid it
- A `gcm.conf` with a repeated section, which is what merging two copies by hand
  produces, stopped GCM starting: no window, and the reason only on stderr. A repeated
  host or folder is now kept as an entry of its own and a verbatim copy dropped, and an
  import reads such a file too
- A `gcm.conf` that cannot be read in full now stops GCM before its window opens, with a
  message saying what is wrong and where. One it could not open at all used to start it
  empty, and closing the window then wrote that empty list over the file
- Saving dropped the `[keys]` section from `gcm.conf`, so a custom key sequence lasted one
  session. A save now keeps every section GCM does not write itself, read from the file
  as it is on disk, so a `[keys]` edit made while GCM runs survives too
- A `gcm.conf.tmp` left behind by an interrupted save made every later save fail, so each
  session's changes were lost at close, with the error only on stderr
- A save wrote over a `gcm.conf` broken by hand while GCM ran, losing the edit. A file it
  cannot read is now kept aside as `gcm.conf.unreadable-<time>` first
- The terminal guide's example for rebinding a shortcut put the key where the command
  goes, so following it changed nothing and nothing said why
- Save Transcript on a session with no recording said to turn on `raw-session-log` in
  `gcm.conf`, which never takes effect while GCM runs. It now names the checkbox that has
  been in Preferences all along, Record the raw session
- The terminal guide gave only a `gcm.conf` line for settings that have a control in
  Preferences, and an edit to that file while GCM runs is written over. It now names each
  control and says whether a change applies straight away or to sessions opened after it
- The terminal guide's paste example put a `;` comment after each value, which GCM reads
  as part of the value. Copied as written, all three settings were rejected and the
  defaults used
- The terminal's menu could not be opened with default settings: right-click pastes, and
  nothing else opened it, though the terminal guide sent readers there. Ctrl+right-click
  now opens it whether or not right-click pastes; it used to paste like a plain one
- The terminal guide named the View buffer menu item by its Spanish source string,
  Ver buffer
- A value in `gcm.conf` that GCM could not read was replaced by the default at the next
  save, with only a line on stderr to say so. The line is now kept as written until the
  setting is changed, and GCM lists such values in a notice when it starts
- Renaming the tab of a session that had ended made it look live again: the grey,
  struck-through label went back to plain text
- Once more lines had been printed than Buffer size holds, View buffer and Save buffer
  to file left out the newest output, the screen included, and opened with an empty
  line for every line dropped. They now hold the same lines as Copy All
- Split and Unsplit reset the tabs they moved. The title the program had set, a rename,
  the grey strikethrough of an ended session and its Reopen menu item, and the marks
  the bell and the cluster window leave were all lost. A tab now moves with its label
- Closing the Preferences window in the instant it opened left a repeating idle behind,
  and GCM froze the next time a console was opened. A probe found it; no user is known
  to have hit it
