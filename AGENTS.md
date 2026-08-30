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
  encryption helpers, and VTE management. It is a single large module by design.
- `src/gnome_connection_manager/main.py` and `src/gnome_connection_manager/__main__.py` –
  entry points (`doit launch` uses these).
- `src/gnome_connection_manager/relay.py` – a PTY relay run as its own process. When OSC 52
  or raw recording is enabled, sessions are spawned *under this* rather than directly, so it
  sits in the byte path between the child and VTE. It forwards bytes unmodified, watches for
  OSC 52, and can tee the stream to disk. VTE keeps its C read path and a stall here cannot
  freeze the interface.
- `src/gnome_connection_manager/utils/urlregex.py` – prebuilt PCRE2-compatible regex strings
  for hyperlink detection inside terminals, including `file:line` locations.
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
- `docs/TERMINAL-USAGE.md` – user-facing: selection when an application has taken the mouse,
  what Copy All copies, pasting, font zoom, session log layout, the shortcut table.
- `docs/DEVELOPING.md`, `docs/PROJECT_STRUCTURE.md` – development setup and layout.
- `docs/SPEC.md` – feature specification. §14 holds a measured analysis of a possible
  Qt/PySide6 port (conclusion: don't, for terminal ergonomics).

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
  0.25–4.0 itself, and a line selection reaches the clipboard as `text\n\n`.
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
  real `~/.gcm`.

## Configuration & Data Flow
- User data lives in `~/.gcm/`: `gcm.conf` (INI) holds options, window state, shortcuts, and
  serialized `Host` entries (`HostUtils.load_host_from_ini` / `HostUtils.save_host_to_ini`).
- `.gcm.key` stores the per-user passphrase used by `pyaes`. `load_encryption_key` and
  `initialise_encyption_key` manage it; respect permissions (0600).
- Configuration defaults live in the `conf` class in `app.py`. Every stored option is
  listed in `CONFIG_OPTIONS`; keep it in step with the defaults and with `writeConfig`,
  which has structural tests enforcing both directions.
- Terminal commands and their default keys live in `SHORTCUT_DEFAULTS`, and
  `TERMINAL_ACTIONS` maps them to application actions. Accelerators are derived
  from the user's config rather than hardcoded — a fixed accelerator shadows the configured
  key, which is what broke #3 and #15. Tests enforce this.
- Host attributes include group/name/description, connection info, tunnels, terminal
  overrides, clipboard/logging flags, colors, command sequences, and SSH options. Keep
  `Host.clone`, `HostUtils.save_host_to_ini`, the `Whost` dialogs, and import/export in sync.
- `Whost` shows a different number of tabs per connection type, on purpose: `on_cmbType_changed`
  hides the Port forwarding page for anything that is not SSH, so a Telnet host's dialog has
  three tabs and an SSH host's has four. It looks like a bug from the outside -- a whole tab
  vanishing -- and it is not. Every other SSH-only control in that branch is made insensitive
  instead, which is the inconsistency behind the confusion, not the hiding itself.
- Session logs are named from the host entry, never the tab label:
  `<log-path>/<group>/<name>/<user>-<YYYYMMDD>-<NNN>.log`. Raw recording adds `.raw` beside
  it plus a `.timing` sidecar; the stream alone is not replayable, because concatenation
  discards the write boundaries that separate frames.
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
  and translations.
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
