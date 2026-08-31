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

### Changed
- Session-log naming moved out of `app.py` into `utils/logpaths.py`, with the log root
  passed in rather than read from `conf`
- `Host` and `HostUtils` moved out of `app.py` into `utils/hosts.py`; their passphrase
  and legacy-format flag are now arguments rather than defaults read from globals
- Password encryption moved out of `app.py` into `utils/crypto.py`, where it is tested
  directly rather than through the `gi` stub that hid a real fault in it
- Python floor raised from 3.8 to 3.12, matching what was actually being used and tested
- Default branch renamed from `master` to `main`

### Fixed
- The README and the developing guide still told a reader to install and use `just`
- Session logs were written to `logs/session/` rather than the host's own directory
- The encryption key protecting saved host passwords was generated with `random.random()`
- Saving a preference containing a double quote raised `SyntaxError` and silently failed
- Every translation catalog carried duplicate message definitions, which `msgfmt` rejects
- The application reported version 1.2.1 while the package said 1.2.0 and the `.deb` 1.2.2
- Passwords in a config predating the `version` key all decrypted to nothing: the legacy
  XOR helpers raised `TypeError` on Python 3 and swallowed it, and test shims hid it
