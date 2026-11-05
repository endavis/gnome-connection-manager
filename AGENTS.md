# AGENTS

Notes for future coding agents working on Gnome Connection Manager (GCM).

## Mission & Primary Entry Points
- GCM is a GTK 3 + VTE based SSH/telnet tabbed terminal manager written in Python.
- Core application logic lives in `src/gnome_connection_manager/app.py`; `main.py` and
  `__main__.py` are thin entry points.
- UI layout and signal wiring live in `data/ui/gnome-connection-manager.glade`; widgets are
  loaded through `Gtk.Builder` (the `GladeComponent` helper inside `app.py`).
- Terminal behavior is customized through `data/style.css`,
  `src/gnome_connection_manager/utils/urlregex.py` (link detection patterns), and helpers
  such as `data/scripts/ssh.expect` and the external `pyaes` library.

## Repository Map
- `src/gnome_connection_manager/app.py` – the configuration (class `conf`), the windows and
  the application (`Wmain`, `Whost`, `Wconfig`, `GcmApplication`), the key file and VTE. Large
  by design: only pure logic comes out of it, into `utils/`. Notes: its module docstring.
- `src/gnome_connection_manager/main.py` and `src/gnome_connection_manager/__main__.py` –
  entry points (`doit launch` uses these).
- `src/gnome_connection_manager/relay.py` – the PTY relay a session runs under while OSC 52 or
  raw recording is on: it finds OSC 52 and records the stream. It starts through
  `childpython.module_command`, never `python -m` (#415). Notes: `docs/design/recording.md`.
- `src/gnome_connection_manager/utils/urlregex.py` – prebuilt PCRE2-compatible regex strings
  for hyperlink detection inside terminals, including `file:line` locations.
- `src/gnome_connection_manager/utils/hosts.py` – the `Host` record and `HostUtils`, which read
  and write it in gcm.conf. A host option with a dot in its name is a connection type's
  setting, so an option of the host's own has none. Notes: its docstrings and comments.
- `src/gnome_connection_manager/utils/placeholders.py` – a host's values filled into a
  command written for it (#238), which the caller quotes; `{password}` is never filled with
  the password (#248). Notes: its docstring, and `app.py`'s `run_before_command`.
- `src/gnome_connection_manager/utils/snippets.py` – the snippet library (#240): text typed
  into a console on request. A save also writes each snippet with a key as a `[shortcuts]`
  pair, for an older GCM to read. Notes: its docstrings and those of `app.py`'s snippet code.
- `src/gnome_connection_manager/utils/connections.py` – one class per kind of host (#228), in
  `CONNECTION_TYPES`: a new type adds a class, not a branch in `app.py`. A test must never reach
  the real `mstsc.exe` or a real browser. Notes: `docs/design/connection-types.md`.
- `src/gnome_connection_manager/utils/remotefiles.py` – a host's files outside its console
  (#267), over SFTP or an sshfs mount the Mounted tab lists (#269), with no password in an
  argument. Notes: its docstrings, and those of `app.py`'s `mount_files` and `list_mounts`.
- `src/gnome_connection_manager/utils/folders.py` – the folder tree hosts are filed under
  (ADR-0002). `host.group` is a path derived from the host's folder, true only while no two
  folders share a path. Notes: its docstrings, and `app.py`'s `sync_folders`.
- `src/gnome_connection_manager/utils/configfile.py` – how gcm.conf and an imported export
  are read, never by `cp.read` (#161). A section a save writes goes in `WRITTEN_SECTIONS`,
  a new kind of record in `RECORD_PREFIXES` (#163). Notes: its docstrings and comments.
- `src/gnome_connection_manager/utils/configpaths.py` – which directory holds `gcm.conf` and
  `.gcm.key` (#192). Nothing is migrated, and `resolve` creates nothing: a directory made
  before the choice would be the one chosen. Notes: its docstrings and `require_config_dir`'s.
- `src/gnome_connection_manager/utils/crypto.py` – password encryption for stored hosts, and
  the two older formats it must still read. OFB, not CTR: a port in CTR reads a password
  shorter than 16 bytes and garbles any longer one (#206). Notes: its docstrings.
- `src/gnome_connection_manager/utils/logpaths.py` – where a session's files go, and the cut of
  a long tab label (#190). A session's files share a number, claimed by creating one empty: an
  empty `.log` is a claim, not an old log (#202). Notes: `docs/design/recording.md`.
- `src/gnome_connection_manager/utils/tabnames.py` – what a host's tab is called (#346–#349).
  A tab keeps the record it was opened for, so read the host's current one through
  `configured_host`, by its id. Notes: `docs/design/tabs.md`.
- `src/gnome_connection_manager/utils/tabcolors.py` – the colour a host's tabs and tree row are
  marked with, its own or its nearest folder's (#350, #358). `color_of` reads only `#rgb` and
  `#rrggbb`, so a hand edit can put nothing else into the CSS. Notes: `docs/design/tabs.md`.
- `src/gnome_connection_manager/utils/menuplacement.py` – where a pop-up menu goes so that it
  stays on the screen on both axes, as WSLg's Weston moves none (#392, #398), and how far a
  wheel notch scrolls a long menu (#399). A new pop-up menu opens through
  `popup_menu_at` in `app.py`, as the other five do; one GTK places, a submenu or a menu
  bar's, gets `fit_placed_menu` on `show` (#397). Notes: `docs/design/menus-and-windows.md`.
- `src/gnome_connection_manager/utils/shortcuts.py` – the shortcut decisions that need no
  widget. A key typed into a console is its program's, bar what `[shortcuts]` binds (#419),
  and the key after a prefix key is its program's whatever it is (#452).
  Notes: its docstrings and comments, and those of the `app.py` code they name.
- `src/gnome_connection_manager/utils/activity.py` – when a console busy out of sight has
  gone quiet (#208). It is asked on a timer that runs only while a tab waits, so an idle
  console costs nothing. Notes: its docstrings, and `app.py`'s `check_quiet`.
- `src/gnome_connection_manager/utils/afterlogin.py` – when a host's commands after login are
  typed, and what becomes of keys typed before then (#312). A fake ssh in a test enters raw
  mode with `TCSADRAIN`, as ssh does. Notes: its docstrings, and `app.py`'s `hold_key`.
- `src/gnome_connection_manager/utils/updates.py` – whether this repository has released a
  newer GCM (#295), compared as numbers. The request runs as a process of its own, never on
  a thread (#369). Notes: its docstrings, and `app.py`'s `check_updates`.
- `src/gnome_connection_manager/utils/wslg.py` – whether WSLg's log shows it cannot draw
  windows (#414), said on the console by `main()`. Notes: its docstrings.
- `src/gnome_connection_manager/utils/trace.py` – `GCM_TRACE`'s areas (#507): a call site passes a lambda
  to `trace.note`, which never raises, and logs no value, key typed into a console, or console text (#513). Notes: its docstrings.
- `src/gnome_connection_manager/utils/childpython.py` – how GCM starts its Python children,
  the relay and the update check (#415). Never `python -m`: under `install.sh`'s launcher a
  fresh interpreter cannot import GCM. Notes: its docstrings, and `tests/test_childpython.py`.
- `src/gnome_connection_manager/utils/osc52.py` – OSC 52 writes: one copy from a pair (#393), and
  a write set again where WSLg's Weston ignored it (#412, #413). Under WSLg GCM then owns GDK's
  event handler: chain any hook through `Wmain.watch_gdk_event`. Notes: `docs/design/clipboard.md`.
- `src/gnome_connection_manager/utils/vtehtml.py` – parses VTE's HTML grid export into styled
  runs for the buffer viewer.
- `src/gnome_connection_manager/utils/transcript.py` – rebuilds a readable transcript from a
  raw recording, replayed by `TranscriptReplayer` in `app.py`, which reads rows by the cursor,
  never by the vertical adjustment (#344). Notes: `docs/design/recording.md`.
- `tools/sandbox.py` – the throwaway HOME `doit sandbox` runs GCM against (#506), written
  with GCM's own writers, under `tmp/sandbox_cache` so a worktree stays removable (#332).
- `tools/build_mo.py` – compiles a `.po` into a `.mo` without gettext. `doit translate` is the
  canonical path; this exists because `msgfmt` is not installed everywhere.
- `tools/packages.py` – what the `.deb` and the `.rpm` declare, read from the Makefile's
  `deb` and `rpm` recipes, the one list of what GCM needs and can use (#273). CI's
  `package` job holds the built packages to it. Notes: `docs/design/packaging.md`.
- `data/ui/gnome-connection-manager.glade` – GTK Builder UI definition. Keep widget
  names/signals aligned with handler names in `app.py`.
- `data/scripts/ssh.expect` – the Expect script that runs a host with a stored password, and
  only such a host: it types the password, passes the tab's size on, and hands the terminal
  over. Inside an `expect` block a `#` line is a pattern, not a comment. Notes: its comments.
- `data/scripts/gcm-askpass` – ssh's askpass for a mount (#267): it answers only a password
  prompt, from `GCM_PASSWORD`, refusing the host key question above all (#216). A test
  checks that the Makefile installs every script here executable. Notes: its comments.
- `data/style.css`, `data/icon.png`, `data/ui/donate.gif` – assets.
- `tests/` – the automated suite (see below). `tests/conftest.py` stubs all of `gi`;
  `tests/xdisplay.py` starts an Xvfb of a run's own, `doit sandbox --xvfb` too (#509).
- `lang/` – gettext `.po` sources and compiled `.mo` files under
  `<lang>/LC_MESSAGES/gcm-lang.mo`, for de, es, fr, it, ko, pl, pt and ru. English has none:
  the msgids are English (ADR-0003, #390). Notes: `docs/design/translations.md`.
- `docs/` – see [Documentation](#documentation).
- `gnome-connection-manager.desktop`, `Makefile`, `dodo.py`, `pyproject.toml`.
- `install.sh` – the one-line installer (#294): one worktree per version, a `current` link,
  and a launcher holding a shared `flock` on its version. An update never changes a
  version's files, which a running GCM still reads. Notes: `docs/design/packaging.md`.
- `.claude/`, `.agents/`, `.codex/`, `.copilot/`, `.github/instructions/`, `.github/skills/`,
  `.github/hooks/` – agent configuration, vendored from pyproject-template and replaced on a
  sync: a fix goes upstream, by `report-template-bug`. Notes: `docs/development/ai/`.
- `docs/development/` – how the vendored tooling works: the doit tasks, CI, repository settings
  and `docs/development/ai/`. Written for the template: it describes machinery GCM has but does
  not always use, as the banner on `docs/development/release-and-automation.md` says.
- `docs/decisions/` – Architecture Decision Records, created with `doit adr`. GCM's own are
  numbered from 0001; those from 9001 and the folder's `README.md` are the template's, synced
  with it (#324). Notes: the README, and `VENDORED_DOC_PATTERNS` in `tests/test_docs.py`.

## Documentation
- `docs/TERMINAL-USAGE.md` – user-facing, everything inside a tab: selection and what a
  word is, copy when nothing is selected, pasting, session logs and raw recording, OSC 52,
  the buffer viewer, tab titles, consoles in windows of their own, the cluster window, the
  bell and a tab's other marks, a session that ends or drops, font zoom, the shortcut
  table, snippets, a host's first connection, and what GCM does with a `gcm.conf` it
  cannot read.
- `docs/HOSTS-AND-FOLDERS.md` – user-facing, everything in the server tree: making,
  renaming and deleting folders, what a drop does where, the order a folder keeps, host
  ids, and export/import; then the host dialog, commands on this computer, each
  connection type besides SSH and Telnet, and a host's files over SFTP and SSHFS, with the
  Mounted tab. Written because the only account of folders was `docs/SPEC.md`, which
  specifies a Qt port that is not being built (#193).
- Every setting Preferences draws a control for must be named in one of those two, by its
  `gcm.conf` key or by its label. `tests/test_docs.py` enforces both directions now:
  guide to code, and code to guide against `UNDOCUMENTED_SETTINGS`, whose entries each
  carry a reason. Four settings had shipped with a control and no mention anywhere before
  the second direction existed.
- `docs/WSL-SETUP.md` – user-facing, GCM on Windows in Ubuntu under WSL (#274): a clone
  run with `UV_PYTHON=/usr/bin/python3`, a `wslg.exe` shortcut, keychain above
  `.bashrc`'s interactive check, `dbus-update-activation-environment` so that GVfs's
  `ssh` has the agent, Nautilus with `gvfs-backends`, sshfs, the scale set by hand since
  WSLg reports every monitor at scale 1, and WSLg's own faults. It was measured on WSL
  2.7.13 with Ubuntu 24.04. A step that would change the machine was run with a scratch
  home, a settings store of its own, or a Windows temp folder, and the guide says which
  steps were not run: switching systemd on, and `wsl --install`. A step added to it is
  measured too, or says it was not.
- `docs/HEADLESS-DEVELOPMENT.md` – contributor-facing, developing on an Ubuntu 26.04 machine
  with no screen (#428), a VM or an LXC container, each step marked with which it applies to.
  The LXC path was measured on an unprivileged Proxmox container: it needs `fuse=1`, and the
  `ssh-keyscan` and `fusermount3` AppArmor profiles in complain mode. The VM path was not
  tried. The suite passes on 26.04 there: the 11 tests that failed with GCM working, #427,
  accept both versions since PR #431.
- `docs/DEVELOPING.md`, `docs/PROJECT_STRUCTURE.md` – development setup and layout.
- `docs/design/` – design notes for an area that spans files, moved out of this file (#430):
  why each choice was made, what was measured, and what was rejected. An entry in this file
  names each page. Read it before changing that area, and keep it true in the same change.
- **A new document under `docs/` needs three things**, and `tests/test_docs.py` checks each:
  YAML frontmatter with `title`, `description`, `audience` and `tags` including `gcm`; an
  entry in `mkdocs.yml`'s hand-written `nav`; and `uv run python tools/generate_doc_toc.py`
  run so `docs/TABLE_OF_CONTENTS.md` picks it up (a pre-commit hook does this too). Quote
  the `title` and `description`: a colon in an unquoted YAML scalar makes `safe_load` raise,
  and the generator swallows that and treats the file as having no frontmatter at all (#198).
  `audience: users` belongs to the vendored template documents and means users *of the
  template*; GCM's own user guides are `gcm-users`, and the TOC sections for GCM follow the
  `gcm-guide` and `gcm-dev` tags rather than an audience.
- `docs/SPEC.md` – feature specification. §14 holds a measured analysis of a possible
  Qt/PySide6 port (conclusion: don't, for terminal ergonomics). Every figure in its Effort
  section is re-measured by `tests/test_docs.py`, so one cannot be restated without
  measuring it -- the share rewritten stood at 85% against a true 77% for want of that.

## Dependencies & Environment
- Runtime: Python 3, PyGObject (`python3-gi`), GTK 3, `gir1.2-vte-2.91`, and `expect`.
  `expect` is checked in `main()`, not at import: the check used to run while the module
  was being imported and report through a modal dialog, so importing it headless hung
  forever (#118). Keep imports side-effect free. VTE
  terminals expect a usable `$SHELL` and system `ssh`/`telnet` binaries.
- Build/packaging: gettext `msgfmt`, Ruby + `fpm` (for `.deb` and `.rpm`), gzip, binutils
  for the `ar` fpm builds a `.deb` with, and `rpm` for `rpmbuild`. CI's `package` job
  installs them on ubuntu-24.04, fpm 1.18.0 among them, and `desktop-file-validate` for
  the desktop entry.
- Preferred tooling: the doit tasks — `doit launch`, `doit sandbox`, `doit test`, `doit lint`,
  `doit type_check`, `doit translate`. `doit list` shows them all. Project-specific
  tasks live in `tools/doit/gcm.py`; the rest of `tools/doit/` is vendored from
  pyproject-template and is replaced wholesale on a sync. Where GCM's needs differ,
  `tools/doit/gcm.py` overrides a vendored task by name, and `dodo.py` installs the
  override after discovery. `audit` audits `uv.lock`, not an environment that holds every
  package apt installed. `check` leaves out `wheel_check`, whose clean virtualenv cannot
  import GTK, measured (#324). `worktree` builds a new worktree's `.venv` a second time,
  from `/usr/bin/python3` with the system's site packages, as CI builds GCM's (#327).
  `release_tag` used to send GCM's developers to a build and to PyPI pages that do not
  exist, until #306 changed it here. The template carries that change itself since
  pyproject-template#993, and `tests/test_release_tag.py` still checks it. For anything
  without a task, use `uv run …` so the repo's environment is honored.

## Testing & Verification

**Tests are automated.** `doit test` runs the suite; `doit coverage` adds coverage. Add
tests with behavior changes rather than documenting a manual test surface.

Practices below have each caught real bugs in this repo. They are worth the time:

- **Measure, don't assume.** Write throwaway probes against real GTK/VTE — `DISPLAY=:0`
  works under WSLg. Assumptions about VTE behavior have been wrong far more often than right:
  VTE 0.76 does not emit `increase-font-size` on Ctrl+scroll, it clamps `set_font_scale()` to
  0.25–4.0 itself, and a line selection reaches the clipboard as `text\n\n`. Its row
  numbers keep counting once the scrollback drops the oldest rows, while the vertical
  adjustment starts again from 0: read as row numbers, the adjustment hid the newest
  output from View buffer (#179). The cursor is reported in the numbering
  `get_text_range_format` takes; the adjustment is not.
- **Mutation-test new tests.** Revert the fix and confirm the test fails. This has caught
  several tests that passed against broken code. In a worktree, unset `GCM_DATA_DIR`,
  `GCM_GLADE_DIR` and `GCM_SCRIPTS_DIR`: `main()` sets them, a shell in a GCM tab inherits
  them, and measured, they gave the worktree's GCM the main checkout's `data/`, so a
  mutant of a script there went unseen and survived. And a mutant the size of the code it
  replaces, as `exists` is of `is_dir`, written within the second of the file's last change,
  runs the old `.pyc`: Python checks only a source's size and its time to the second,
  measured on 3.12.3. Delete `__pycache__` first.
- **The weekly mutation run is mutmut over `utils/`, `relay.py` and `main.py`** (#326),
  as `[tool.mutmut]` in `pyproject.toml` sets it up. Not `app.py`: mutmut's copy of a
  module holds every mutant of it, and `app_module` imports `app.py` afresh for each
  test, which measured, made every such test take about a second. It runs each test file
  that imports the package or takes `app_module`, bar those `tests/test_mutmut_config.py`
  excuses, and that test fails on one left out. A subprocess started from mutmut's copy
  imports the package from the tree, not from the copy, measured, so the real-GTK
  scenarios are left out, and `relay.py`'s mutants are reached by `tests/test_relay.py`,
  which runs it in pytest's own process. A mutant no input tells apart from the original
  is marked `# pragma: no mutate`, the reason beside it, where every mutant on its line
  is one: mutmut 3.7.0 marks whole lines, so one sharing a line with a mutant a test
  kills is left alive, and #337 records which. mutmut makes all its runs in one process and forks it for each
  mutant, and GTK stays connected to the first run's Xvfb, which ends with that run: its
  clean run exited 1 and printed nothing. So `tests/conftest.py` keeps the real `gi` out
  of mutmut's process, and a selected test that wants it asks with
  `pytest.importorskip("gi")`, which the same test checks. Nor does that process get an
  Xvfb, or keep a display at all: mutmut ends a mutant that runs too long with SIGXCPU,
  then SIGKILL, so `pytest_unconfigure` never stopped one, and each such mutant left its
  Xvfb running (#341). A pytest that a selected test starts has no mutmut in it, and
  starts an Xvfb of its own. A test that reads the source
  rather than running it sees every mutant at once, and is left out or deselected there.
  The test file is GCM's own: the template's, which a sync offers, checks the template's
  selection.
- **Verify what is rendered, not what the model says.** A menubar was once "verified" by
  walking its `Gio.Menu` when it had never been rendered at all (#43). Walk the widget tree.
- **A test that reads the screen raises its window first.** Every xdist worker's windows
  open on the one Xvfb, all at +0+0 with no window manager, and measured, a read of a
  covered window returns what covers it. `on_screen` in `tests/test_vnc.py` failed on CI
  so, reading another test's console as black, until it raised its window (#250). When
  looking for what covers a window, `xwininfo -root -children` lists the top-most first.
- **Real X input comes through XTest, by ctypes.** python-xlib is not a dependency, so
  `tests/test_console_window.py` loads libXtst, which CI installs as `libxtst6`. Keys and
  the keyboard's place are a display's, so a test using them runs on an Xvfb of its own:
  on the shared one, another worker's windows take them. Two workers can choose the same
  free display number, and measured under load, the loser's server took long enough to
  exit that two scenarios ran on one display, each typing into the other's windows, until
  one finished and took the server down. So `_private_display` counts a display as its
  own only once the lock file Xvfb writes names its process. A GTK process whose X server
  goes away exits with status 1 and prints nothing, measured.
- **Wayland is measured on sway, headless.** WSLg takes no synthetic input, and Xvfb
  answers for X11 only. Ubuntu's sway runs from its packages unpacked with
  `apt-get download` and `dpkg -x`, under `WLR_BACKENDS=headless`, and a small C client of
  the `zwlr_virtual_pointer_manager_v1` protocol, built against `libwayland-dev`'s
  headers, moves and presses its pointer (#255). Keep its `XDG_RUNTIME_DIR` short: a
  socket's path holds 108 bytes. Wayland tells a client nothing of where its windows are,
  so find a widget on the output by putting the pointer in its window and asking GTK
  where it is. Measured, sway 1.9 often refused a drag begun seconds after a cancelled
  one, with GCM's handling of it and without, so a drag that never ends is sway's while
  its log says `Rejecting start_drag`.
- **An ssh a test runs reads `~/.ssh` unless told not to.** Measured, `ssh -F <file>`
  reads no other configuration but still offers the default keys in `~/.ssh`, unless
  the file says `IdentityFile none`. `tests/test_host_files.py` gives ssh known hosts, a
  key and no agent of its own, and runs sshd as the user on 127.0.0.1, serving SFTP from
  a folder of the test's through `internal-sftp -d`. An sshd not run as root checks no
  password, so the mount a stored password makes goes through a fake ssh that asks the
  helper. Its GIO scenarios give GIO data folders that link everything of the system's
  but `applications`, so that no folder application the system has can open.
- **A signal handler's exception does not end a scenario.** PyGObject prints it and
  carries on, measured: the scenario exits 0 having printed OK. So
  `tests/test_console_window.py` also fails on a traceback in the scenario's stderr.
- **A scenario builds GCM with the update check off**, `app.conf.CHECK_UPDATES = False`,
  and a scenario about the check starts it itself, against an answer of its own: with it
  on, every scenario longer than 2 s asked GitHub for the tags. On the daemon thread the
  check had before #369, the registry's open-in-browser scenario exited during its request
  on every run, measured, and is the one that died of SIGSEGV at exit on CI (#316).
  `test_no_scenario_runs_the_check` fails on a scenario script that leaves it on.
- **CI fails on any skipped test.** Its `Run tests` step greps the pytest log for a skip and
  exits 1: everything a test needs is installed there, so a skip means the environment is
  wrong. A test that needs a locale therefore builds it, as
  `test_gcm_shows_spanish_where_it_reads_the_catalog` does, with `localedef --no-archive
  -i es_CL -f UTF-8 -c <folder>/es_CL.UTF-8` and `LOCPATH=<folder>`. Measured, that needs no
  root and takes 0.7 s, and the runner image lists the `locales` package it reads.
- **A new catalog's `.mo` is added with `git add -f`.** `.gitignore` ignores
  `/lang/*/LC_MESSAGES/*.mo`, yet the seven older catalogs' are tracked, and neither CI nor
  `install.sh` compiles one. Left untracked, it gives no translation to anyone who installs
  from git, and `test_every_compiled_catalog_matches_its_source` fails on CI.
- **Test fakes must mirror the real widget API.** `tests/conftest.py` stubs all of `gi`, so a
  fake can define methods the real class lacks and nothing complains — this caused #30
  (`select_none()` on `Vte.Terminal`) and #41 (`set_attention()` on `Gtk.Label`). Several
  tests now assert the real class has each method the fake offers; extend that pattern.
- **Baseline the linters.** The repo carries pre-existing lint and typecheck drift, so
  compare against a `git stash` baseline instead of reading absolute counts. Formatting is
  not drift: the tree is ruff-formatted and `doit check` enforces it, so `doit format`
  should be a no-op on a clean checkout.
- **The glade file is a shared namespace.** Deleting a block can remove widgets referenced
  elsewhere. Sweep every `get_widget("...")` id in the source against the glade. Its
  handlers are connected by name, and vulture skips every `on_*` name, so a handler whose
  signal is lost still looks alive. The glade rebuild in df18e0a lost the server tree's and
  the About dialog's (#257, #261), and moving the menus to actions left ten behind (#256).
  `test_every_on_handler_is_connected` fails on an `on_*` method that nothing connects.
- **Run the app for tracebacks** with `timeout 12 uv run doit sandbox --wait`: a throwaway HOME
  under `tmp/`, with `XDG_CONFIG_HOME` unset, as HOME alone no longer settles which
  configuration directory is read. Never point it at a real one. Give it a scratch `DISPLAY`
  too — a real one puts a GCM window over whatever the developer is doing and steals focus
  for the whole timeout. **`DISPLAY` alone is not enough under WSLg**: GTK prefers Wayland
  whenever `WAYLAND_DISPLAY` is set, so the window opens on the real desktop and the Xvfb
  screen stays black (measured: `xwininfo -root -tree` reported `0 children` for thirty
  seconds). Unset `WAYLAND_DISPLAY` and set `GDK_BACKEND=x11`, as `pytest_configure` does,
  and `GDK_DPI_SCALE` too if you are measuring geometry. `pytest` starts its own Xvfb
  (`tests/conftest.py`); do the same, or `timeout 12 uv run doit sandbox --xvfb --fresh`
  (#509), and use `:0` only for probes that must measure the real compositor.

## Configuration & Data Flow
- User data lives in `~/.config/gcm/`, or in `~/.gcm/` where that was already there --
  `src/gnome_connection_manager/utils/configpaths.py` decides which, and nothing is
  migrated. `gcm.conf` (INI) holds options, window state, shortcuts, and
  serialized `Host` entries (`HostUtils.load_host_from_ini` / `HostUtils.save_host_to_ini`).
  It is read through `configfile.load`, never `cp.read`, and a save starts from it rather
  than from nothing -- see the module entry above.
- `.gcm.key` stores the per-user passphrase used by `pyaes`. `load_encryption_key` and
  `initialise_encyption_key` manage it; respect permissions (0600).
- Configuration defaults live in the `conf` class in `app.py`. Every stored option is
  listed in `CONFIG_OPTIONS`; keep it in step with the defaults and with `writeConfig`,
  which has structural tests enforcing both directions.
- Terminal commands and their default keys live in `SHORTCUT_DEFAULTS`, and
  `TERMINAL_ACTIONS` maps them to application actions. Accelerators are derived
  from the user's config rather than hardcoded — a fixed accelerator shadows the configured
  key, which is what broke #3 and #15. Tests enforce this. A default key moves only for a
  `gcm.conf` with no line for the command: a save writes the key of every command, so one
  GCM has saved keeps the keys it holds, and a changed default never reaches it (#419). So
  the six keys that moved there are not marked `BREAKING CHANGE:`, as its plan decided, and
  the changelog names the lines that take the new keys or keep the old. A command written
  `<command> =` has no key, and a command with no line has its default.
- Host attributes include an `id`, a `folder` (the id `group` is derived from), a
  `position` among that folder's children, group/name/description, connection info, tunnels,
  terminal overrides, clipboard/logging flags, colors, command sequences, commands to run on
  this computer before connecting and after disconnecting, a tab name and a tab colour of
  its own, and SSH options.
  Keep `Host.clone`, `HostUtils.save_host_to_ini`, the `Whost` dialogs, and import/export in
  sync. The dialog rebuilds the record rather than mutating it, so an edit carries the id
  across in `Whost.oldId` -- dropping that would make every edit look like a new host --
  and the position in `Whost.oldPosition`, while the host stays in the same folder.
  The first two now live in `src/gnome_connection_manager/utils/hosts.py` and the dialogs
  in `app.py`, so adding an attribute crosses both files. A setting of one connection
  type's own is not an attribute: it goes in the type's `settings`, and all of those
  carry it already (#228).
- `Whost` shows a type only the tabs it uses, on purpose (#277): `on_cmbType_changed`
  shows the SSH page, `sshGrid`, and Port forwarding, `tunnelGrid`, for a type with
  `ssh_options`, which only SSH has, and the Terminal page, `terminalPage`, where
  `opens_terminal` says the host's tab is a terminal: not a web host's, nor a VNC host's
  that gtk-vnc draws. A type's own page shows as `show_type_page` says. So an SSH host's
  dialog has five tabs and a web host's two. A control on a tab every type is shown goes
  insensitive where the type does not use it, and is never hidden. A hidden page keeps
  what its widgets hold, and OK reads them all, so a host saved before #277 is saved as
  it was, which `tests/test_host_dialog_tabs.py` checks for a host of each type.
  A new host's dialog runs no `on_cmbType_changed` until another type is chosen:
  `GladeComponent` connects the signals after `new()` has chosen ssh. So the glade's
  starting state must be an SSH host's, every page shown and each spin button greyed as
  its box starts unticked. The dialog is as tall as its tallest page, and `new()` gives
  the commands box ten lines of its font: once SSH's rows left Properties it had two at
  a font scale of 2.25, measured.
- Session logs are named from the host entry, never the tab label:
  `<log-path>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`. The naming lives in
  `src/gnome_connection_manager/utils/logpaths.py`. Raw recording adds `.raw` beside
  it plus a `.timing` sidecar, under the same number; the stream alone is not replayable,
  because concatenation discards the write boundaries that separate frames. A tab keeps
  its number, so a reconnect appends to its recording as its text log carries on.
  `vte_run` records on `raw-session-log` alone, not on the host's `log` or on
  `log-local`, and that is decided (#308): a recording needs no text log beside it, and
  Save Transcript reads only the recording. A local console's files go in
  `<log-path>/local/`, as its host is named `local`.
- Spawning changes shape when `osc52-clipboard` or `raw-session-log` is on: the command is
  wrapped so it runs under `relay.py`. With both off the spawn path is byte-for-byte what it
  was, which is the property that keeps the default safe. There are tests asserting it.
- Password handling flows through `encrypt`/`decrypt` (`pyaes`, with a legacy XOR fallback).
  Changes must stay backward compatible by honoring `conf.VERSION`.
- Diagnostic logging goes to stderr via Python's `logging`. `GCM_LOG_LEVEL` (e.g. `DEBUG`) sets
  verbosity; `GCM_TRACE=drag,menu,keys,actions,links,config,notifications` apart from it traces areas (`docs/DEVELOPING.md`).

## UI, Theming & Localization
- Modify UI in `data/ui/gnome-connection-manager.glade` and ensure widget IDs still match the
  handler names (e.g. `on_btnConnect_clicked`). `GladeComponent` normalizes names.
- CSS tweaks go in `data/style.css` (loaded by `Gtk.CssProvider`). Test on GTK 3. The
  cluster window's tick and the attention mark give a tab's label a background and dark
  text, `#2e3436`, Adwaita's own: measured, on Adwaita-dark and Yaru-dark the theme's
  light text could not be read on the yellow (#350). `color` on the box reaches the label
  inside it in all four themes, measured.
- Dragging in the server tree is GtkTreeView's model drag, but GCM refiles the row itself,
  and a refused spot is vetoed by `Gdk.drag_status(context, 0, time)` *and returning True*.
  Notes: `drop_target`'s docstring and the comments of `on_treeServers_drag_motion`.
- A console's tab label is a `NotebookTabLabel`, which holds state its text does not. Read
  its long form through `get_text()` or `get_display_text()`, never `self.label.get_text()`,
  which is cut, and move a console with `Wmain.move_page`. Notes: its docstrings.
- A console action acts on `get_context_tab_widget`'s tab: the one whose menu is open, else
  `page_in_use` (#219, #221). Notes: their docstrings, and those of `current_notebook` and
  `on_context_menu_hide`.
- A tab holds a page, which need not hold a terminal (#223): nothing may take a page's first
  child for its terminal, as `page_terminal` answers. Notes: its docstring, `add_page`'s, and
  `tests/test_tab_pages.py`'s.
- A console can move to a window of its own, a `ConsoleWindow` (#255), so code that reaches
  every console walks `console_notebooks`, not the main window's panes alone. Notes: the
  docstrings of `ConsoleWindow`, `console_notebooks` and `current_notebook`.
- A window GCM opens has a transient parent from `dialog_parent` in `app.py`, bar the six in
  `EXEMPT` in `tests/test_dialog_parents.py`, which holds the rule (#403): under Wayland the
  compositor places a window over its parent. Notes: `docs/design/menus-and-windows.md`.
- Translation sources are the `.po` files directly under `lang/`, one per locale
  (`lang/de_DE.po`); the catalogs the application loads are compiled beside them
  (`lang/de/LC_MESSAGES/gcm-lang.mo`). `doit translate` compiles every source, creating
  the directory it writes into. It uses `msgfmt` where that exists and `tools/build_mo.py`
  otherwise, and fails rather than reporting success when it finds nothing to compile.
  Add a locale by copying an existing `.po` and updating its headers, and add its `.mo` with
  `git add -f` (see Testing). Nothing else names a language: the Makefile's `translate` and
  `doit translate` both compile every `.po` under `lang/`.
- The msgids are English (ADR-0003, #390): a msgid is the text an English reader sees, and a
  locale GCM has no catalog for shows the msgids. Rewording an English message re-keys it:
  change the msgid in the code or the glade file and in every catalog, or its translations
  are lost, and the entry left behind fails `test_no_catalog_keeps_an_entry_nothing_uses`.
- Every message GCM shows is translated in every catalog, and `tests/test_i18n.py` holds each
  to it (#359). A message added to the code or the glade comes with its translation in every
  catalog, keeping its msgid's placeholders by name, underscores, markup, newlines and tabs.
  Each label of a menu in the test's `MENUS` keeps an access key of its own, in every catalog
  and in English (#382). A `msgstr` that is its own msgid passes msgfmt and shows English.
- A Spanish translation follows the catalog's style rules (#391), and tests hold two of them:
  a question opens with `¿`, and a translation that reads as its msgid must be listed in
  `SAME_IN_SPANISH`, with its reason. The rules, and what was measured of glibc, Python's
  `gettext` and GtkBuilder, are in `docs/design/translations.md`.
- Visible strings in Python and glade should be wrapped with `_()` so gettext picks them
  up, and written in English: the text is the msgid.

## Packaging & Release Flow
- `uv run make`, `uv run make deb`, `uv run make rpm` use `fpm`: build translations, stage
  files under `/usr/share/gnome-connection-manager`, and produce artifacts in the repo root.
- No package runs a script (#273): `tests/test_packages.py` fails on one in either recipe,
  and on a package added to a recipe until the README's tables name it, under both names.
- A release is a `vX.Y.Z` tag on `main`, made as `.github/CONTRIBUTING.md` (Release Process)
  describes (#291), with a `CHANGELOG.md` written by hand (#311). A person runs
  `doit release_tag`: `tools/hooks/ai/block-dangerous-commands.py` refuses it from an agent.
- `install.sh` installs the newest release, with the packages its Makefile's `deb` recipe
  names, so a change there reaches installs only with the next release. A package added
  there goes in `PACKAGES` in `tests/test_install.py` too, an optional one in `OPTIONAL`,
  and all but the first of an alternative in `ALTERNATIVES`. Notes: `docs/design/packaging.md`.

## Breaking Changes Policy

GCM is an application, not a library: it is not published to PyPI, and its Python names are
its own to change. What it must not break is what people already have:
- **`gcm.conf` and `.gcm.key`.** A newer GCM reads every file an older one wrote, and every
  password stored in it, honoring `conf.VERSION`. Where the format allows, what it writes
  stays readable by an older GCM, as `commands` beside `commands-json` and
  `collapsed-folders` beside `collapsed-folder-ids` are.
- **What an existing configuration does.** A changed default breaks where it changes what
  a setting or a host already does.
- **The command line**, `gnome-connection-manager` and `gcm`.

A change that breaks one anyway carries a `BREAKING CHANGE:` footer, as
`.github/CONTRIBUTING.md` (Breaking Changes) says, a migration note in its PR, and an entry
in `CHANGELOG.md`, which is written by hand (#311). The `deprecate-api` skill, which retires
a name in a library's API, has nothing to apply to here.

## Coding Conventions & Tips
- This file deliberately names symbols rather than line numbers. The previous version
  pointed at a line number in a root-level module that no longer exists, so the reference
  was wrong twice over. `tests/test_docs.py` checks every path and symbol named here and
  in `docs/design/` against the tree, including bare filenames that have since moved.
- The codebase predates modern idioms: globals, manual signal hookups, custom dialog
  helpers. Match the surrounding style and avoid sweeping refactors unless explicitly
  asked. Matching a neighbor's idiom beats being locally correct.
- **Layout is ruff's, not yours.** The tree is `ruff format`-clean and `doit check`
  enforces it (#115), so run `doit format` rather than hand-aligning. One caveat learned
  when the tree was first formatted: a test that regexes source for `_("...")` must allow
  whitespace inside the parentheses, because the formatter is free to wrap a long call
  across lines. `tests/test_i18n.py` gets this right; copy its pattern.
- Favor the existing helpers (`msgbox`, `inputbox`, `vte_feed`, `HostUtils`, `sanitize_log_name`)
  instead of duplicating behavior — they already handle edge cases across VTE versions.
  `msgbox` draws every message as an error: measured with the Yaru theme, GTK shows a
  message's type as its icon, a no-entry sign for an error. Say that something worked, or
  that there was nothing to do, with `msginfo`, which draws it as information.
- When adding UI controls or config fields, keep these in sync: defaults (`conf`),
  `CONFIG_OPTIONS`, `writeConfig`, glade widgets, the preferences dialog, menus, export/import,
  and translations. `docs/TERMINAL-USAGE.md` names a setting by the label Preferences draws
  for it, and `tests/test_docs.py` fails when the two part, so relabelling a control means
  changing the guide too. A setting Preferences decides for a console belongs in
  `Wmain.apply_preferences_to_terminal`, which `addTab` calls for a new console and
  `apply_settings_to_open_consoles` for each open one, so a change reaches both (#174,
  #181). A test fails if `addTab` sets one itself.
- GCM waits for GTK with `while Gtk.events_pending(): Gtk.main_iteration()` in five
  places, `addTab` among them. A callback that keeps asking to run again keeps
  `events_pending()` true, and every one of those loops with it, so a repeating idle
  must stop once what it waits for can no longer arrive. A Preferences window destroyed
  before `move_to_center` first ran froze the whole application (#175).
- The expect script assumes `/usr/bin/ssh` and `/usr/bin/telnet`; if touching authentication,
  check the regexes and resize trap in `data/scripts/ssh.expect`.

## Contribution Workflow

Issue, branch, commit, PR and merge, each through its doit task rather than `gh`, as
`.github/CONTRIBUTING.md` (Development Workflow) sets out: the tasks validate against the
templates in `.github/`, and `tools/hooks/ai/` refuses the raw commands (#119). The traps:

- **A closing keyword closes its issue wherever it stands in a PR's description, negated
  or not.** `Addresses #N` closes nothing; check a PR with
  `gh pr view <n> --json closingIssuesReferences` before it merges.
- **`ready-to-merge` is a governance label**, applied by a person. An agent may not add it,
  and `require-label` blocks the merge until someone does.
- **`--body-file` for anything long**, written under `tmp/agents/`: a body passed inline is
  scanned as command arguments, so one that names a blocked pattern is refused. The same
  goes for a commit message: `git commit -F`.
- Section headings in an issue body must be `##`; the validator parses on that and reports
  "Missing required sections" for `###`.
- **Approving work on an issue runs `implement-issue`**, and authorizes its commit, push and
  PR on that issue's branch; a question is not approval. **"N is green" or "merge N" runs
  `merge-pr`**: consent to merge that PR and to close the issues it fully addresses, never
  to add `ready-to-merge`. See
  [Slash Commands and Workflows](docs/development/ai/slash-commands.md#merge-pr-n).
- **A security review's findings stay private until fixed.** Fix those that belong to the
  change at hand. Never put an unfixed one in a public issue, PR, comment or commit
  message: file each as a private draft security advisory, and if that is refused, stop and
  ask. `.github/SECURITY.md` sets out the rest, for `src/` and for `tools/`.

### Temporary Files

An agent never writes a temporary file to `/tmp/`: it uses the session scratchpad where the
harness gives one, else `tmp/agents/<agent-type>/`, with the issue or PR number in the file's
name, and deletes it when done. A file left in a worktree's `tmp/` keeps the worktree, as
`doit pr_merge` removes one only while every file git ignores there can be rebuilt (#332).
So a script or log meant to be reused goes in the main checkout's `tmp/agents/<agent-type>/`,
and a body file or commit message written in a worktree is deleted before the merge.

### 4. When Blocked Protocol

A blocked command is blocked for a reason. Find out why, never override it with a flag or a
workaround, then report it and wait for the user.

## Agent Checklist
1. Understand which component you're touching and read its neighbors before editing.
2. Update config, dialogs, menus, translations, and docs together for user-facing options.
3. Add tests, then mutation-test them by reverting the fix.
4. Run `doit test`, `doit lint`, `doit type_check` — compare the last two against a baseline.
5. Launch the app with a throwaway HOME and confirm no tracebacks.
6. Rebuild translations (`doit translate`) if `.po` files change, and say so in your summary.
7. Open the work as an issue and a PR through the doit tasks, not `gh` (see above).
8. State plainly what you did not verify.
