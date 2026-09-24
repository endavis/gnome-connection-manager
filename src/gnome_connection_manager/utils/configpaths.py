"""Which directory holds gcm.conf and .gcm.key, and the rule that picks it.

GCM has kept everything in ``~/.gcm`` since the 2020 fork, which predates the XDG base
directory specification. A fresh install now uses ``$XDG_CONFIG_HOME/gcm`` -- ``~/.config/gcm``
unless the variable says otherwise -- and an install that already has ``~/.gcm`` goes on
using it, in place. Nothing is copied or moved: relocating someone's hosts and the key
that decrypts their passwords, unasked, is the one failure this must not have (#192).

The rule is three lines, and their order is the whole of it:

1. ``$XDG_CONFIG_HOME/gcm``, if it is already there,
2. otherwise ``~/.gcm``, if it is already there,
3. otherwise ``$XDG_CONFIG_HOME/gcm``, which the caller creates.

`resolve` creates nothing, which is why creating is `ensure` and a separate call. `app.py`
used to mkdir the directory while the module was being imported; a create that ran ahead of
the choice would satisfy rule 1 on every later start and rule 2 could never be reached
again. Choose, then create -- and `main()` is where the creating belongs anyway, beside
`require_expect` and `require_readable_config`, so importing the module stays free of
side effects (#118).

Pure of GTK and of `conf`: the home directory and the environment are arguments, so the
branches are tested directly rather than through the `gi` stub in tests/conftest.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping

# The pre-XDG directory, straight in $HOME.
LEGACY_DIR_NAME = ".gcm"
# What GCM is called under the XDG configuration home.
XDG_DIR_NAME = "gcm"
# $XDG_CONFIG_HOME's own default, from the specification.
XDG_CONFIG_HOME_DEFAULT = ".config"

# Which of the three rules chose the directory, for the log line and for tests.
FROM_XDG = "xdg"
FROM_LEGACY = "legacy"
FROM_DEFAULT = "new"


class ConfigDir(NamedTuple):
    """The directory GCM will use, and how it came to be that one.

    `legacy` is where the pre-XDG directory would be whether or not it was chosen, so a
    caller can say "and ~/.gcm is where it used to live" without recomputing it.
    """

    path: Path
    source: str
    legacy: Path

    @property
    def exists(self) -> bool:
        """Whether the chosen directory is already there, so `ensure` would create it."""
        return self.source != FROM_DEFAULT


def config_home(home: Path, environ: Mapping[str, str]) -> Path:
    """``$XDG_CONFIG_HOME``, or ``~/.config`` when it does not say.

    The specification requires a value that is unset, empty or relative to be ignored in
    favour of the default -- a relative path would otherwise put the configuration
    somewhere that depends on the working directory GCM happened to be started from.
    """
    value = environ.get("XDG_CONFIG_HOME", "")
    if value and Path(value).is_absolute():
        return Path(value)
    return home / XDG_CONFIG_HOME_DEFAULT


def resolve(home: Path, environ: Mapping[str, str]) -> ConfigDir:
    """Pick the configuration directory. Touches nothing on disk but to look."""
    legacy = home / LEGACY_DIR_NAME
    xdg = config_home(home, environ) / XDG_DIR_NAME
    if xdg.is_dir():
        return ConfigDir(xdg, FROM_XDG, legacy)
    if legacy.is_dir():
        return ConfigDir(legacy, FROM_LEGACY, legacy)
    return ConfigDir(xdg, FROM_DEFAULT, legacy)


def ensure(directory: Path) -> Path:
    """Create the chosen directory, parents and all. Returns it, for chaining.

    Separate from `resolve` on purpose: see the module docstring. `is_dir` rather than
    `exists` throughout, so a stray *file* named ``.gcm`` is not mistaken for the
    directory -- `mkdir` then reports it as what it is.
    """
    directory.mkdir(parents=True, exist_ok=True)
    return directory
