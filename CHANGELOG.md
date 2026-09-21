# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at the migration to
[pyproject-template](https://github.com/endavis/pyproject-template); earlier history is in
the git log.

## [Unreleased]

### Added
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

### Changed
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

### Fixed
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
