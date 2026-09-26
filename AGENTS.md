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
- `src/gnome_connection_manager/app.py` – configuration (class `conf`), window/controller
  classes (`Wmain`, `Whost`, `Wconfig`, `GcmApplication`), `Host`/`HostUtils` models,
  the encryption key file, and VTE management. Large by design: the window classes are
  wired to the glade file by handler name and share mutable module globals, so splitting
  them relocates the coupling without reducing it. What does come out is pure logic, into
  `utils/` — see #137 to #140 for the seams identified, and the crypto entry below for
  the first one taken.
- `src/gnome_connection_manager/main.py` and `src/gnome_connection_manager/__main__.py` –
  entry points (`doit launch` uses these).
- `src/gnome_connection_manager/relay.py` – a PTY relay run as its own process. When OSC 52
  or raw recording is enabled, sessions are spawned *under this* rather than directly, so it
  sits in the byte path between the child and VTE. It forwards bytes unmodified, watches for
  OSC 52, and can tee the stream to disk. VTE keeps its C read path and a stall here cannot
  freeze the interface.
- `src/gnome_connection_manager/utils/urlregex.py` – prebuilt PCRE2-compatible regex strings
  for hyperlink detection inside terminals, including `file:line` locations.
- `src/gnome_connection_manager/utils/hosts.py` – the `Host` record and `HostUtils`, which
  read and write it to the `configparser` object behind gcm.conf. Pure: the passphrase and
  the pre-v2 `legacy` flag are arguments the caller supplies, not defaults read from
  `get_password()` and `conf.VERSION` as they used to be, and `Vte.EraseBinding.AUTO` is
  held as `ERASE_BINDING_AUTO` with a test asserting it still matches the real enum.
  Every record also carries an `id` from `new_host_id` -- random, not sequential, because
  an imported export brings ids minted elsewhere. `Host` mints one for any record read
  without it, which is the whole migration, and `HostUtils.ensure_unique_ids` repairs a
  repeat afterwards. `clone` deliberately does not carry it: a clone is a second host.
- `src/gnome_connection_manager/utils/folders.py` – the folder tree hosts are filed under
  (ADR-0002): `Folder` records keyed by id in `[folder <id>]` sections, and `FolderTree`,
  which loads, repairs and saves them. `host.group` is kept as a path *derived* from the
  host's folder, so everything that reads the path string is unchanged -- which only holds
  while every folder has a distinct path, the reason `repair` forbids `/` in a name and
  merges same-named siblings. `FolderTree.bind` files each host: its folder id wins when
  it resolves, and otherwise its `group` is resolved, which is the whole migration.
  `app.py` runs it through `sync_folders`, called from `updateTree` and `writeConfig`, so
  the code that edits `groups` by path needed no change. A folder outlives its last host.
  Edits go through `add`, `rename`, `move` and `remove`, which raise `FolderError` rather
  than break a rule; `check_move` asks without moving, since a drag asks on every motion.
  In the tree widget a folder row is one with no host in it (`is_folder_row`), not one
  with children -- an empty folder has none. Collapsed folders are saved by id in
  `collapsed-folder-ids`, beside the positional `collapsed-folders` older builds read
  unguarded: `Gtk.TreePath.new_from_string` raises `TypeError` on an id.
  Order is a `position` on folders and hosts alike, one sequence per folder with
  subfolders and hosts mixed. It is kept only while it differs from name order
  (subfolders, then hosts) -- `number` strips it otherwise, and `sync_folders` runs that
  on every folder -- so a config nobody arranges carries no positions at all.
  `FolderTree.contents` gives each folder's children as drawn; `place` files an item
  beside a sibling, or into a folder: at the end of an arranged one, by name otherwise.
- `src/gnome_connection_manager/utils/configfile.py` – how gcm.conf and an imported export
  are read, by `loadConfig`, the import dialog, and `require_readable_config`, which
  `main()` runs before the window exists (#161). A hand merge of two copies repeats
  sections -- both number their hosts from `[host 1]` -- and strict configparser refuses
  that. `read_config` keeps a repeated host or folder section as a record of its own,
  drops one that is a verbatim copy, and merges a repeated singleton section. A folder id
  that named two records comes back in `ambiguous_folders`, and `refile_ambiguous_hosts`
  files the hosts naming it by their `group` path instead. Anything else it cannot read
  raises `UnreadableError`, and GCM refuses to start rather than start empty. Do not go
  back to `cp.read`: it skips a file it cannot open, so GCM came up with no hosts and
  wrote that over the file when the window closed.
  A save starts from the file too (#163). `carried_config` in `app.py` reads it as it is
  on disk, and `unwritten` strips what the save writes: `WRITTEN_SECTIONS`, and host and
  folder records by `RECORD_PREFIXES`. What is left survives -- `[keys]`, which people
  write by hand, and any section GCM does not know. A section added to `writeConfig`
  belongs in `WRITTEN_SECTIONS`, or the next save finds it already there and fails; a new
  kind of record belongs in `RECORD_PREFIXES`, or a deleted one comes back. A file that
  cannot be read at save time is kept aside under `aside_path`, never written over. And
  never read `gcm.conf.tmp`: it is the save's own output, and one left behind by an
  interrupted save made every later save fail.
  A single value that cannot be read comes back from `read_option` as an `Unread` beside
  the default (#173). `loadConfig` keeps those from `[options]` in `unread_options`,
  `writeConfig` writes their text back through `put_back_unread` while each setting still
  holds that default, and `report_unread_options` lists them once the window is up. Not
  `[window]`: that is GCM's record of its own window, and a save writes the window as it is.
- `src/gnome_connection_manager/utils/configpaths.py` – which directory holds `gcm.conf` and
  `.gcm.key` (#192). `resolve` takes `$XDG_CONFIG_HOME/gcm` if it is there, else `~/.gcm` if
  it is there, else `$XDG_CONFIG_HOME/gcm` for the caller to create; `config_home` supplies
  the `~/.config` default and ignores a value that is empty or relative, as the spec
  requires. Nothing is migrated: relocating someone's hosts and the key that decrypts their
  passwords, unasked, is the failure this must not have. `resolve` creates nothing and
  `ensure` is the only thing that does, which is the whole of it -- a directory created
  before the choice satisfies the rule that looks for it, so an eager `~/.config/gcm` would
  put `~/.gcm` permanently out of reach. `app.py` resolves at import into `CONFIG_DIRECTORY`
  and creates in `require_config_dir`, called from `main()` beside `require_expect` and
  `require_readable_config`. `is_dir`, not `exists`, so a stray *file* named `.gcm` is not
  chosen. Beware when mutation-testing that swap: the two names are the same length, so
  `sed` leaves the file size unchanged and Python can serve a stale `.pyc` within the
  same second.
- `src/gnome_connection_manager/utils/crypto.py` – password encryption for stored hosts:
  AES-CTR over a PBKDF2-stretched key, plus the two legacy formats that must stay readable
  (bare-SHA-256, and repeating-key XOR before that). Pure — the key file and the
  `conf.VERSION` check that selects the legacy path stay in `app.py`, which keeps a thin
  `encrypt` / `decrypt` pair wrapping this. Tested directly rather than through the `gi`
  stub, which is the point: the stub hid the XOR path failing outright on Python 3 (#141).
- `src/gnome_connection_manager/utils/logpaths.py` – naming and layout for session logs:
  `<log_dir>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`, plus the containment check that
  keeps a free-text group from escaping the log root. Two sanitizers on purpose —
  `sanitize_log_name` guards a filesystem path, `sanitize_tab_title` guards a widget that
  ends at `set_markup`. `truncate_tab_label` is a third thing again: it cuts the whole
  composed label at `TAB_LABEL_MAX = 30` so one tab does not push its neighbours behind the
  notebook's scroll arrows, which `sanitize_tab_title`'s per-title 40 cannot do -- the host
  name and a rename are part of the label too (#190). A cut, not a Pango ellipsis: measured,
  an ellipsized label reports the ellipsis as its minimum width and the tab collapses to
  34px, and `set_width_chars` as a floor then pads a `Local` tab out from 66px to 223px.
  Pure of GTK and of configuration: the log root is an argument, and
  `app.py` keeps a `session_file_for` wrapper that supplies `conf.LOG_PATH` and keeps the
  number it chose on the terminal as `session_stem`. A session's `.log`, `.raw` and
  `.timing` are opened at different times -- the recording again on every reconnect --
  and when each chose its own number, `002.log` sat beside `001.raw` (#200). A number is
  free only while none of `SESSION_SUFFIXES` uses it, and choosing one creates the file
  asked for, empty and exclusively: the relay creates a recording about 35 ms after the
  spawn, and until then a second tab for the host took the same number (#202). The claim
  is then checked against the number's other files and backed out of if one appeared:
  the exclusive create settles two GCM instances claiming the same file, not one
  claiming the `.log` while another claims the `.raw` (#204). So an empty `.log` is a
  session's own reservation, not an earlier log to append to -- `set_terminal_logger`
  reads its size, not whether it exists.
- `src/gnome_connection_manager/utils/shortcuts.py` – the two shortcut decisions that need
  no widget: `parse_custom_keys`, which turns the `[keys]` section into key-name-to-bytes
  and refuses anything already bound, and `clamp_font_scale` with the VTE range it mirrors.
  Pure — the reserved set is an argument, and `RESERVED_ACCELERATORS` stays in `app.py`
  beside the `do_startup` registrations a test checks it against. `shortcut_to_accel`,
  `apply_menu_accels` and `sync_shortcut_accels` stay too: measurement showed they are
  `Gdk`/`Gtk` calls rather than logic, which is what put the seam here (#140).
- `src/gnome_connection_manager/utils/activity.py` – when a console busy out of sight has
  gone quiet (#208). An agent CLI finishing in a tab nobody watches gave no sign: measured
  in a real VTE, only codex of Claude Code, codex, agy and Copilot CLI rings the bell at
  the end of a turn. All four redraw continuously while they work, with the longest pause
  at 1.35 s, and not at all while idle. `QuietWatch` turns `contents-changed` into that
  decision. Output only counts while the tab is out of sight, and must run for
  `QUIET_MIN_BUSY`, so typing a command and switching away is not work finishing. Pure:
  the time is an argument. `Wmain.on_terminal_contents_changed` feeds it, and `check_quiet`
  polls it on a timer that exists only while a tab is waiting, so an idle console costs
  nothing. It, the bell and a session ending all mark through `request_attention`.
- `src/gnome_connection_manager/utils/osc52.py` – extraction of OSC 52 clipboard writes from
  a byte stream. Pure and stateless apart from a partial-sequence buffer, so it is testable
  without a terminal, a display or a pty.
- `src/gnome_connection_manager/utils/vtehtml.py` – parses VTE's HTML grid export into styled
  runs for the buffer viewer.
- `src/gnome_connection_manager/utils/transcript.py` – rebuilds a readable transcript from a
  raw recording: restores the write boundaries from the `.timing` sidecar, coalesces each
  burst of writes back into the frame it drew, tracks which screen the stream is on, and
  decides what a new alternate-screen frame actually added. Pure, so the heuristics are
  testable without a display; the emulator driving it is `TranscriptReplayer` in `app.py`.
- `tools/build_mo.py` – compiles a `.po` into a `.mo` without gettext. `doit translate` is the
  canonical path; this exists because `msgfmt` is not installed everywhere.
- `data/ui/gnome-connection-manager.glade` – GTK Builder UI definition. Keep widget
  names/signals aligned with handler names in `app.py`.
- `data/scripts/ssh.expect` – Expect script wrapping `ssh`/`telnet` to feed stored
  credentials, propagate terminal resize events, and hand control back to the VTE widget.
- `data/style.css`, `data/icon.png`, `data/ui/donate.gif` – assets.
- `tests/` – the automated suite (see below). `tests/conftest.py` stubs all of `gi`.
- `lang/` – gettext `.po` sources and compiled `.mo` files under
  `<lang>/LC_MESSAGES/gcm-lang.mo`. Locales present: de, en, fr, it, ko, pl, pt, ru.
- `docs/` – see [Documentation](#documentation).
- `gnome-connection-manager.desktop`, `postinst`, `Makefile`, `dodo.py`, `pyproject.toml`.

- `.claude/`, `.agents/`, `.codex/`, `.copilot/`, `.github/instructions/` – agent
  configuration. `.claude/settings.json`
  and `.agents/hooks.json` register the guard rails in `tools/hooks/ai/`, which refuse
  `gh pr create`/`gh pr merge` in favour of the doit tasks and treat `ready-to-merge` as a
  label only a person may apply. `.claude/commands/` and `.agents/skills/` hold the slash
  commands and delegation skills; `.claude/rules/` holds narrow footgun rules that apply on
  top of this file, and `.github/instructions/` carries the same rules in the form
  Copilot reads — change one and change the other. All of it is vendored from pyproject-template and replaced on a sync.
- `docs/development/` – how the vendored tooling works: the doit tasks, CI, repository
  settings, and `docs/development/ai/` on the hooks, delegation and slash commands.
  Written for the template, so it describes machinery this project has but does not
  always use — `docs/development/release-and-automation.md` carries a banner saying so.
- `docs/decisions/` – Architecture Decision Records, created with `doit adr`. The template
  numbers its own decisions from 9001; a project's own start at 0001.

## Documentation
- `docs/TERMINAL-USAGE.md` – user-facing, everything inside a tab: selection and what a
  word is, copy when nothing is selected, pasting, session logs and raw recording, OSC 52,
  the buffer viewer, tab titles, the bell, font zoom, the shortcut table, and what GCM does
  with a `gcm.conf` it cannot read.
- `docs/HOSTS-AND-FOLDERS.md` – user-facing, everything in the server tree: making,
  renaming and deleting folders, what a drop does where, the order a folder keeps, host
  ids, and export/import. Written because the only account of folders was `docs/SPEC.md`,
  which specifies a Qt port that is not being built (#193).
- Every setting Preferences draws a control for must be named in one of those two, by its
  `gcm.conf` key or by its label. `tests/test_docs.py` enforces both directions now:
  guide to code, and code to guide against `UNDOCUMENTED_SETTINGS`, whose entries each
  carry a reason. Four settings had shipped with a control and no mention anywhere before
  the second direction existed.
- `docs/DEVELOPING.md`, `docs/PROJECT_STRUCTURE.md` – development setup and layout.
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
- Build/packaging: gettext `msgfmt`, Ruby + `fpm` (for `.deb` and `.rpm`), gzip,
  desktop-file utilities (`xdg-desktop-menu`, invoked in `postinst`).
- Preferred tooling: the doit tasks — `doit launch`, `doit test`, `doit lint`,
  `doit type_check`, `doit translate`. `doit list` shows them all. Project-specific
  tasks live in `tools/doit/gcm.py`; the rest of `tools/doit/` is vendored from
  pyproject-template and is replaced wholesale on a sync. For anything without a task,
  use `uv run …` so the repo's environment is honored.

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
  several tests that passed against broken code.
- **Verify what is rendered, not what the model says.** A menubar was once "verified" by
  walking its `Gio.Menu` when it had never been rendered at all (#43). Walk the widget tree.
- **Test fakes must mirror the real widget API.** `tests/conftest.py` stubs all of `gi`, so a
  fake can define methods the real class lacks and nothing complains — this caused #30
  (`select_none()` on `Vte.Terminal`) and #41 (`set_attention()` on `Gtk.Label`). Several
  tests now assert the real class has each method the fake offers; extend that pattern.
- **Baseline the linters.** The repo carries pre-existing lint and typecheck drift, so
  compare against a `git stash` baseline instead of reading absolute counts. Formatting is
  not drift: the tree is ruff-formatted and `doit check` enforces it, so `doit format`
  should be a no-op on a clean checkout.
- **The glade file is a shared namespace.** Deleting a block can remove widgets referenced
  elsewhere. Sweep every `get_widget("...")` id in the source against the glade.
- **Run the app for tracebacks** with a throwaway HOME:
  `HOME=<tmpdir> timeout 12 uv run python -m gnome_connection_manager`. Never point it at a
  real configuration directory -- and note that HOME alone no longer settles which one
  that is, so unset `XDG_CONFIG_HOME` along with it. Give it a scratch `DISPLAY` too — a
  real one puts a GCM window over whatever the developer is doing and steals focus for the
  whole timeout. **`DISPLAY` alone is not enough under WSLg**: GTK prefers Wayland whenever
  `WAYLAND_DISPLAY` is set, so the window opens on the real desktop and the Xvfb screen
  stays black. Measured while taking the README screenshot -- `xwininfo -root -tree` on the
  scratch display reported `0 children` for thirty seconds. Unset `WAYLAND_DISPLAY` and set
  `GDK_BACKEND=x11`, which is what `pytest_configure` does for the same reason, and unset
  `GDK_SCALE`/`GDK_DPI_SCALE` with them if you are measuring geometry. `pytest` already
  starts its own Xvfb (`pytest_configure` in
  `tests/conftest.py`); do the same here rather than reusing `:0`, which is only for
  probes that must measure the real compositor.

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
  key, which is what broke #3 and #15. Tests enforce this.
- Host attributes include an `id`, a `folder` (the id `group` is derived from), a
  `position` among that folder's children, group/name/description, connection info, tunnels,
  terminal overrides, clipboard/logging flags, colors, command sequences, and SSH options.
  Keep `Host.clone`, `HostUtils.save_host_to_ini`, the `Whost` dialogs, and import/export in
  sync. The dialog rebuilds the record rather than mutating it, so an edit carries the id
  across in `Whost.oldId` -- dropping that would make every edit look like a new host --
  and the position in `Whost.oldPosition`, while the host stays in the same folder.
  The first two now live in `src/gnome_connection_manager/utils/hosts.py` and the dialogs
  in `app.py`, so adding an attribute crosses both files.
- `Whost` shows a different number of tabs per connection type, on purpose: `on_cmbType_changed`
  hides the Port forwarding page for anything that is not SSH, so a Telnet host's dialog has
  three tabs and an SSH host's has four. It looks like a bug from the outside -- a whole tab
  vanishing -- and it is not. Every other SSH-only control in that branch is made insensitive
  instead, which is the inconsistency behind the confusion, not the hiding itself.
- Session logs are named from the host entry, never the tab label:
  `<log-path>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`. The naming lives in
  `src/gnome_connection_manager/utils/logpaths.py`. Raw recording adds `.raw` beside
  it plus a `.timing` sidecar, under the same number; the stream alone is not replayable,
  because concatenation discards the write boundaries that separate frames. A tab keeps
  its number, so a reconnect appends to its recording as its text log carries on.
- Spawning changes shape when `osc52-clipboard` or `raw-session-log` is on: the command is
  wrapped so it runs under `relay.py`. With both off the spawn path is byte-for-byte what it
  was, which is the property that keeps the default safe. There are tests asserting it.
- Password handling flows through `encrypt`/`decrypt` (`pyaes`, with a legacy XOR fallback).
  Changes must stay backward compatible by honoring `conf.VERSION`.
- Diagnostic logging goes to stderr via Python's `logging`. Set `GCM_LOG_LEVEL` (e.g. `DEBUG`)
  to adjust verbosity.

## UI, Theming & Localization
- Modify UI in `data/ui/gnome-connection-manager.glade` and ensure widget IDs still match the
  handler names (e.g. `on_btnConnect_clicked`). `GladeComponent` normalizes names.
- CSS tweaks go in `data/style.css` (loaded by `Gtk.CssProvider`). Test on GTK 3.
- Dragging in the server tree is GtkTreeView's model drag with a target of GCM's own,
  `GCM_TREE_ROW`: GTK highlights the row under the pointer and opens a folder hovered
  over, but never moves a row itself -- `on_treeServers_drag_data_received` refiles the
  record and redraws. A refused spot is vetoed in `on_treeServers_drag_motion` by
  `Gdk.drag_status(context, 0, time)` *and returning True*. Measured with real pointer
  input under Xvfb: return False instead and the refused drop is delivered anyway.
  The dragged row is the one under the press (`_drag_source_path`), not the selection:
  measured the same way, a press on a folder's expander arrow starts a drag without
  selecting the folder. `drop_target` reads the edge of a row as a place beside it and
  the middle as that row's folder.
- A console's tab label is a `NotebookTabLabel`, and it holds state its text does not:
  the title the program set, a rename, whether the session has ended, and the marks the
  bell and the cluster window leave. Three texts, and they differ: `get_text()` is the
  identity (host name or rename) that clone, cluster consoles and `move_page` read,
  `get_display_text()` is the whole composed label, and the widget draws that cut to
  `TAB_LABEL_MAX` (#190). Everything with room for the long form -- the tooltip, the
  open-console list, the rename and close dialogs -- must take one of the first two, never
  `self.label.get_text()`, which is the cut one. `render_label` is the single place that
  composes and cuts, so the constructor goes through it too. Move a console between notebooks with
  `Wmain.move_page`, which takes the label along. Split and Unsplit used to build a new
  one from `get_text()`, and every moved tab lost all of that (#180). Dragging a tab
  into another pane is GTK's own notebook drag, not GCM code: measured with real
  pointer input, the drop carries the same label object across, still reorderable and
  detachable, so the tab keeps everything it was showing (#186). GCM's `page-added`
  and `page-removed` handlers do run on a drop, which is what the test there covers.
- Translation sources are the `.po` files directly under `lang/`, one per locale
  (`lang/en_US.po`); the catalogs the application loads are compiled beside them
  (`lang/en/LC_MESSAGES/gcm-lang.mo`). `doit translate` compiles every source, creating
  the directory it writes into. It uses `msgfmt` where that exists and `tools/build_mo.py`
  otherwise, and fails rather than reporting success when it finds nothing to compile.
  Add a locale by copying an existing `.po` and updating its headers; the Makefile still
  names each language, so add it there too.
- Visible strings in Python and glade should be wrapped with `_()` so gettext picks them up.

## Packaging & Release Flow
- `uv run make`, `uv run make deb`, `uv run make rpm` use `fpm`: build translations, stage
  files under `/usr/share/gnome-connection-manager`, and produce artifacts in the repo root.
- `postinst` registers the desktop entry through `xdg-desktop-menu`; update it if install
  paths change, along with `gnome-connection-manager.desktop`.
- `make check` and `make style-strip-trailing-whitespace` enforce newline cleanliness.

## Coding Conventions & Tips
- This file deliberately names symbols rather than line numbers. The previous version
  pointed at a line number in a root-level module that no longer exists, so the reference
  was wrong twice over. `tests/test_docs.py` checks every path and symbol named here
  against the tree, including bare filenames that have since moved.
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

Issue first, then a branch for it, then a PR. Use the doit tasks rather than `gh` directly:
they validate against the templates in `.github/`, and `tools/hooks/ai/` refuses the raw
commands once wired (#119).

| Step | Command |
|---|---|
| File the issue | `doit issue --type=<bug\|feature\|docs\|refactor\|chore> --title=... --body-file=...` |
| Branch from `origin/main` | `<type>/<issue-number>-<slug>`, e.g. `fix/111-session-log-host-ordering` |
| Open the PR | `doit pr` |
| Merge | `doit pr_merge` |

- **`feat/`, not `feature/`.** A pre-commit hook rejects a malformed branch name, and
  another rejects a commit citing an issue that is not the branch's own.
- **`doit pr_merge` squashes**, producing `<type>: <subject> (merges PR #XX, addresses #YY)`.
  That is why `main` has linear history, which branch protection requires.
- **`--body-file` for anything long.** A body passed inline is scanned as command
  arguments, so a message that merely names a blocked pattern is refused. Write it under
  `tmp/agents/` and pass the path. The same applies to commit messages: `git commit -F`.
- **`ready-to-merge` is a governance label**, applied by a person. An agent may not add it,
  and `require-label` blocks the merge until someone does.
- Section headings in an issue body must be `##`; the validator parses on that and reports
  "Missing required sections" for `###`.

See `.github/CONTRIBUTING.md` for the full account.

## Agent Checklist
1. Understand which component you're touching and read its neighbors before editing.
2. Update config, dialogs, menus, translations, and docs together for user-facing options.
3. Add tests, then mutation-test them by reverting the fix.
4. Run `doit test`, `doit lint`, `doit type_check` — compare the last two against a baseline.
5. Launch the app with a throwaway HOME and confirm no tracebacks.
6. Rebuild translations (`doit translate`) if `.po` files change, and say so in your summary.
7. Open the work as an issue and a PR through the doit tasks, not `gh` (see above).
8. State plainly what you did not verify.
