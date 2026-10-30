"""How GCM starts its Python children on the files it is running from (#415).

GCM runs two of its own modules as programs: the relay, which wraps a console while OSC 52
or raw recording is on, and the update check (#369). They ran as `python -m
gnome_connection_manager.<module>`, which finds the package only where a fresh interpreter
can import it. It can in a checkout's `.venv`, which has the package installed, and, as the
Makefile's `install` recipe reads, from the `.deb`, which installs it under `/usr`. It
cannot under `install.sh`: its launcher makes the package importable in GCM's own process
alone, with `sys.path.insert`. There the relay exited with `No module named
'gnome_connection_manager'`, so no console opened with either setting on, and the update
check failed with no word at all.

`module_command` starts a child on the files the running GCM started with instead. The
child puts the folder holding the package first on its `sys.path`, unless it is there
already, and runs the module as `python -m` would. That works wherever GCM's own process
could import the package, and it keeps both children on that version after an update has
moved `current`. It sets no environment variable. `PYTHONPATH` set by the launcher would
reach every program in a tab, and measured, a checkout's `.venv` then imported the
installed copy of GCM in place of its own.

Standard library only: nothing here imports GTK.
"""

from __future__ import annotations

import sys
from pathlib import Path

# What `python -c` runs, given the folder holding the package and the module to run,
# then the module's own arguments. It takes the two out of `sys.argv`, so that the module
# sees the arguments after it and nothing else, as `-m` leaves them.
#
# The folder goes first only if it is not on `sys.path` already: a checkout's `.venv` and
# the `.deb` find the package without it, and keep the order they imported in. `run_module`
# gives the module `-m`'s `__name__`, `__package__` and `sys.argv[0]`, its file. A
# SystemExit carries the module's exit status out, as it does from `-m`.
BOOTSTRAP = """\
import runpy
import sys

root, module = sys.argv[1:3]
del sys.argv[1:3]
if root not in sys.path:
    sys.path.insert(0, root)
runpy.run_module(module, run_name="__main__", alter_sys=True)
"""


def package_root() -> str:
    """The folder that holds the `gnome_connection_manager` package this GCM runs from.

    Not resolved through symlinks. The package was imported from an entry on `sys.path`,
    and the child looks for this folder among its own entries as text. A path with its
    links followed would not be found there, and would be put in front of an entry that
    names the same folder.
    """
    # <root>/gnome_connection_manager/utils/childpython.py
    return str(Path(__file__).absolute().parents[2])


def module_command(module: str) -> list[str]:
    """The command that runs `module` as `python -m module` would, in the interpreter
    running GCM and on the files GCM runs from. The caller adds the module's arguments."""
    return [sys.executable, "-c", BOOTSTRAP, package_root(), module]
