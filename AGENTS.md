# AGENTS

Notes for future coding agents working on Gnome Connection Manager (GCM).

## Mission & Primary Entry Points
- GCM is a GTK 3 + VTE based SSH/telnet tabbed terminal manager written in Python (`gnome_connection_manager.py`).
- UI layout and signal wiring live in `gnome-connection-manager.glade`; widgets are loaded through `Gtk.Builder` (`GladeComponent` helper inside `app.py`).
- Terminal behavior is customized through `style.css`, `urlregex.py` (link detection patterns), and helpers such as `ssh.expect` and the external `pyAES` library.

## Repository Map
- `gnome_connection_manager.py` – core application logic: configuration (class `conf`), window/controller classes (`Wmain`, `Whost`, `Wconfig`, etc.), `Host`/`HostUtils` models, encryption helpers, and VTE management.
- `gnome-connection-manager.glade` – GTK Builder UI definition. Keep widget names/signals aligned with handler names in `gnome_connection_manager.py`.
- `GladeComponent` (in `gnome_connection_manager/app.py`) – lightweight builder wrapper that loads the glade file, binds translations, and dispatches signal callbacks.
- `pyAES` – PyPI dependency used for AES-256 encryption; installed via the Python package manager.
- `ssh.expect` – Expect script that wraps `/usr/bin/ssh` and `/usr/bin/telnet` to feed stored credentials, propagate terminal resize events, and hand control back to the VTE widget.
- `urlregex.py` – prebuilt PCRE2-compatible regex strings for hyperlink detection inside terminals.
- `lang/` – gettext `.po` sources and compiled `.mo` files under `<lang>/LC_MESSAGES/gcm-lang.mo`.
- `style.css`, `icon.png`, `donate.gif`, `.desktop`, `postinst`, and packaging plumbing (Makefile).

## Dependencies & Environment
- Runtime: Python 3, PyGObject (`python3-gi`), GTK 3, `gir1.2-vte-2.91` (or `python3-gobject` on Fedora), and `expect`. VTE terminals expect a usable `$SHELL` and system `ssh`/`telnet` binaries.
- Build/packaging: gettext `msgfmt`, Ruby + `fpm` (for `.deb` and `.rpm`), gzip, desktop-file utilities (`xdg-desktop-menu` invoked in `postinst`).
- Paths assume a desktop install (`/usr/share/gnome-connection-manager`). When running from the repo use `./gnome_connection_manager.py` so relative paths resolve for assets, CSS, expect scripts, and translations.

## Running & Manual Verification
- Launch locally with `python3 gnome_connection_manager.py` (from repo root) after ensuring `python3-gi`, `Vte`, and `expect` are installed.
- GUI/manual tests: open the app, add/edit hosts, connect via SSH/telnet, split notebooks, test clipboard shortcuts, run cluster commands, and verify preferences persist in `~/.gcm/gcm.conf`.
- Override language as needed via `LANG=en_US.UTF-8 ./gnome_connection_manager.py` (mirrors README instructions).
- When touching terminal behavior confirm `ssh.expect` still runs (`chmod +x` if needed) and that resizing, password prompts, and keyboard shortcuts behave.

## Configuration & Data Flow
- User data lives in `~/.gcm/`:
  - `gcm.conf` (INI) holds options, window state, shortcuts, and serialized `Host` entries (`HostUtils.load_host_from_ini` / `HostUtils.save_host_to_ini`).
  - `.gcm.key` stores the per-user passphrase used by `pyAES`. `load_encryption_key` + `initialise_encyption_key` manage it; respect permissions (0600).
- Configuration defaults reside in the `conf` class (`gnome_connection_manager.py:246`) and must be updated alongside `loadConfig` and `writeConfig` when introducing new settings.
- Host attributes include group/name/description, connection info, tunnels, terminal overrides, clipboard/logging flags, colors, command sequences, and SSH options. Keep `Host.clone`, `HostUtils.save_host_to_ini`, dialogs in `Whost`, and import/export features in sync.
- Password handling flows through `encrypt`/`decrypt` (PyPI `pyAES` with fallback to legacy XOR). Any changes must maintain backward compatibility by honoring `conf.VERSION`.
- Logging goes to stderr via Python's logging module. Set `GCM_LOG_LEVEL` (e.g., `DEBUG`, `INFO`) to adjust verbosity during troubleshooting.

## UI, Theming & Localization
- Modify UI in `gnome-connection-manager.glade` and ensure widget IDs still match the handler names (e.g., `on_btnConnect_clicked`). `GladeComponent` auto-normalizes names, so keep consistent prefixes if you rely on `self.widget_name`.
- CSS tweaks go into `style.css` (loaded by `Gtk.CssProvider`). Test on GTK 3 to verify selectors.
- Translations live in `.po` files; compile MO files with `make translate` (invokes `msgfmt`). Add new locales by copying an existing `.po`, updating headers, and adding a matching directory hierarchy (e.g., `lang/es/LC_MESSAGES/gcm-lang.mo`).
- Visible strings in Python/Glade should be wrapped with `_()` so gettext picks them up.

## Packaging & Release Flow
- `make`, `make deb`, and `make rpm` rely on `fpm` packaging: build translations, stage files under `/usr/share/gnome-connection-manager`, and produce artifacts in the repo root.
- `postinst` registers the desktop entry through `xdg-desktop-menu`; update it if install paths change.
- `Makefile check` / `make style-strip-trailing-whitespace` enforce newline cleanliness; run these before contributing patches meant for release.
- Desktop integration metadata is defined in `gnome-connection-manager.desktop` (Exec path, categories, icon). Update both the desktop file and packaging copy steps together.

## Coding Conventions & Tips
- Codebase predates modern formatting: lots of globals, manual signal hookups, custom dialog helpers, and Python 2 idioms (`xrange`, old-style prints). Match the existing style and avoid sweeping refactors or auto-formatters unless explicitly tasked.
- Favor the provided helpers (`msgbox`, `inputbox`, `vte_feed`, `HostUtils`, etc.) instead of duplicating behavior, since they already handle edge cases (VTE versions, encoding, config compatibility).
- Tests are manual. When changing behavior, document the manual test surface (e.g., “open local console, run cluster command, export hosts”).
- When adding UI controls or config fields, keep these in sync: defaults (`conf`), glade widgets, load/write logic, export/import, command-line interactions, and translations/tooltips.
- Expect script assumes `/usr/bin/{ssh,telnet}`; if touching authentication flows, check the expect regexes (`ssh.expect`) and resize trap.
- Use `rg`/`msgfmt`/`make check` for quick validation; repository intentionally keeps ASCII assets under version control—avoid re-encoding binary files unless needed.

## Agent Checklist
1. Understand which component you're touching (core app, expect script, packaging, translations) and review its neighbor files before editing.
2. Update configs, dialogs, translations, and docs together when introducing user-facing options.
3. Run the app (or at minimum sanity-check `python3 gnome_connection_manager.py --help`) before/after code changes; describe any unverified areas in your final summary.
4. Rebuild translations (`make translate`) if `.po` files change, and mention this in your response.
5. For packaging changes, run the relevant `make` target when possible and summarize the outcome (artifacts, issues).
6. Keep `~/.gcm` backups handy when testing to avoid clobbering user data; include migration notes if you modify file formats.
