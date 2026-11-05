"""A throwaway configuration to run the checkout's GCM against (#506).

`doit sandbox` runs GCM with a HOME under the checkout's `tmp/`, holding a folder of many
hosts and a folder of a few, so a menu, a scroll or a tree can be tried without touching
`~/.config/gcm`. This module is pure and GTK-free; `tools/doit/gcm.py` wraps it.

The file is written with GCM's own writers (`HostUtils.save_host_to_ini`, `FolderTree`), so
it has the shape a current GCM saves (ADR-0002). The hosts point at 127.0.0.1 and are only
there to fill menus: opening one tries ssh.
"""

from __future__ import annotations

import configparser
import math
import shutil
from pathlib import Path

from gnome_connection_manager.utils.folders import FolderTree
from gnome_connection_manager.utils.hosts import ERASE_BINDING_AUTO, Host, HostUtils

REPO = Path(__file__).resolve().parents[1]
# Named so that `doit pr_merge` counts it as rebuildable: its `*_cache` rule (#332).
HOME_NAME = "sandbox_cache"

# What a shell in a GCM tab carries, or the caller sets, that would point GCM at another
# configuration, another checkout's data, or a scale of the caller's.
UNSET = ("XDG_CONFIG_HOME", "GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR", "GDK_SCALE")

# (folder path, host name prefix); the first takes --many hosts, the second --few.
FOLDERS = (("Many hosts", "many"), ("Few hosts", "few"))


def sandbox_home(repo: Path = REPO) -> Path:
    """The HOME GCM runs under: one per checkout, under its ignored `tmp/`."""
    return repo / "tmp" / HOME_NAME


def config_file(home: Path) -> Path:
    return home / ".config" / "gcm" / "gcm.conf"


def write_config(path: Path, many: int, few: int) -> None:
    """Write a gcm.conf of `many` hosts in one folder and `few` in another.

    A count of 0 writes no folder. Update checks are off: a sandbox run would otherwise ask
    GitHub for the tags each time (#316).
    """
    if many < 0 or few < 0:
        raise ValueError("a host count cannot be negative")
    cp = configparser.RawConfigParser()
    cp.add_section("options")
    cp.set("options", "check-updates", "False")
    tree = FolderTree()
    number = 0
    for (group, prefix), count in zip(FOLDERS, (many, few), strict=True):
        if count == 0:
            continue
        folder = tree.ensure_path(group)
        for i in range(1, count + 1):
            number += 1
            host = Host(
                group, f"{prefix}-{i:02d}", "", "127.0.0.1", "test", "", "", "22", "", "ssh", "",
                "0", "", "", "False", "False", "False", "", "", "False",
                ERASE_BINDING_AUTO, ERASE_BINDING_AUTO, "", "False", "", folder,
            )  # fmt: skip
            section = f"host {number}"
            cp.add_section(section)
            HostUtils.save_host_to_ini(cp, section, host, "")
            # save_host_to_ini encrypts even an empty password, and a fresh sandbox has no
            # .gcm.key to decrypt it with: put the empty one back.
            cp.set(section, "pass", "")
    tree.save(cp)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        cp.write(stream)


def prepare(home: Path, *, fresh: bool, many: int, few: int) -> bool:
    """Make `home` hold a configuration. True when it was written, False when kept.

    `fresh` removes `home` first, but only a folder called `sandbox_cache` directly under a
    `tmp` and not a link, so a wrong path cannot take anything else with it.
    """
    if fresh:
        if home.name != HOME_NAME or home.parent.name != "tmp" or home.is_symlink():
            raise ValueError(f"refusing to remove {home}: not a tmp/{HOME_NAME}")
        shutil.rmtree(home, ignore_errors=True)
    if config_file(home).is_file():
        return False
    write_config(config_file(home), many, few)
    return True


def environment(base: dict[str, str], home: Path, scale: str | None) -> dict[str, str]:
    """`base` with HOME set to the sandbox and what points elsewhere removed.

    `scale` becomes GDK_DPI_SCALE, as typed; without it the caller's own is left alone.
    DISPLAY, WAYLAND_DISPLAY and GDK_BACKEND are the caller's.
    """
    env = {key: value for key, value in base.items() if key not in UNSET}
    env["HOME"] = str(home)
    if scale:
        try:
            number = float(scale)
        except ValueError:
            number = math.nan
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"--scale must be a positive number, not {scale!r}")
        env["GDK_DPI_SCALE"] = scale
    return env


def command(repo: Path = REPO) -> list[str]:
    """The checkout's own interpreter, not `uv run`, whose cache would be sought under HOME."""
    return [str(repo / ".venv" / "bin" / "python"), "-m", "gnome_connection_manager"]
