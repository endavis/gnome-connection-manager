"""A throwaway configuration to run the checkout's GCM against (#506).

`doit sandbox` runs GCM with a HOME under the checkout's `tmp/`, holding a folder of many
hosts and a folder of a few, so a menu, a scroll or a tree can be tried without touching
`~/.config/gcm`. This module is pure and GTK-free; `tools/doit/gcm.py` wraps it.

The file is written with GCM's own writers (`HostUtils.save_host_to_ini`, `FolderTree`), so
it has the shape a current GCM saves (ADR-0002). The remote hosts have `<name>.invalid` for
an address (RFC 6761), so one never reaches a machine, and the environment drops the ssh
agent: they are only there to fill menus. The `--local` hosts have no address and open a
local shell.
"""

from __future__ import annotations

import configparser
import math
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from gnome_connection_manager.utils.folders import FolderTree
from gnome_connection_manager.utils.hosts import ERASE_BINDING_AUTO, Host, HostUtils
from gnome_connection_manager.utils.remotefiles import mounted_folders

if TYPE_CHECKING:
    from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
# Named so that `doit pr_merge` counts it as rebuildable: its `*_cache` rule (#332).
HOME_NAME = "sandbox_cache"

# What a shell in a GCM tab carries, or the caller sets, that would point GCM at another
# configuration, another checkout's data, or a scale of the caller's.
UNSET = ("XDG_CONFIG_HOME", "GCM_DATA_DIR", "GCM_GLADE_DIR", "GCM_SCRIPTS_DIR", "GDK_SCALE")

# What would let a host of the sandbox reach the developer's own machines.
AGENT = ("SSH_AUTH_SOCK", "SSH_AGENT_PID")

# (folder path, host name prefix); the first takes --many hosts, the second --few.
FOLDERS = (("Many hosts", "many"), ("Few hosts", "few"))

LOCAL_FOLDER = "Local hosts"
LOCAL_NAMES = (
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
)

# The window title, so the sandbox's GCM is not taken for the developer's own.
APP_TITLE = "GCM sandbox"


def local_name(index: int) -> str:
    """The name of the `index`th local host (from 0): `alpha`, then on to `alpha-2`."""
    word = LOCAL_NAMES[index % len(LOCAL_NAMES)]
    round_ = index // len(LOCAL_NAMES)
    return word if round_ == 0 else f"{word}-{round_ + 1}"


def sandbox_home(repo: Path = REPO) -> Path:
    """The HOME GCM runs under: one per checkout, under its ignored `tmp/`."""
    return repo / "tmp" / HOME_NAME


def config_file(home: Path) -> Path:
    return home / ".config" / "gcm" / "gcm.conf"


def write_config(path: Path, many: int, few: int, local: int = 0) -> None:
    """Write a gcm.conf of `many` hosts in one folder, `few` in another and `local` more.

    A count of 0 writes no folder. Update checks are off: a sandbox run would otherwise ask
    GitHub for the tags each time (#316).
    """
    if many < 0 or few < 0 or local < 0:
        raise ValueError("a host count cannot be negative")
    cp = configparser.RawConfigParser()
    cp.add_section("options")
    cp.set("options", "check-updates", "False")
    cp.set("options", "app-title", APP_TITLE)
    cp.set("options", "update-title", "True")
    tree = FolderTree()
    number = 0
    folders = [*FOLDERS, (LOCAL_FOLDER, "")]
    for (group, prefix), count in zip(folders, (many, few, local), strict=True):
        if count == 0:
            continue
        folder = tree.ensure_path(group)
        for i in range(1, count + 1):
            number += 1
            name = local_name(i - 1) if not prefix else f"{prefix}-{i:02d}"
            address = f"{name}.invalid" if prefix else ""
            host = Host(
                group, name, "", address, "test", "", "", "22", "", "ssh", "",
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


def mounts_below(home: Path, mountinfo: str) -> list[Path]:
    """The mounts at `home` or below it, from the text of /proc/self/mountinfo.

    A sibling that shares a prefix, as `sandbox_cache2`, and a parent are not below it.
    """
    roots = {str(home), str(home.resolve())}
    found = []
    for mounted in mounted_folders(mountinfo):
        if any(mounted == root or mounted.startswith(root.rstrip("/") + "/") for root in roots):
            found.append(Path(mounted))
    return found


def log_file(home: Path, now: datetime) -> Path:
    """Where a detached GCM's output goes: one file for each start, kept between starts."""
    return home / "logs" / f"gcm-{now:%Y%m%d-%H%M%S}.log"


def prepare(
    home: Path, *, fresh: bool, many: int, few: int, local: int = 0, mountinfo: str | None = None
) -> bool:
    """Make `home` hold a configuration. True when it was written, False when kept.

    `fresh` removes `home` first, but only a folder called `sandbox_cache` directly under a
    `tmp` and not a link, so a wrong path cannot take anything else with it. It refuses while
    a mount lies at or below `home`: `rmtree` deletes inside one before it fails. `mountinfo`
    is the text of /proc/self/mountinfo, read when not given.
    """
    if fresh:
        if home.name != HOME_NAME or home.parent.name != "tmp" or home.is_symlink():
            raise ValueError(f"refusing to remove {home}: not a tmp/{HOME_NAME}")
        if mountinfo is None:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8", errors="replace")
        mounted = mounts_below(home, mountinfo)
        if mounted:
            raise ValueError(
                f"refusing to remove {home}: {mounted[0]} is mounted there; unmount it "
                "first, from GCM's Mounted tab or with `fusermount -u`"
            )
        shutil.rmtree(home, ignore_errors=True)
    if config_file(home).is_file():
        return False
    write_config(config_file(home), many, few, local)
    return True


def environment(
    base: dict[str, str],
    home: Path,
    scale: str | None,
    trace: str = "",
    wayland_debug: bool = False,
    display: str | None = None,
) -> dict[str, str]:
    """`base` with HOME set to the sandbox and what points elsewhere removed.

    `scale` becomes GDK_DPI_SCALE, as typed; without it the caller's own is left alone.
    DISPLAY, WAYLAND_DISPLAY and GDK_BACKEND are the caller's, unless `display` is given, an
    X display of the run's own (#509): then DISPLAY is it, GDK_BACKEND is x11, and
    WAYLAND_DISPLAY and the caller's GDK_DPI_SCALE are removed, as the test suite does for
    its own Xvfb, so GTK cannot go back to the caller's desktop. `scale` still applies.

    `trace` becomes GCM_TRACE, and `wayland_debug` sets WAYLAND_DEBUG=client, so that the
    protocol and GCM's trace lines share the one log (#507). Without them GCM_TRACE and
    WAYLAND_DEBUG are the caller's, as DISPLAY is.
    """
    env = {key: value for key, value in base.items() if key not in UNSET + AGENT}
    env["HOME"] = str(home)
    env["PYTHONFAULTHANDLER"] = "1"
    if display is not None:
        env["DISPLAY"] = display
        env["GDK_BACKEND"] = "x11"
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("GDK_DPI_SCALE", None)
    if scale:
        try:
            number = float(scale)
        except ValueError:
            number = math.nan
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"--scale must be a positive number, not {scale!r}")
        env["GDK_DPI_SCALE"] = scale
    if trace:
        env["GCM_TRACE"] = trace
    if wayland_debug:
        env["WAYLAND_DEBUG"] = "client"
    return env


def command(repo: Path = REPO) -> list[str]:
    """The checkout's own interpreter, not `uv run`, whose cache would be sought under HOME."""
    return [str(repo / ".venv" / "bin" / "python"), "-m", "gnome_connection_manager"]
