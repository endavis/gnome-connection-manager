"""List the windows WSLg's own `msrdc.exe` holds, from inside WSL (#510).

`doit wslg_windows` runs a small EnumWindows lister through `powershell.exe`, the one #401
used to find the grey rectangles a failed tab drag leaves on the Windows desktop. Each window
is shown with its title, place and size, whether it is visible, the size read the way
PowerShell's default DPI awareness reads it, its DPI and its class.

WSLg's windows belong to `C:\\Program Files\\WSL\\msrdc.exe`, matched by its whole path and not
its name: a Remote Desktop client is `msrdc.exe` too, and a filter on the name alone read that
client's window title (#401). Another `msrdc.exe` is never listed, but its path is shown when
no WSLg one is found, so an install elsewhere can be seen.

It was built on an LXC container with no Windows, so every test here uses a fake PowerShell
and fake output. It was then run on WSL on 2026-11-05, with GCM open under WSLg (#510). It
listed GCM's window as visible, the same window #401's lister listed beside it, and WSLg's
hidden windows. It left out the Windows App's `msrdc.exe`, a Remote Desktop client.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess  # nosec B404  # runs powershell.exe, the point of this module
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

WSLG_MSRDC = r"C:\Program Files\WSL\msrdc.exe"
FALLBACK_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
TIMEOUT = 120
DPI_LINE = "default-dpi-awareness="
PROCESS_ROW = "process"
# hwnd, pid, visible, phys, default, dpi, class, then the title, which may hold a tab.
WINDOW_FIELDS = 8

# Printed: `process<TAB>pid<TAB>path` for every msrdc (the path empty when Windows will not
# say), then `default-dpi-awareness=N`, then a row for every window of those pids, hidden
# ones too, as `0xHWND pid visible phys default dpi class title` split by tabs. It filters
# nothing by path: the caller does, in Python, where it is tested.
SCRIPT = r"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class GcmEnum {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] public static extern IntPtr GetThreadDpiAwarenessContext();
  [DllImport("user32.dll")] public static extern int GetAwarenessFromDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
  public static List<string> List(HashSet<uint> pids) {
    var rows = new List<string>();
    var hwnds = new List<IntPtr>();
    var owners = new Dictionary<IntPtr, uint>();
    rows.Add("default-dpi-awareness=" + GetAwarenessFromDpiAwarenessContext(GetThreadDpiAwarenessContext()));
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pids.Contains(pid)) { hwnds.Add(h); owners[h] = pid; }
      return true;
    }, IntPtr.Zero);
    var plain = new Dictionary<IntPtr, RECT>();
    foreach (var h in hwnds) { RECT r; GetWindowRect(h, out r); plain[h] = r; }
    SetThreadDpiAwarenessContext(new IntPtr(-4)); // per-monitor aware v2: physical pixels
    foreach (var h in hwnds) {
      var t = new StringBuilder(512); GetWindowText(h, t, 512);
      var c = new StringBuilder(256); GetClassName(h, c, 256);
      RECT r; GetWindowRect(h, out r);
      RECT p = plain[h];
      rows.Add(String.Format("0x{0:X}\t{1}\t{2}\tphys={3}x{4}@{5},{6}\tdefault={7}x{8}@{9},{10}\tdpi={11}\t{12}\t{13}",
        h.ToInt64(), owners[h], IsWindowVisible(h) ? 1 : 0,
        r.R - r.L, r.B - r.T, r.L, r.T, p.R - p.L, p.B - p.T, p.L, p.T,
        GetDpiForWindow(h), c, t));
    }
    return rows;
  }
}
"@
$pids = New-Object 'System.Collections.Generic.HashSet[uint32]'
Get-Process -Name msrdc -ErrorAction SilentlyContinue | ForEach-Object {
  $path = ''
  if ($_.Path) { $path = $_.Path }
  "process`t$($_.Id)`t$path"
  [void]$pids.Add([uint32]$_.Id)
}
[GcmEnum]::List($pids) | ForEach-Object { $_ }
"""


@dataclass(frozen=True)
class Window:
    """One window, as the lister printed it."""

    hwnd: str
    pid: int
    visible: bool
    width: int
    height: int
    x: int
    y: int
    default_width: int
    default_height: int
    default_x: int
    default_y: int
    dpi: int
    class_name: str
    title: str


def under_wsl(kernel_release: str, environ: Mapping[str, str]) -> bool:
    """Whether this is WSL: the kernel's release says Microsoft, or WSL names the distro."""
    return "microsoft" in kernel_release.lower() or bool(environ.get("WSL_DISTRO_NAME"))


def encode(script: str) -> str:
    """The script as `-EncodedCommand` takes it: base64 of UTF-16LE."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def command(powershell: str, script: str = SCRIPT) -> list[str]:
    """The argv that runs the script, with no profile, no prompt and no window."""
    return [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
        encode(script),
    ]


def find_powershell(
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
) -> str | None:
    """Windows' PowerShell as WSL reaches it: on PATH, else at its usual place under /mnt/c."""
    found = which("powershell.exe")
    if found:
        return found
    return FALLBACK_POWERSHELL if exists(FALLBACK_POWERSHELL) else None


def _number(field: str, prefix: str = "") -> int:
    return int(field.removeprefix(prefix))


def _box(field: str) -> tuple[int, int, int, int]:
    """`phys=WxH@x,y` (or `default=`) as width, height, x, y."""
    _, _, value = field.partition("=")
    size, _, place = value.partition("@")
    width, _, height = size.partition("x")
    x, _, y = place.partition(",")
    return int(width), int(height), int(x), int(y)


def parse(output: str) -> tuple[dict[int, str], list[Window]]:
    """The lister's output as {pid: path} of every msrdc, and every window it listed.

    A title is the last field and is split off last, so a tab in it stays in it.
    """
    processes: dict[int, str] = {}
    windows: list[Window] = []
    for raw in output.replace("\r", "").split("\n"):
        if not raw.strip() or raw.startswith(DPI_LINE):
            continue
        if raw.startswith(PROCESS_ROW + "\t"):
            _, pid, path = (raw.split("\t", 2) + [""])[:3]
            processes[int(pid)] = path.strip()
            continue
        fields = raw.split("\t", WINDOW_FIELDS - 1)
        if len(fields) < WINDOW_FIELDS:
            continue
        hwnd, pid, visible, phys, default, dpi, class_name, title = fields
        width, height, x, y = _box(phys)
        default_width, default_height, default_x, default_y = _box(default)
        windows.append(
            Window(
                hwnd=hwnd,
                pid=_number(pid),
                visible=visible.strip() == "1",
                width=width,
                height=height,
                x=x,
                y=y,
                default_width=default_width,
                default_height=default_height,
                default_x=default_x,
                default_y=default_y,
                dpi=_number(dpi, "dpi="),
                class_name=class_name,
                title=title,
            )
        )
    return processes, windows


def wslg_pids(processes: Mapping[int, str]) -> set[int]:
    """The processes whose whole path is WSLg's `msrdc.exe`, case aside; no path matches none."""
    wanted = WSLG_MSRDC.lower()
    return {pid for pid, path in processes.items() if path.lower() == wanted}


def wslg_windows(output: str) -> list[Window]:
    """The windows of WSLg's own `msrdc.exe` in the lister's output, and no one else's."""
    processes, windows = parse(output)
    pids = wslg_pids(processes)
    return [window for window in windows if window.pid in pids]


def format_window(window: Window) -> str:
    """One window on one line."""
    return (
        f"{window.title!r} at {window.x},{window.y}, "
        f"{window.width}x{window.height}, "
        f"{'visible' if window.visible else 'hidden'}, "
        f"read as {window.default_width}x{window.default_height} by default, "
        f"dpi {window.dpi}, class {window.class_name}, {window.hwnd}"
    )


def run_powershell(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run the command, decoding its output as UTF-8 and never raising for its status."""
    return subprocess.run(  # nosec B603  # argv is a PowerShell path and our own script
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        check=False,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    kernel_release: str | None = None,
    environ: Mapping[str, str] | None = None,
    powershell: str | None = None,
    run: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_powershell,
) -> int:
    """Print the windows of WSLg's msrdc.exe. 0 if there is one, 1 on a failure, 2 off WSL."""
    argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None).parse_args(
        argv
    )
    if kernel_release is None:
        from gnome_connection_manager.utils.osc52 import kernel_release as read_kernel_release

        kernel_release = read_kernel_release()
    if environ is None:
        environ = os.environ
    if not under_wsl(kernel_release, environ):
        print("Not WSL: this lists the windows of WSLg, which only WSL has.", file=sys.stderr)
        return 2
    if powershell is None:
        powershell = find_powershell()
    if not powershell:
        print(
            "No powershell.exe: WSL's Windows interop is off or Windows is not on the PATH, "
            f"and {FALLBACK_POWERSHELL} is not there.",
            file=sys.stderr,
        )
        return 2
    result = run(command(powershell))
    if result.returncode != 0:
        print(f"powershell.exe exited {result.returncode}.", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1
    processes, _ = parse(result.stdout)
    if not wslg_pids(processes):
        print(f"No msrdc.exe at {WSLG_MSRDC}.", file=sys.stderr)
        for pid, path in sorted(processes.items()):
            print(f"  msrdc.exe {pid}: {path or '(no path)'}", file=sys.stderr)
        if not processes:
            print("  no msrdc.exe is running.", file=sys.stderr)
        return 1
    windows = wslg_windows(result.stdout)
    for window in windows:
        print(format_window(window))
    shown = sum(1 for window in windows if window.visible)
    print(f"{len(windows)} windows of WSLg's msrdc.exe, {shown} visible")
    return 0


if __name__ == "__main__":
    sys.exit(main())
