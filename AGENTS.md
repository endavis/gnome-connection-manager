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
  freeze the interface. A change of the tab's size reaches it as SIGWINCH, and
  `on_sigwinch` passes the size on itself. Python retries a `select` a signal
  interrupted once the handler has run (PEP 475), so a size left for the loop reached an
  idle program only when a byte next went through, measured (#319). `relay` makes the
  program's pty itself, with `os.openpty`, and sizes it before it forks. `pty.fork` starts
  the program first, and measured under load, a program that read its size at once then
  read 0 by 0 (#339).
  `tests/test_osc52.py` runs the relay on a pty that is its controlling terminal, since
  only then does a resize signal it. `tests/test_relay.py` calls `relay()` in pytest's
  own process instead, with a pty or pipes of the test's in place of `sys.stdin` and
  `sys.stdout`, so that mutmut sees its mutants reached (#337). The relay holds the test's
  thread until its program ends, so what a test does meanwhile, a resize among it, runs
  from a timer's SIGALRM, and the resize is a SIGWINCH the test sends itself.
  `held_up_after_fork` holds the relay up once it has started its program, as load does,
  so that what a test finds the program first sees does not hang on the scheduler.
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
  No folder holds two hosts of one name, so that a folder path and a name always tell
  two hosts apart (#351). The host dialog and a drag refuse one, `copy_name` names
  Duplicate Host's copy, and `HostUtils.ensure_unique_names` renames a later repeat
  `<name> (2)` and so on. `loadConfig` and the import run it once the hosts are filed,
  since `FolderTree.repair` merges two folders of one name with their hosts, and in the
  file's order, which `groups` does not keep. `report_renamed_hosts` says which.
  A host's commands are written as `commands`, each new line as `\n`, which is what an
  older GCM reads, and which reads a backslash and an n back as a new line. Where that
  would change them they are written exactly as well, under `commands-json`, and
  `read_commands` takes that only while `commands` still says the same, so a hand edit
  wins (#243). The name has no dot, since an option with one is a type's setting.
  Measured with the save GCM had before #243, an older GCM drops it and rewrites
  `commands` unchanged. A host's own tab name is `tab-name`, written only when set
  (#349). Measured with v2.1.1, an older GCM reads a file holding it, names the host's
  tabs by name, and leaves it out when it saves, with the host's other options as they
  were, bar the password, which every save encrypts afresh. A host's own tab colour is
  `tab-color`, written only when set and kept as written (#350): v2.1.1 drops it the same
  way, measured. A carriage return goes into `commands` as a new line: gcm.conf is
  read with universal newlines, and one written as it is ended its line, which left the
  file unreadable or set another option, measured. Sending ends a line there anyway,
  since `addTab` splits the commands with `splitlines`.
- `src/gnome_connection_manager/utils/placeholders.py` – a host's values filled into a
  command written for it, `{name}` and the rest (#238). Pure: the caller supplies the
  quoting, `shlex.quote` for a host's commands on this computer, which run through
  `sh -c`, so that a name holding a `;` stays one argument. Anything else in braces is
  left as written. `{folder}` is the last folder of `{group}`, the whole path, and empty
  at the top level (#348). A command host's line (#248) goes through `fill_command`, which makes
  `{password}` the reference `"$GCM_PASSWORD"`, `PASSWORD_VARIABLE`, and never the
  password: measured, `/proc/<pid>/cmdline` is mode 444 and `/proc/<pid>/environ` 400.
  Those commands are the host's `before_command` and `after_command`. `addTab` runs the
  first in the tab's own terminal through `run_before_command`, and
  `on_terminal_child_exited` starts the session with `start_session` only once it exits
  0, from an idle rather than inside the signal. `addTab` builds the connection's command
  before that, so Reconnect has it when the first attempt failed. `session_ended` runs the
  second once per session, for a terminal or a page alike. Measured, Ctrl+Q ends GCM with
  no session's end reported, while closing the window reports each, with status 9, so
  `request_quit` runs `end_sessions` first. A page reports nothing when its tab closes,
  so `open_type_page` listens for its `destroy`.
  Reconnecting a dropped session (#239) asks the type whether it `dropped` or was
  `refused`, from the exit status and the tab's last lines. `child-exited` gives the wait
  status, measured: 65280 for a program that exits 255, 9 for one killed by SIGKILL, so
  `reconnect_if_dropped` converts it first. ssh exits 255 for every failure, `~.`
  included, and only its last line tells a lost connection. telnet exits 0 however its
  session ends, a server that dies included, so Telnet never drops. The countdown lives
  in `count_down_to_reconnect`, and Reconnect cancels it before reconnecting itself.
  `on_terminal_keypress` stops it for a key not in `MODIFIER_KEYS`. Not
  `event.is_modifier`: measured with real input under X11, GDK sets it for no key, Shift
  and Control included, and a test that builds its own events can set it to anything. Close console and the tab's mark wait in `session_over`
  until the attempts run out.
- `src/gnome_connection_manager/utils/snippets.py` – the snippet library (#240): text
  typed into a console on request, found by name, each a `[snippet <id>]` record, which
  `configfile.RECORD_PREFIXES` names so that one deleted stays deleted. Snippets
  replaced custom commands, the `shortcutN`/`commandN` pairs in `[shortcuts]`. `migrate`
  takes each pair once, and a save writes each snippet with a key back as a pair, for an
  older GCM to read, which `migrate` knows by its key. The pairs' encoding turned a
  backslash and an n into a newline, measured, so a snippet's text is a JSON string,
  which also keeps the space a `cd ` ends with. In `app.py` the list is the global
  `snippets`, and a snippet with a key is in `shortcuts` under it too, put there after
  the built-in commands by `bind_snippet_keys`: `on_terminal_keypress` sends it from
  there, and it keeps a key a built-in command also has, as a custom command did.
  `fill_snippet_menus` lists them by name, in folders. A menu built from a model reads
  `_` as a mnemonic, measured, so the menubar's labels go through `menu_label`.
  `send_snippet` fills in the host's values unquoted, and asks for each `{?Label}` once,
  before it types anything. `SnippetPicker` finds one by typing, on the `snippets`
  shortcut, and sends it to the terminal it was opened for. The cluster window's menu is
  `fill_snippet_menus` given a `send`, and sends to every console ticked through
  `send_snippet_to`, which asks for a `{?Label}` once for them all. Preferences edits them on a
  page `Wconfig.build_snippets_page` adds to `nbConfig`, working on copies in
  `Wconfig.library` that `kept_snippets` turns into the library on OK. Its widgets take
  no key until the page has been shown: a test must switch to it first, as GTK drops a
  key sent to a widget not yet realized with a critical, which is why the snippet
  scenarios fail on a GLib critical. And `addTab` gives a new console the keyboard
  twice, the second time from a 200 ms timer: a test that moves the keyboard away after
  opening a tab must wait that out, or the timer takes it back, measured. `focus_again`
  runs that timer, and gives the keyboard back only while the tab is the one in use, so
  moving it to another tab or pane is kept (#264).
- `src/gnome_connection_manager/utils/connections.py` – the connection types (#228): a class
  per kind of host, `Ssh`, `Telnet`, `Rdp`, `Local`, `Web`, `Vnc` and `CustomCommand`, listed in `CONNECTION_TYPES` in the
  order the host dialog offers them, which fills its list from there. Code that used to
  compare `host.type` with a name asks the type instead: `addTab` for the `Command` to
  spawn, and the dialog and `host_sends_commands` for `default_port`, `remote`,
  `ssh_options` and `sends_commands`, the server tree's menu for `sftp`, whether a
  host's files open over SFTP (#267), and `start_session` for `session_program`, whose
  session's start the commands after login wait for (#312). A new type adds a class here, not a branch in each
  of those. `named` finds a type by name, and gives Telnet for a name GCM does not know;
  `for_host` is what `addTab` opens a host as, a local shell for a host with no address
  unless its type has `runs_without_address`, since the Local button's host is of type
  ssh. Both keep what `addTab`
  did before the registry, checked by recording its command for a matrix of hosts before
  and after. Pure: what a command needs from outside comes in as `Programs`, which
  `connection_programs` in `app.py` builds at each spawn, so a test that swaps
  `SSH_COMMAND` for a copy of the script is heard. A type's message, such as the one its
  `missing` gives for RDP, is marked with `N_` and translated in `app.py`, and
  `tests/test_i18n.py` reads this module for it, one literal per message: its pattern
  does not follow a message split across literals.
  A type whose tab is not a terminal has its page in `TYPE_PAGES` in `app.py`, by the
  type's id, since a page is made of widgets. `addTab` opens one with `open_type_page`
  before it asks the type for `missing`, and builds no terminal for it: VTE 0.76 reports
  GLib criticals as a terminal that never joined a window is dropped, which every web
  host did until `addTab` made its terminal last. The registry scenarios fail on a GLib
  critical since, and not on a warning: on CI, GTK warns that it has no accessibility
  bus and no icon theme.
  A type's own settings are the `Setting`s in its `settings`, each a flag, a choice or
  text. A choice has `choices`, each a value and its label, drawn as a combo box, and a
  value it does not offer reads as its default (#278). The
  host dialog draws them on a page titled `settings_title`, which
  `Whost.build_type_pages` places after Port forwarding and `on_cmbType_changed` shows
  only while that type is chosen. A host keeps them in `Host.type_settings`, by the name
  each is saved under in its section, `<type>.<key>`, and only while one differs from
  its default. `HostUtils` reads every option with a dot as one, those of a type GCM
  does not know included, so clone and export and import carry them, and a new type adds
  no attribute to `Host`. A key is lower case: configparser folds an option's name as it
  writes it, and a key in mixed case would not be found once GCM restarted, so `Setting`
  refuses one. `settings_hint` is a line of help under the settings, and `invalid` lets
  a type refuse them on OK. The page packs its rows at the top at their own height:
  measured in a screenshot, a grid given the whole page shared its height out among the
  rows, and the one entry of the first type with settings drew half a page tall.
  That type is `CustomCommand` (#248), a command host, whose `command.line` runs through
  `sh -c` in a terminal tab, with the host's values quoted as `local_command` quotes them.
  It sets `runs_without_address`, so the dialog does not ask for one. Its `{password}`
  reaches the command in `Command.environment`, which `vte_run` hands VTE as `envv`:
  measured, VTE adds it to what the child inherits, directly and under the relay, and it
  never enters GCM's own environment, as TERM does. So `terminal.command` is
  `(program, argv, environment)`, which `start_session` and the Reconnect key in
  `on_terminal_keypress` read, and a stored password reaches `data/scripts/ssh.expect`
  the same way (#314). Nothing is typed at a command host's prompts.
  `tests/test_connections.py` gives a type of its own settings, as
  `tests/test_tab_pages.py` opens a page of its own.
  RDP's settings (#278) are how FreeRDP shows the desktop: Display, Resize with the
  window, on by default, Size and Desktop scale. `rdp_arguments` gives FreeRDP an option
  for each, `/f`, `/f /multimon`, `/dynamic-resolution`, `/size:` in a window only and
  `/scale-desktop:`, before the extra arguments. `rdp_size` and `rdp_scale` hold a value
  to what FreeRDP 3.32.1 takes, measured at each edge: a side from 200 to 32766, a share
  from 1% to 100%, a scale from 100 to 500. FreeRDP refuses `/dynamic-resolution`
  beside smart sizing, exit 22, so `asks_for_smart_sizing` leaves it out for extra
  arguments that ask for that. These were measured against `freerdp-shadow-cli3`,
  unpacked from Ubuntu's packages and serving one Xvfb to a client on another. Its
  desktop keeps its own size, so neither a resize nor the scale could be seen to take.
  Under `/sec:rdp` the client's MCS Connect Initial is not encrypted, and decoded
  through a relay it carried `/scale-desktop:`'s value in its core data as given.
  FreeRDP's own log line for its monitor swaps the desktop and device scales. So does
  the monitor `freerdp_settings_enforce_monitor_exists` builds, which reaches a server
  only in a session with more than one monitor. Its log also names blocks 0xC006 and
  0xC00A `CS_MONITOR` and `CS_MONITOR_EX`, which they are not.
  Under WSL, Preferences' RDP client can choose Windows Remote Desktop, `mstsc.exe`,
  which WSL's interop runs (#283). `Programs` carries the choice as `rdp_client` to
  `Rdp.missing` and `Rdp.command`, which falls back to FreeRDP where `windows_rdp` finds
  no `mstsc.exe`, and Preferences draws the setting only where it does. `mstsc_arguments`
  gives `/v:` and an option for Display and a size in pixels, and never the user, the
  password or the extra arguments: Windows asks for the password itself, as #283 decided
  rather than a file holding it. Options rather than an `.rdp` file, since Windows' April 2026
  security update shows a dialog before every connection opened from a file, with each
  redirection off until ticked. The real `mstsc.exe` opens its windows on the Windows
  desktop, so no test may reach it: `tests/test_windows_rdp.py` runs its scenarios with a
  fake first on a PATH without the folders WSL adds under `/mnt`.
  What the program a host opens in leaves unused is its type's `ignores`, given the
  `Programs`. `on_cmbType_changed` greys it and keeps what it holds, where it clears
  what a type never uses: Windows Remote Desktop ignores an RDP host's user, password,
  extra arguments, Resize and Desktop scale (#285). OK checks a setting so greyed at its
  default, or a value a hand edit left would refuse it with no way to correct it.
  Measured with the real mstsc on a managed desktop (#283): a certificate warning before
  connecting, not a file's dialog; a window that could not be resized by dragging, which
  Smart sizing allows, scaling the image; Remember me gone, under the policy *Do not
  allow passwords to be saved*, `DisablePasswordSaving`; and closing the tab left mstsc
  running. mstsc has no dynamic resolution (#287): of 19 `.rdp` setting names, its
  binary holds 16, not `dynamic resolution`, nor the two Microsoft lists as Windows
  App's alone. A size given applies each time, and mstsc saves the `/w:` and `/h:` into
  its `Default.rdp`, which a connection with no size then opens at. It exits 0 however a
  session ends, a failed connection included, so `Rdp.dropped` and `Rdp.refused` never
  apply to it.
  A web host (#231) opens no tab: its type's `opens_tab` is False, and `addTab` hands
  its `url` to `open_in_browser` in `app.py` and returns. `credentials` and `arguments`
  say whether a remote host's user and password, and its extra arguments, apply; the
  dialog clears and greys them for a web host, as it does all of them for a local one.
  `open_in_browser` runs `xdg-open`, not `Gtk.show_uri`: GIO finds a browser only
  through a MIME cache or a default in `mimeapps.list`, and WSLg had neither. Measured
  there, GIO raised `Operation not supported` where `xdg-open` found the browser from
  its desktop file. A link Ctrl+clicked in a terminal goes through it too (#232), and it
  gives `xdg-open` the scheme in lower case: `xdg-open` looks a handler up by the scheme
  as written, and sent `HTTPS:` and `MAILTO:` to `BROWSER`. It is not waited for, since `xdg-open` with no desktop session runs
  the browser itself and returns only when it closes, and a child watch reports a
  failure once it exits. Its tests give `xdg-open` a browser of their own, through a
  desktop file and through `BROWSER` both: with neither, `xdg-open` falls back to
  `x-www-browser`, which started a real browser when this was measured.
  A VNC host (#234) is drawn in its tab by `VncPage` in `app.py`, with gtk-vnc, whose
  bindings are optional: `TYPE_PAGES` holds it only where `GtkVnc` imports, and without
  it a VNC host runs a viewer in a terminal tab from its type's `command`, the first of
  `VNC_VIEWERS` found. Measured with gtk-vnc 1.3.1 against Xtigervnc 1.13.1, and each a
  scenario in `tests/test_vnc.py`: the credentials asked for come as a
  `GObject.ValueArray`, which PyGObject does not iterate, so `get_nth` over `n_values`;
  a server with no security type gtk-vnc supports is dropped without an error, so an end
  is clean only when GCM closed the connection; the error for a server going away is
  "Server closed the connection" or "Failed to flush data", by what gtk-vnc was doing;
  and destroying the page closes the connection with no signal. GCM's shortcuts are
  accelerators, which run before the focused widget sees a key, and measured with real
  input they took Ctrl+W, closing the tab, and Ctrl+F from the desktop. So
  `Wmain.on_window_key_press` gives a desktop with the keyboard every key first;
  gtk-vnc leaves them once disconnected, and the shortcuts apply again.
  `tests/test_vnc.py` starts Xtigervnc on a display number it picks and retries, since
  `-displayfd` finds none under WSLg, whose `/tmp/.X11-unix` is not writable. What it
  starts dies with the scenario: a leftover held the scenario's output open, and the
  test waited out its timeout. It starts `GcmApplication` as GCM does, `register` then
  `activate`: a bare `Wmain` has no accelerators, and a key test there passes with or
  without the fix.
- `src/gnome_connection_manager/utils/remotefiles.py` – a host's files outside its console
  (#267): the `sftp://` address the server tree's Open in File Manager hands on, and the
  `sshfs` command its Mount with SSHFS runs, at `~/mnt/<name>` from `mount_folder`. Only a
  type with `sftp` offers them, which is `Ssh`. Not `xdg-open`: measured, with nothing
  for `sftp:` it gave the address to `x-www-browser` and exited 0, and no file manager in
  Ubuntu 24.04 declares the scheme. So `open_in_file_manager` in `app.py` asks GIO for the
  default application for `inode/directory`, which GIO finds only through a MIME cache or
  `mimeapps.list`, measured, and else takes the first of `FILE_MANAGERS` on `PATH`.
  sshfs runs as a daemon, its default: measured with sshfs 3.7.3, the mount appears
  before it connects and goes again on a failure, while a daemon exits 0 only once
  connected. A daemon drops ssh's messages and prints `read: Connection reset by peer`
  for every failure, so ssh writes them to a log of its own, `ssh -E` in `ssh_command`,
  which `failure_reason` reads. sshfs splits that command at spaces, and measured, an
  escaped space reached ssh with its backslash, so `ssh_log` picks a folder whose path
  holds none, and there is no log where the runtime folder's path has one. Never a
  fallback in `/tmp`: another user could put a link where the log goes there, and GCM,
  emptying the log for each attempt, would empty the file it names. `read_as_option`
  refuses a user beginning with `-`: measured, sshfs hands ssh a source after `--` as it
  is, so a user `-oProxyCommand=...` would run a command, where a console passes the user
  as `-l`'s value. An address so made comes behind the user, and ssh refuses it. `SSHFS_OPTIONS` bounds the wait for a host that never answers: 15 s,
  measured, where tcp(7) puts the kernel's own at about 127 s. The password reaches ssh in
  `GCM_PASSWORD` through `data/scripts/gcm-askpass`, never in an argument.
  `Wmain.mount_files` starts sshfs with `child_setup=os.setsid`, so the mount outlives
  GCM, and `mount_at` reads `/proc/self/mountinfo` for what is mounted at the folder.
  `remove_mount_folder` removes the folder again after an unmount and after a failed
  mount, so that one is not left for every host ever mounted. `rmdir` alone: measured,
  it refuses a folder still mounted, as busy, and one holding anything, so files that
  were there before the mount stay, folder and all.
  `find_mounts` says where each host is mounted: where its name puts it, or else, for a
  host renamed while mounted, by its `user@host:` in another folder of `~/mnt`, only
  while no other host has the same, as the mount table names no port. `Wmain.find_mounts`
  reads the table for it, `~/mnt` resolved first, since measured, a mount made through a
  link is listed where the link leads, and leaves out a folder still in `mounting`:
  sshfs mounts before it connects, measured. `Wmain.show_mounts` marks each host mounted
  in the tree and `list_mounts` lists every mount under Servers ▸ Mounted, rebuilt only
  when what it lists changed. `watch_mounts` runs it on GIO's `mounts-changed`, so a
  mount made or ended outside GCM shows too. The mark is `MOUNTED_MARK`, a tick before
  the host's name, through `marked_name`: in the tree by `draw_mount_mark`, a data
  function on the name's renderer, and in the Hosts menu on the item `host_items` keeps
  for each host, which `show_mounts` relabels. Text, so that it is drawn at the name's
  size: measured at a font scale of 2.25, the 16 pixel icon that took the host's place
  sat beside a line of text 46 pixels tall, and went unnoticed. Not at the row's end,
  which a name wider than the tree puts out of sight, measured. The list's empty line is
  given Unmount All, disabled then, since GTK draws an item with no action as one to
  choose, measured. Pure: the programs found and the mount table are arguments.
  The server pane is the notebook `nbServers` (#269): the tree's tab, Servers, and a
  Mounted tab that `list_mounts` fills through `fill_mounts_page`, shown only while
  anything is mounted. The Servers tab is always there, and names the pane where the
  tree's header did, which the glade hides: measured, with the header kept and the tabs
  shown only while mounted, the tree's first row dropped from 27 pixels below the pane's
  top to 64 at each mount, where now it stays at 39. The Mounted tab's
  menu, `popupMenuMounts`, acts on the folder `mount_menu_folder` holds, and Open over
  SFTP finds the host there through `mounted_host`, again each time, as Edit Host makes a
  new `Host`. Open Folder hands `open_in_file_manager` a `file://` address, and measured,
  GIO gives the application a folder's path for it. The tabs ellipsize and share the
  strip, and `data/style.css` trims their padding: measured, the theme's left the strip
  136 pixels at its narrowest, and in GCM's default pane of 100 the tree lost its left
  side; now 68, and 96 at a font scale of 2.25. `on_hpMain_button_press_event` shows and
  hides the pane only for a double-click on the divider's own window: measured, one on a
  tab, or below the Mounted tab's rows, reached it too, and hid the pane.
- `src/gnome_connection_manager/utils/folders.py` – the folder tree hosts are filed under
  (ADR-0002): `Folder` records keyed by id in `[folder <id>]` sections, and `FolderTree`,
  which loads, repairs and saves them. `host.group` is kept as a path *derived* from the
  host's folder, so everything that reads the path string is unchanged -- which only holds
  while every folder has a distinct path, the reason `repair` forbids `/` in a name and
  merges same-named siblings. `FolderTree.bind` files each host: its folder id wins when
  it resolves, and otherwise its `group` is resolved, which is the whole migration.
  `app.py` runs it through `sync_folders`, called from `updateTree` and `writeConfig`, so
  the code that edits `groups` by path needed no change. A folder outlives its last host.
  A folder's `tab_color` colours the tabs of the hosts below it (#350), `tab-color` in its
  record only when set, which v2.1.1 reads and drops at its save, measured; `repair`'s
  merge of two folders of one name keeps the colour of the one merged away where the one
  kept has none.
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
  AES in OFB mode over a PBKDF2-stretched key, plus the two legacy formats that must stay
  readable (bare-SHA-256, and repeating-key XOR before that). OFB, not CTR, as these notes
  once said: the two agree on the first block only, so a port written in CTR reads
  passwords shorter than 16 bytes and garbles the rest (#206). Pure — the key file and the
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
- `src/gnome_connection_manager/utils/tabnames.py` – what a host's tab is called (#346).
  `tab_name` gives a host its name, and where another host has the name, in another
  folder, as much of its folder path as tells it apart from each, in front, folder first:
  `infrafoundry/ansible` beside `pyproject-template/ansible`. A host at the top level keeps
  its name. Pure, and judged among the configuration's hosts, not the open tabs', so a tab
  is not renamed as others open and close. `host_tab_name` in `app.py` judges it among
  `groups`, through the host there with the id of the one given: the host dialog builds a
  new record for a host it edits, and a tab keeps the record it was opened for, as
  `NotebookTabLabel.host`. A clone of a tab keeps the id for the same reason, where
  Duplicate Host's copy, a second host, does not. `addTab` and `open_type_page` name a
  tab so. Every change to the hosts redraws the tree, and `updateTree` ends in
  `name_tabs`, which names each tab not renamed by hand again through `set_name`. Then
  `title_windows` titles the windows again, not through `on_tab_focus`, which clears a
  tab's mark, and `name_cluster_consoles` names an open cluster window's rows, since that
  window is not modal. `name_tabs` does nothing while `count`, the tabs open, is 0, as it
  is at class level for a `Wmain` built without `new()`, as tests build one.
  `whole_path` is a host's folders and name, which a tab's tooltip, the open-console list
  and the cluster window show beside its name (#347). `host_path` in `app.py` reads it from
  the host `configured_host` finds, as `host_tab_name` does, and `set_name` gives it to a
  tab renamed by hand too. `NotebookTabLabel.get_path` shows it only where it says more
  than the tab's identity: not for a host at the top level, nor the Local console, nor a
  #346 name that is the whole path already, and always for a renamed tab, which hides its
  host. `with_path` puts it on a second line of a list, smaller and fainter by alpha.
  Measured in a menu built as the open-console list's, a row with it was 43 pixels tall
  against 27, and 85 against 50 at a font scale of 2.25. On the same line it made the
  menu twice as wide, and as a tooltip it showed one row's path, half a second after the
  pointer stopped there. `Wcluster.draw_console` reads it from the row's terminal's tab as
  the row is drawn, so the cluster window's store keeps its columns. A row rewritten by
  `name_cluster_consoles` is drawn again even with the same name, as the store emits
  `row-changed` for it, measured.
  What a tab is named before the folders go in front is Preferences' Tab name,
  `conf.TAB_NAME`, a template of the host's values that `templated` fills, the host's
  name where it gives nothing (#348). The folders go in front of what it gives, so the
  prefix compares template outputs, not names. `namer` fills it once for each host and
  names any number of tabs from that: naming 50 tabs among 1000 hosts took 58 ms with the
  template filled again for every tab and 2 ms with the namer, the best of 5 runs,
  measured. `tab_namer` in `app.py`
  builds one for each `name_tabs`. The Local console keeps `local`, through
  `is_local_console`, since its type reads ssh and it has no address. Preferences' OK
  stores the template and then redraws the tree, which renames the open tabs.
  A host's own tab name, `Host.tab_name` from Tab name on the host dialog's Properties
  tab, names its tabs in place of the template (#349). `own_name` fills it as the
  template is filled, and it is used as it is, with no folders in front. The other hosts
  are compared against what each one's tab shows before any folders, an own name where
  there is one. So a host whose tab would read as another's own name takes its folders,
  and two hosts of one name lose theirs once one is named otherwise. An own name that
  gives nothing counts as none. `tab_namer` reads it from the host `configured_host`
  finds, so the host dialog's OK renames the host's tabs through `updateTree`. The field
  is greyed and cleared for a type that opens no tab, as the command after disconnecting
  is, and OK saves none for one.
- `src/gnome_connection_manager/utils/tabcolors.py` – the colour a host's tabs are marked
  with (#350): `tab_color` gives the host's own, else that of the nearest folder above it
  with one, `folder_color`, else none. `color_of` reads only `#rgb` and `#rrggbb`, so a
  hand edit can put nothing else into the CSS, and a value it cannot read colours nothing
  and is kept as written. `stripe_css` is the CSS of a stripe `STRIPE` pixels tall across
  the top of the tab: an inset `box-shadow`, which takes no room. Not the background,
  which the cluster window's tick and the attention mark colour, and not the bottom, where
  Adwaita and Yaru mark the tab in use, measured with each and its dark variant, Yaru
  from Ubuntu's `yaru-theme-gtk` unpacked into a scratch folder: GTK here names Yaru but
  draws Adwaita, as Yaru is not installed. `NotebookTabLabel.set_color` gives a tab its
  own `Gtk.CssProvider` the first time it has a colour, so a tab never given one is drawn
  as before, and the class `colored`, for which `data/style.css` starts a mark `GAP`
  below the stripe: without the gap, measured, a stripe of the mark's own colour did not
  show on it. `host_tab_color` in `app.py` reads it through `configured_host`, as
  `host_tab_name` does, and `add_page` and `name_tabs` give it to the tabs, so the host
  dialog's OK, a folder's colour and a move reach the open tabs through `updateTree`. A
  folder's colour comes from `color_selected_folder`, the folder's **Tab Color**, through
  `choose_tab_color`, GTK's colour chooser with a No Color button, `NO_COLOR`. The host
  dialog's `chkTabColor` is greyed and unticked for a type that opens no tab, and shows
  the folder's colour while unticked. `tests/test_tabcolors.py` reads the pixels of real
  tabs, drawn into an image rather than read from the screen.
  The server tree and the Hosts menu show the colour as `MARK`, a square, before the name
  (#358). `row_color` in `app.py` gives a host's row `tab_color` and a folder's row
  `folder_color`. `draw_name`, the name renderer's data function, puts `mark_markup` in
  the name's own text, so the square is the name's size and on its line, and hands a row
  without a colour to `draw_mount_mark`, which draws it as before. It is not a cell of its
  own, which moved the name off `get_cells()[1]`, where a test reads it, nor a column of the
  model, which tests slice from column 5. The markup puts the square on a patch of the
  row's own background, the model's column 3. Measured in Adwaita, without it a square of
  the selection's colour could not be seen on the selected row: `#3584e4`, which the host
  dialog's colour button starts with. `label_menu_item` gives a Hosts menu item the
  menu's background in the same way, as Adwaita draws a hovered item `#3584e4` too.
  `colored_items` keeps those items for `on_tvServers_style_updated`. Measured, a change
  of theme emits the tree's `style-updated` once, when the menus already give the new
  background, and emits no hidden menu's own. The real-GTK scenarios read a row's pixels in
  the mark's own box, which Pango measures: on a selected row in Adwaita, the text beside
  it is white, the colour of a patch on a white row.
- `src/gnome_connection_manager/utils/shortcuts.py` – the shortcut decisions that need no
  widget: `parse_custom_keys`, which turns the `[keys]` section into key-name-to-bytes
  and refuses anything already bound, `clamp_font_scale` with the VTE range it mirrors,
  and `captured_key`, what a key pressed in a snippet's key field binds (#240). That one
  asks `MODIFIER_KEY_NAMES` whether a key is a modifier, since GDK's `is_modifier` is
  False for every key under X11, measured with real input (#239).
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
- `src/gnome_connection_manager/utils/afterlogin.py` – when a host's commands after login
  are typed, and what becomes of what is typed into its tab before then (#312). They
  were typed 3 s after the spawn. An SSH host's now go once ssh's own terminal is raw,
  which it is from the session's start, measured with OpenSSH 9.6 no more than 70 ms
  before the remote prompt, and the tab's output has paused for `QUIET`, or after
  `SETTLE` however busy. Under ssh.expect or the relay that terminal is one of theirs,
  so `find_program` finds ssh among the tab's processes, from the pid `note_child_pid`
  keeps as the terminal's `child_pid`, and `terminal_state` reads its modes through
  `/proc/<pid>/fd/0`. Which type is followed so is its `session_program`, `Ssh`'s alone:
  Telnet, a command host and a local shell keep the fixed waits. `Gate.key` decides each
  key typed meanwhile. Held, as a copy of its event, which `replay_keys` gives the
  terminal after the commands, and VTE sends what it would have, measured byte for byte,
  to a tab not in use too. Or passed: while the login asks something, which
  `login_asking` reads as text before the cursor on its row, while ssh reads a secret,
  and for a key with Ctrl. `hold_key` runs last in `on_terminal_keypress`, after the
  shortcuts and `[keys]`, and passes the keys VTE scrolls for, `vte_keeps`, measured to
  send nothing. A paste, a snippet and the cluster window write to the terminal without
  a key event, and are not held: measured, a paste during the login went ahead of the
  commands. `GIVE_UP` sends them anyway for a session that never goes raw, as
  `ssh -T`'s, measured at 20 s, and `FIND_WAIT` where ssh is never found. A remote
  prompt in such a session reads as a question, which restarts `GIVE_UP` for as long as
  it shows. A fake ssh must enter raw mode with `TCSADRAIN`, as ssh does: Python's
  `tty.setraw` defaults to `TCSAFLUSH`, which discards what was typed and not yet read,
  the very thing a test of this is about.
- `src/gnome_connection_manager/utils/updates.py` – whether this repository has released a
  newer GCM (#295). `newer_release` compares the `vX.Y.Z` tags GitHub lists at
  `TAGS_URL` with `app_version` as numbers. The check it replaced asked the original
  author's site, which serves that GCM's 1.2.1, and compared strings, under which 10.0.0
  is less than 9.0.0. Pure. `CheckUpdates` in `app.py` asks on a daemon thread two
  seconds after start, while `check-updates` is on, and says nothing on any failure.
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
  VTE 0.76 does not clear the alternate screen for `?47h`, measured, so a sample taken
  straight after one shows what an earlier session left there. `AltScreenScanner`
  reports a switch with the chunk it ends, and `TranscriptReplayer._plan` feeds a run
  that is only a switch together with the frame after it, so that no such sample is
  taken (#340). `TranscriptReplayer._harvest` reads the primary screen's new rows by the
  cursor's row: at a switch up to it, since output goes on from there once the
  alternate screen is left, into rows that a screen not yet full has empty, and at the
  end to a screen below it (#344). Not by the vertical adjustment: ED 3, which `clear`
  sends, and a reset drop the scrollback even when it is unlimited, measured, and the
  adjustment then counts from 0 again. What they drop is read before they go in (#362):
  `_plan` cuts a primary run before each of `ERASES` with `split_at_erases`, and
  `_harvest_erased` reads up to the cursor for ED 3 and a screen below it for a reset.
  It keeps those rows waiting in `_erased`, and `_keep` adds them with the lines after
  them, less what `unreprinted` finds those print again. Gemini CLI clears and prints its
  screen again on every resize, measured, so keeping all of it put the screen in one
  transcript 17 times. A redraw is told by its first `REPRINT_WORDS` words, and a line
  goes when each of its words is in a run of `RUN_WORDS` that the redraw prints. Words,
  so that a redraw at another width still matches, and anywhere in the redraw, since
  Gemini CLI printed its screen twice after some clears, measured: matched in one
  stretch, its screen was in the transcript 8 times. `ScreenTracker.feed` passes over a
  frame with no text, so the next is compared with the page before it, and `flush` gives
  that page if the screen ends blank (#363). A blank holds none of the text
  `screen_replaced` needs, so a program that blanked its page before leaving the
  alternate screen, as xterm-r6's rmcup does, lost it, and a blank between two pages
  lost the first, measured. A frame with a line or two of text still replaces a page
  without emitting it.
- `tools/build_mo.py` – compiles a `.po` into a `.mo` without gettext. `doit translate` is the
  canonical path; this exists because `msgfmt` is not installed everywhere.
- `tools/packages.py` – what the `.deb` and the `.rpm` declare, read from the Makefile's
  `deb` and `rpm` recipes, the one list of what GCM needs and can use (#273). Given the
  two built packages, it holds what fpm wrote into them to the recipes, as CI's `package`
  job does, and `--names deb` lists every package the `.deb` names, which that job asks
  apt for. `tests/test_packages.py` holds the README's tables and `tests/test_install.py`'s
  lists to the same reading.
- `data/ui/gnome-connection-manager.glade` – GTK Builder UI definition. Keep widget
  names/signals aligned with handler names in `app.py`.
- `data/scripts/ssh.expect` – Expect script wrapping `ssh`/`telnet`, and FreeRDP for an RDP
  host, to feed stored credentials, propagate terminal resize events, and hand control
  back to the VTE widget.
  Its exit status becomes the tab's, which Close console's Only on clean exit decides on,
  so every way out ends at its `exp_wait` and passes on the status of `ssh` or `telnet`.
  An early `exit` reports 0, a clean exit, as the host key failure once did (#210).
  `exp_wait` gives 0 for a program killed by a signal too, so the script reports that as
  a shell does, 128 and the signal's number.
  It runs only hosts with a stored password; the rest run `ssh`, `telnet` or FreeRDP
  directly. `expect_environment` gives it the password as `GCM_PASSWORD`, which it unsets
  before the spawn, measured, so the program does not inherit it (#314). GCM used to type
  it into the tab 2 s after the spawn, and the script started nothing until it came: every
  connection started 2 s late, and a key pressed first became part of the password. Keys
  typed early now wait for the program, and `stty -echo` keeps them off the screen until
  they reach it; without it, measured, they showed twice.
  It turns `log_user` on straight after the `spawn`, so the tab shows everything the
  program prints as it arrives, as a host without a stored password would: the banner,
  the host key question, the prompts. `log_user` is 0 until then only
  so that `spawn` does not echo its command line. While it stayed 0 through the `expect`
  block, only what a pattern's action printed ever showed: a connection that failed left
  an empty tab (#212), a new host key was trusted out of sight (#214), and printing from
  each branch instead loses what follows the match. A `#` line inside the `expect` block
  is read as a pattern, not a comment.
  The host key question is the user's to answer; the script used to answer `yes`, and
  send the password to the server whose key it had trusted (#216). Nothing typed reaches the
  program while the `expect` block waits, only during `interact`, so the question hands
  the terminal over until Enter and then goes back to the block for the password.
  Measured, and each one a test: without `-nobuffer`, `interact` dropped an answer typed
  before it began, all but the Enter; with it, the Enter is passed on, so the action
  must not send another, which ssh would read as an empty password. `interact` also
  returns when the program ends, having closed the spawn id, and an `exp_continue` then
  fails with a Tcl traceback in the tab.
  ssh need not ask for the password at all: it tries keys first, and a server that
  accepts one gets no password prompt (#313). The block waited for ever then, and the
  tab took no input. So ssh's timeout is 1 s, and each timeout reads ssh's own terminal,
  the spawn pty, with `stty -a`. Measured with OpenSSH 9.6, it is canonical with echo
  while connecting and at the host key question, without echo at a passphrase, and raw
  once the session has started. Raw hands over, and so does no echo at two looks
  running, since the password prompt matches first. An echoing question cannot be told
  from connecting. expect's timeout is whole seconds, measured: 0.25 times out at once,
  and output that matches nothing does not restart it. The handover sends the WINCH, as
  after the password, for a change of size before the trap is set. Measured in GCM, the
  trap is set within 60 ms of `addTab`, and a new tab's size changed at about 0.2 s and
  0.4 s. expect gives the program the size its own terminal had when expect started, or
  when `stty` last read it, measured, so the trap reads the size before the spawn too,
  and sets the program's terminal only once there is one: naming `spawn_out(slave,name)`
  before then is a Tcl error, which shows in the tab.
  Telnet's terminal is not read: its 20 s timeout hands over as before.
  An RDP host (#225) names its program as the script's first argument: `rdp_client` in
  `src/gnome_connection_manager/utils/connections.py` picks `xfreerdp3`, else `xfreerdp`,
  and `rdp_arguments` builds the rest. Never
  `/p:`: FreeRDP 3 masks it in its own argv, measured, but not in its parent's, and
  `relay.py` is that parent when raw recording or OSC 52 is on. The rdp branch has an
  `expect` block of its own, so that its `Domain:` pattern never meets an ssh banner. It
  answers FreeRDP 3's `Domain:` with an empty line and hands its `(Y/T/N)` certificate
  question over as the ssh block hands over the host key question. FreeRDP 2 asks for the
  password only, as FreeRDP 3 does given `DOMAIN\user`. The RDP type's `sends_commands`
  is False: a command typed into its tab would answer FreeRDP's certificate question or
  its password prompt. `tests/test_rdp.py` covers GCM's side, with a fake `xfreerdp3` on
  `PATH`.
  `tests/test_ssh_expect.py` runs it on a pty with a fake `ssh`, `telnet` or FreeRDP: its
  `stty` refuses to run without a controlling terminal, and closing the pty before it
  exits kills it. The fakes turn echo off before asking for a password, as `ssh` and
  `login` do; printing the prompt first races the script's answer, and the pty echoes it.
  A test that types Ctrl+C waits for `interact` to put the pty in raw mode: until then the
  terminal turns it into a SIGINT for the script, not the program.
- `data/scripts/gcm-askpass` – ssh's askpass for a mount (#267), under
  `SSH_ASKPASS_REQUIRE=force`. It answers a prompt ending in `assword:` with
  `GCM_PASSWORD` from its environment and refuses every other question: a key's
  passphrase, and the host key question above all, which is the user's to answer in a
  console (#216). Measured, ssh then fails at once with `Host key verification failed.`
  The Makefile installs it executable, and a test checks that of every script there.
- `data/style.css`, `data/icon.png`, `data/ui/donate.gif` – assets.
- `tests/` – the automated suite (see below). `tests/conftest.py` stubs all of `gi`.
- `lang/` – gettext `.po` sources and compiled `.mo` files under
  `<lang>/LC_MESSAGES/gcm-lang.mo`. Locales present: de, en, fr, it, ko, pl, pt, ru.
- `docs/` – see [Documentation](#documentation).
- `gnome-connection-manager.desktop`, `Makefile`, `dodo.py`, `pyproject.toml`.
- `install.sh` – the one-line installer (#294), served from `main` and piped to bash. It
  clones the repository bare into `~/.local/share/gnome-connection-manager/repo`, adds
  each version as a worktree under `versions/`, and moves the link `current` to the one
  in use. An update never changes a version's files, since a running GCM reads its glade
  file for every dialog and runs `data/scripts/ssh.expect` for each tab. The launcher it
  writes, `~/.local/bin/gnome-connection-manager`, resolves `current` once and holds a
  shared `flock` on that version while GCM runs, and drops the `GCM_*_DIR` a GCM started
  from another's tab inherits. An update keeps the version it replaces, as `previous`,
  and removes an older one only if it can lock it exclusively. Measured: `flock(1)`
  creates a file at a path that does not exist, so it is given only folders found; and
  git exits 128 in a folder that is gone, `Unable to read current working directory`, so
  the script works from `/`, as it may remove the one it was run from. The packages come
  from the version's own `Makefile`, the `deb` recipe's `-d` and `--deb-recommends`, and
  git. Its `--deb-suggests` are GCM's optional programs (#302), which `want_optional`
  offers, asking once for all those missing. It asks on `/dev/tty`, since piped, the
  script's input is the script, and with no terminal it asks nothing and installs none.
  On a yes they are installed in an `apt-get install` of their own, after what GCM needs,
  so that apt failing on one leaves GCM installed. Everything runs from a `main` called
  on the last line, in braces: a download cut short just after `main` would run it
  without its arguments. GLib's `get_executable` reads a quoted Exec up to the first
  space, quote included, measured, so the desktop entry quotes the launcher's path only
  where it must.
  `tests/test_install.py` pipes it to bash against a repository of the test's own, with
  `sudo`, `apt-get` and `dpkg-query` faked and `awk` as mawk, which a new Ubuntu has.
  Each scenario runs in a session of its own, with no terminal: measured, run from a
  developer's terminal without that, the script asked its question there. One that
  answers it runs on a pty of its own, which `TAKE_TERMINAL` makes its controlling
  terminal.

- `.claude/`, `.agents/`, `.codex/`, `.copilot/`, `.github/instructions/`,
  `.github/skills/`, `.github/hooks/` – agent configuration, for Claude, Codex, Copilot and
  Antigravity. `.claude/settings.json`, `.agents/hooks.json` and
  `.github/hooks/copilot-hooks.json` register the guard rails in `tools/hooks/ai/`, which
  refuse `gh pr create`/`gh pr merge` in favour of the doit tasks and treat
  `ready-to-merge` as a label only a person may apply. A workflow skill is written once,
  in `.agents/skills/<name>/SKILL.md`, and `doit skills_sync` writes Claude's copy under
  `.claude/skills/`, which is never edited by hand: `tests/template/test_skills_sync.py`
  fails when the two part. "Implement issue N" runs the `implement-issue` skill, which
  replaced the per-agent plan and implement commands (#324). The review and
  adversarial-review commands, and the bridges that hand them to another agent, are in
  `.claude/commands/`, `.github/skills/` and `.agents/skills/`. `.claude/rules/` holds
  narrow footgun rules that apply on top of this file, and `.github/instructions/` and
  `.agents/skills/` carry the same rules for the other agents:
  `tests/template/test_rule_files.py` keeps the three identical. All of it is vendored
  from pyproject-template and replaced on a sync.
- `docs/development/` – how the vendored tooling works: the doit tasks, CI, repository
  settings, and `docs/development/ai/` on the hooks, delegation and slash commands.
  Written for the template, so it describes machinery this project has but does not
  always use — `docs/development/release-and-automation.md` carries a banner saying so.
- `docs/decisions/` – Architecture Decision Records, created with `doit adr`. The template
  numbers its own decisions from 9001; a project's own start at 0001. The 9001 to 9025
  records and the folder's `README.md` are the template's, synced with it (#324), and
  `tests/test_docs.py` treats them as vendored, as it treats `docs/development/` and
  `docs/template/`.

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
- Build/packaging: gettext `msgfmt`, Ruby + `fpm` (for `.deb` and `.rpm`), gzip, binutils
  for the `ar` fpm builds a `.deb` with, and `rpm` for `rpmbuild`. CI's `package` job
  installs them on ubuntu-24.04, fpm 1.18.0 among them, and `desktop-file-validate` for
  the desktop entry.
- Preferred tooling: the doit tasks — `doit launch`, `doit test`, `doit lint`,
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
  mutant of a script there went unseen and survived.
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
- Diagnostic logging goes to stderr via Python's `logging`. Set `GCM_LOG_LEVEL` (e.g. `DEBUG`)
  to adjust verbosity.

## UI, Theming & Localization
- Modify UI in `data/ui/gnome-connection-manager.glade` and ensure widget IDs still match the
  handler names (e.g. `on_btnConnect_clicked`). `GladeComponent` normalizes names.
- CSS tweaks go in `data/style.css` (loaded by `Gtk.CssProvider`). Test on GTK 3. The
  cluster window's tick and the attention mark give a tab's label a background and dark
  text, `#2e3436`, Adwaita's own: measured, on Adwaita-dark and Yaru-dark the theme's
  light text could not be read on the yellow (#350). `color` on the box reaches the label
  inside it in all four themes, measured.
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
  the title the program set, a rename, whether the session has ended, the marks the
  bell and the cluster window leave, and its host's colour (#350). Three texts, and they differ: `get_text()` is the
  identity (the host's tab name, `host_tab_name`, or a rename) that clone, cluster
  consoles and `move_page` read,
  `get_display_text()` is the whole composed label, and the widget draws that cut to
  `TAB_LABEL_MAX` (#190). Everything with room for the long form -- the tooltip, the
  open-console list, the rename and close dialogs -- must take one of the first two, never
  `self.label.get_text()`, which is the cut one. The tooltip and the two lists add the
  host's whole path under it, `get_path` (#347). `render_label` is the single place that
  composes and cuts, so the constructor goes through it too. Move a console between notebooks with
  `Wmain.move_page`, which takes the label along. Split and Unsplit used to build a new
  one from `get_text()`, and every moved tab lost all of that (#180). Dragging a tab
  into another pane is GTK's own notebook drag, not GCM code: measured with real
  pointer input, the drop carries the same label object across, still reorderable and
  detachable, so the tab keeps everything it was showing (#186). GCM's `page-added`
  and `page-removed` handlers do run on a drop, which is what the test there covers.
- A console action acts on the tab in use, or, from a tab's or a terminal's menu, on
  that tab (#219, #221). `get_context_tab_widget` answers which, reading the terminal's
  context too: the terminal menu's Reset and Clone are tab actions. The tab in use is
  `page_in_use`: the page showing in the pane the keyboard is in, or was last in, in the
  window that last had it, which `current_notebook` gives. `on_window_set_focus` keeps
  that pane, following the window's `set-focus` into the panes by a click or a key alike
  (#223). It replaced `self.current`, the last terminal given the keyboard, which a click
  never set and a tab without a terminal could not be. `get_target_terminal` is the
  context terminal, else that tab's terminal, else None. Terminal shortcuts are also
  application accelerators, which run before the focused terminal sees the key, so a key
  reaches the action's handler and not `on_terminal_keypress`. A remote desktop with the
  keyboard is the exception, and gets the key first (#234). Both menus clear their context
  from an idle callback after `hide`, in `on_context_menu_hide`, and
  `trigger_popup_action` clears it even when the action raises. Measured: GTK hides a menu
  before the chosen item's action runs, and that action reads the context. The tab menu
  cleared half of it at once, which sent the next paste or Ctrl+W to a tab nobody was
  looking at. The terminal menu cleared all of it, so each item acted on the terminal with
  the keyboard, which after a split can be in the other pane. Opening the menu does not
  move the keyboard, measured.
- A tab holds a page, and the page need not hold a terminal (#223). `addTab` builds one
  around a terminal and opens it with `add_page`, which a page of any other kind goes
  through too: VNC's is one (#234), and web views and in-tab RDP are to be (#207). Nothing may
  take a page's first child for its terminal; `page_terminal` answers, with None for a
  page that holds something else. Terminal actions then do nothing, and tab actions --
  Rename, Close console, Split, moving between panes and windows, the open-console list --
  work on any tab. `NotebookTabLabel.prepare_menu` offers such a tab Rename, Split and
  Move to New Window only, and the cluster window leaves it out. Measured, choosing a tab
  whose page cannot take the keyboard leaves the keyboard on the notebook itself. Alt+1 to
  Alt+9 are handled in `on_terminal_keypress`, not as accelerators, so they do nothing
  from such a tab. `tests/test_tab_pages.py` opens a kind of page of its own to test all
  of this.
- A console can move to a window of its own, a `ConsoleWindow` (#255). It holds one
  notebook from `new_console_notebook`, as a split does, so tabs drag between it and the
  panes, and no splits: `split_notebook` refuses there, both menus hide Split, and
  `check_notebook_pages` passes its notebook over. Code that reaches every console walks
  `console_notebooks`, the main window's panes and then each console window's;
  `collect_notebooks(self.console_side())` is the main window's alone, which is what
  `on_window_set_focus` and `main_notebook` want. `console_side` is right of the server
  pane, never all of `hpMain`: the server pane is a notebook too (#269), and taken for a
  pane of consoles, the keyboard in its tree made it the pane in use. The window in use, `window_in_use`, is
  the last of them to become active, through `on_window_active_changed`, or the one
  `use_window` brought forward, and `current_notebook` reads it. A console window joins
  the application, so the application's keys work there: measured, without that the
  terminal shortcuts still worked, through `on_terminal_keypress`, but Ctrl+Shift+U did
  not. `toggle_console_window` moves a tab out or back. Back is into `main_notebook`, the
  main window's pane in use, and so is every console of a window being closed, which ends
  none of them, as decided in #255. An emptied console window closes itself, from an idle.
  A tab dropped outside every notebook raises `create-window`: measured with real pointer
  input under X11, a drop on the root window arrives through GTK's root-window drop,
  `drag-data-get` and not `drag-failed`, with the pointer's position, and a drop anywhere
  else but a tab strip, a terminal included, through `drag-failed` with no target. Under
  Wayland, measured on sway, GTK reports either as `drag-failed` with an error and opens
  nothing, so there `on_notebook_drag_failed` moves the tab out itself, the one
  `on_notebook_drag_begin` recorded, once GTK has put it back. `watch_tab_drags` wires
  those signals on every console notebook. Find there opens the window's own search box,
  which `search_box` returns, and F11 makes the console window fill the screen. The bar
  maps its entry only on its next frame, so `focus_search` realizes it: unrealized, each
  key let go of meanwhile was a GTK critical. A mark flags the window holding the tab,
  which `window_of` gives.
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
- No package runs a script (#273). The `.deb`'s `postinst` ran `xdg-desktop-menu`, which
  needs xdg-utils, only suggested, and a menu folder to write to. Measured in Ubuntu
  24.04: without xdg-utils it exited 127, and without `/usr/share/desktop-directories` 3,
  each leaving the package half-configured, and where `/usr/local/share/applications`
  existed it put a copy of the entry there that no package owns. The entry needs none:
  dpkg's desktop-file-utils trigger, and Fedora's file trigger, update the desktop
  database for `/usr/share/applications`. `tests/test_packages.py` fails on a script in
  either recipe.
- The `rpm` recipe names the `.deb`'s packages by Fedora's names, checked in Fedora 43's
  and 44's repositories: `python3-gobject` holds the cairo integration, `freerdp` installs
  FreeRDP 3 as `xfreerdp`, `fuse-sshfs` is sshfs, and `gvfs` holds the sftp backend. fpm
  has no option for an rpm's weak dependencies, so they are `--rpm-tag 'Recommends: …'`
  and `'Suggests: …'`, which rpm 4.18.2 reads back, measured. The `.rpm` has been built
  and read on Ubuntu, never installed on Fedora. Neither package names a VNC viewer, which
  GCM runs only where gtk-vnc, which both install, is missing (#302, #273). A package
  added to a recipe goes in the README's tables, under both names, and
  `tests/test_packages.py` fails until it is.
- A release is a `vX.Y.Z` tag on `main`, made through a `release/vX.Y.Z` PR as
  `.github/CONTRIBUTING.md` (Release Process) describes (#291). `cz bump --files-only`
  writes the version into the four files `tests/test_package.py` keeps equal, which
  `[tool.commitizen]` in `pyproject.toml` names, and the test fails if the two lists part.
  The same section's `update_changelog_on_bump = false` keeps `CHANGELOG.md` hand-written
  (#311). Measured, `true` has `cz bump --files-only` write the changelog too, from commit
  subjects. False is commitizen's default, and the template's `doit release` reads a
  missing key so since pyproject-template#992, so only `tests/test_package.py` would
  notice the key go. Not `doit release`, as yet. Before #324 it wrote no version, and its
  `cz changelog --incremental`, tried on a copy, replaced `CHANGELOG.md`'s hand-written
  `## [Unreleased]` with commit subjects. `--dry-run` showed only the new section, which
  hid that. The version #324 synced is meant to bump a static version with
  `cz bump --files-only` and to keep a hand-written changelog (pyproject-template#992),
  which is GCM's case, but it has not been tried here. `doit release_tag` tags the tip of
  `main`, so run it straight after the release PR merges. A person runs it:
  `tools/hooks/ai/block-dangerous-commands.py` refuses it from an agent.
- `install.sh` installs the newest of those tags, so a release reaches every install the
  next time it runs, and the script itself reaches new installs as soon as it merges. A
  package the `.deb` needs goes in the Makefile's `deb` recipe, which the script reads,
  and in `PACKAGES` in `tests/test_install.py`, which checks what it installs. An
  optional program goes there as `--deb-suggests`, and in `OPTIONAL`. Alternatives are
  one quoted word, `'freerdp3-x11|freerdp2-x11'`, as the script reads the recipe a word
  at a time: it counts any one installed as enough, else installs the first, and the
  others go in `ALTERNATIVES`. Measured with fpm 1.18.0, dpkg 1.22.6 and apt 2.8.3, fpm
  writes one into the control file as given, and dpkg and apt read `a|b` as they read
  `a | b`, which is how `dpkg-deb -f` gives it back. A run following
  `release` reads the recipe of the release it installs, so a change there reaches it
  only with the next release.

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
  That is why `main` has linear history, which branch protection requires. Run from the
  base branch, it then fast-forwards that branch to the merge.
- **`doit worktree --branch=<branch>`** puts a branch in `worktrees/<branch>`, with a
  `.venv` of its own (ADR-9022). The template's task builds that with `uv sync`, which
  leaves out the system's site packages, so `gi` did not import there (#327). GCM's
  `task_worktree` then builds it again, as CI builds GCM's, so the suite runs there as it
  does here. Unset the `GCM_*_DIR` variables there too, as Testing says. `doit pr_merge`
  removes it once merged, but only while everything git ignores there can be rebuilt, as
  the `.venv` and the caches can: any other file keeps it, under `tmp/` too, a body file
  in `tmp/agents/` included. So `.gitignore` ignores `tmp/*` but not the tracked
  `tmp/.gitkeep`, as the template's does, which has git list what is in `tmp/` file by
  file. Under a bare `tmp/` git listed the folder as one entry, and `doit pr_merge` kept
  every worktree with anything in it (#332). For the same reason `audit` exports
  `uv.lock` outside the tree, not into `tmp/`.
- **`--body-file` for anything long.** A body passed inline is scanned as command
  arguments, so a message that merely names a blocked pattern is refused. Write it under
  `tmp/agents/` and pass the path. The same applies to commit messages: `git commit -F`.
- **A closing keyword closes its issue wherever it stands in a PR's description, negated
  or not.** "This does not close #291" in #292's closed #291 at the merge, before the
  release it tracked existed. `Addresses #N` closes nothing; check a PR with
  `gh pr view <n> --json closingIssuesReferences` before it merges.
- **`ready-to-merge` is a governance label**, applied by a person. An agent may not add it,
  and `require-label` blocks the merge until someone does.
- Section headings in an issue body must be `##`; the validator parses on that and reports
  "Missing required sections" for `###`.

See `.github/CONTRIBUTING.md` (Development Workflow) for the full account.

## Agent Checklist
1. Understand which component you're touching and read its neighbors before editing.
2. Update config, dialogs, menus, translations, and docs together for user-facing options.
3. Add tests, then mutation-test them by reverting the fix.
4. Run `doit test`, `doit lint`, `doit type_check` — compare the last two against a baseline.
5. Launch the app with a throwaway HOME and confirm no tracebacks.
6. Rebuild translations (`doit translate`) if `.po` files change, and say so in your summary.
7. Open the work as an issue and a PR through the doit tasks, not `gh` (see above).
8. State plainly what you did not verify.
