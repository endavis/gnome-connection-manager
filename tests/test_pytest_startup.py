"""pytest has to start beside whatever the system's Python has installed (#252).

GCM's virtualenv is built with --system-site-packages, to reach PyGObject, so every
distribution installed for /usr/bin/python3 is on sys.path too, after the venv's own.
pytest loads each pytest11 plugin any of them registers, and imports it from wherever the
import system finds it first, which is the venv. platformdirs registers its plugin,
platformdirs.pytest_plugin, from 4.12. On CI the venv had platformdirs 4.11.5, which has no
such module, and the runner's Python registered the plugin: pytest stopped with
ModuleNotFoundError before it collected a test. pyproject.toml blocks the plugin by name.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _collect_this_file(site: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """Collect this file in a pytest of its own, with `site` on sys.path.

    No conftest, cache or coverage: plugins load before any of them would matter, and the
    run must leave nothing behind in the checkout.
    """
    paths = [str(site), os.environ.get("PYTHONPATH", "")]
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *options,
            __file__,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in paths if p)},
    )


def test_a_system_platformdirs_plugin_does_not_stop_pytest(tmp_path: Path) -> None:
    """A dist-info on its own is what CI had in effect: pytest reads the registration from
    it, and the import finds the venv's platformdirs. It names a module no platformdirs
    has, so the run without the block fails whatever version the venv holds, which also
    shows the registration is seen at all.
    """
    dist_info = tmp_path / "platformdirs-99.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: platformdirs\nVersion: 99.0\n"
    )
    (dist_info / "entry_points.txt").write_text(
        "[pytest11]\nplatformdirs = platformdirs.not_a_module\n"
    )

    unblocked = _collect_this_file(tmp_path, "-o", "addopts=")
    assert unblocked.returncode != 0
    assert "No module named 'platformdirs.not_a_module'" in unblocked.stderr

    configured = _collect_this_file(tmp_path, "--no-cov")
    assert configured.returncode == 0, configured.stdout[-2000:] + configured.stderr[-2000:]
    assert "test_a_system_platformdirs_plugin_does_not_stop_pytest" in configured.stdout
