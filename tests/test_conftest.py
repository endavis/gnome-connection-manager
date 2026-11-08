"""What `tests/conftest.py` does to the environment of a run before its first test (#547).

`main()` sets `GCM_DATA_DIR`, `GCM_GLADE_DIR` and `GCM_SCRIPTS_DIR` for the GCM it starts,
and a shell in a GCM tab inherits them. `app.py` takes its data folder from the first when
it is imported, so `doit check` run from a tab tested the checkout's code against the
running GCM's glade file and scripts. `pytest_configure` clears the three.

Nothing here imports the package or takes `app_module`, and it tests no code mutmut mutates,
so it is not among the tests mutmut runs (`tests/test_mutmut_config.py` keeps that list).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# What `main()` sets, with `setdefault`, and a shell in a GCM tab therefore inherits.
DATA_VARIABLES = ("GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR")


def test_the_suite_does_not_inherit_the_data_paths_a_gcm_tab_sets() -> None:
    """With them inherited the suite read the running GCM's `data/`, not the checkout's.

    Run from a GCM tab, `doit check` then failed tests that pass without them. Nothing sets
    them on CI, so this passes there whatever `pytest_configure` does: the next test is the
    one that can fail there.
    """
    inherited = [name for name in DATA_VARIABLES if name in os.environ]

    assert not inherited, f"tests/conftest.py left these set for the run (#547): {inherited}"


def test_a_pytest_started_with_the_data_paths_set_runs_without_them(tmp_path: Path) -> None:
    """The test above, in a pytest of its own that is started with all three set.

    That is what a GCM tab's shell gives the suite and CI never does, so only a run started
    so fails there when the pop is dropped. The path they are set to exists nowhere, so
    nothing reads it by chance. The run goes through the real `tests/conftest.py`. It draws
    no window, so it needs no Xvfb of its own, and `GCM_TEST_REAL_DISPLAY` is the first of
    `pytest_configure`'s returns after mutmut's: a pop moved below any of the others fails
    here too.
    """
    nowhere = str(tmp_path / "no-such-data")
    environment = {
        **os.environ,
        **dict.fromkeys(DATA_VARIABLES, nowhere),
        "GCM_TEST_REAL_DISPLAY": "1",
    }
    test = test_the_suite_does_not_inherit_the_data_paths_a_gcm_tab_sets
    node = f"{Path(__file__).resolve()}::{test.__name__}"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov", node],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "1 passed" in result.stdout, output
