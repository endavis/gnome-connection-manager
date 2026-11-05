"""`doit wslg_windows` (#510): the windows of WSLg's own msrdc.exe, listed from WSL.

Nothing here reaches a real PowerShell: `subprocess.run` raises in both modules that could
call it, and the lister's output is made up. Its run on WSL is recorded on #510.
"""

from __future__ import annotations

import base64
import subprocess
from typing import TYPE_CHECKING

import pytest

from tools import wslg_windows as w
from tools.doit import gcm

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

WSLG = w.WSLG_MSRDC
RDP = r"C:\Program Files\Remote Desktop\msrdc.exe"
LINUX = "6.6.87.2-microsoft-standard-WSL2"
NOT_WSL = "6.17.13-2-pve"


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test ran a real process")

    monkeypatch.setattr(w.subprocess, "run", refuse)
    monkeypatch.setattr(gcm.subprocess, "run", refuse)


def row(
    hwnd: str,
    pid: int,
    visible: int,
    title: str,
    size: str = "800x600@10,20",
    default: str = "355x266@4,9",
    dpi: int = 216,
    cls: str = "RAIL_WINDOW",
) -> str:
    return f"{hwnd}\t{pid}\t{visible}\tphys={size}\tdefault={default}\tdpi={dpi}\t{cls}\t{title}"


OUTPUT = "\r\n".join(
    [
        f"process\t100\t{WSLG}",
        f"process\t200\t{RDP}",
        "process\t300\t",
        "default-dpi-awareness=0",
        row("0x10", 100, 1, "GCM sandbox"),
        row("0x11", 100, 0, "hidden one", size="153x48@5,6"),
        row("0x20", 200, 1, "Work RDP"),
        row("0x30", 300, 1, "no path"),
        "",
    ]
)


def completed(
    stdout: str = "", stderr: str = "", code: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def runner(
    result: subprocess.CompletedProcess[str],
) -> Callable[[Sequence[str]], subprocess.CompletedProcess[str]]:
    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        run.argv = list(argv)  # type: ignore[attr-defined]
        return result

    return run


def test_only_wslgs_windows_are_listed() -> None:
    windows = w.wslg_windows(OUTPUT)

    assert [(x.hwnd, x.title, x.visible) for x in windows] == [
        ("0x10", "GCM sandbox", True),
        ("0x11", "hidden one", False),
    ]
    first = windows[0]
    assert (first.width, first.height, first.x, first.y) == (800, 600, 10, 20)
    assert (first.default_width, first.default_height) == (355, 266)
    assert (first.dpi, first.class_name, first.pid) == (216, "RAIL_WINDOW", 100)


@pytest.mark.parametrize(
    "path",
    [
        r"D:\Program Files\WSL\msrdc.exe",
        WSLG + ".bak",
        r"C:\Program Files\WSL\other\msrdc.exe",
        r"C:\Program Files\WSL\msrdc.exe\x",
        "",
    ],
)
def test_a_path_that_is_not_wslgs_matches_nothing(path: str) -> None:
    assert w.wslg_pids({1: path}) == set()


def test_the_path_is_wslgs_whatever_its_case() -> None:
    assert w.wslg_pids({1: WSLG.upper(), 2: WSLG.lower()}) == {1, 2}


def test_a_title_with_a_tab_stays_whole() -> None:
    out = f"process\t1\t{WSLG}\n" + row("0x1", 1, 1, "a\tb\tc")

    assert w.wslg_windows(out)[0].title == "a\tb\tc"


def test_crlf_and_blank_lines_are_ignored() -> None:
    out = f"process\t1\t{WSLG}\r\n\r\ndefault-dpi-awareness=0\r\n" + row("0x1", 1, 1, "t") + "\r\n"

    processes, windows = w.parse(out)

    assert processes == {1: WSLG}
    assert [x.title for x in windows] == ["t"]


def test_a_window_is_shown_on_one_line() -> None:
    line = w.format_window(w.wslg_windows(OUTPUT)[0])

    assert "\n" not in line
    for part in (
        "GCM sandbox",
        "10,20",
        "800x600",
        "visible",
        "355x266",
        "dpi 216",
        "RAIL_WINDOW",
        "0x10",
    ):
        assert part in line
    assert "hidden" in w.format_window(w.wslg_windows(OUTPUT)[1])


def test_main_prints_wslgs_windows_and_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    run = runner(completed(OUTPUT))

    code = w.main([], kernel_release=LINUX, environ={}, powershell="/ps.exe", run=run)

    out = capsys.readouterr().out
    assert code == 0
    assert "GCM sandbox" in out and "hidden one" in out
    assert "Work RDP" not in out and "no path" not in out
    assert out.splitlines()[-1] == "2 windows of WSLg's msrdc.exe, 1 visible"
    assert run.argv[0] == "/ps.exe"  # type: ignore[attr-defined]


def test_main_outside_wsl_says_so_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code = w.main([], kernel_release=NOT_WSL, environ={})

    assert code == 2
    assert capsys.readouterr().err.startswith("Not WSL")


def test_wsl_is_known_by_its_kernel_or_its_distro() -> None:
    assert w.under_wsl(LINUX, {})
    assert w.under_wsl("5.15.0-Microsoft", {})
    assert w.under_wsl(NOT_WSL, {"WSL_DISTRO_NAME": "Ubuntu"})
    assert not w.under_wsl(NOT_WSL, {})


def test_main_without_powershell_says_why(capsys: pytest.CaptureFixture[str]) -> None:
    code = w.main([], kernel_release=LINUX, environ={}, powershell="")

    assert code == 2
    assert "interop" in capsys.readouterr().err


def test_main_reports_a_powershell_failure(capsys: pytest.CaptureFixture[str]) -> None:
    run = runner(completed(stderr="boom", code=5))

    code = w.main([], kernel_release=LINUX, environ={}, powershell="/ps.exe", run=run)

    assert code == 1
    assert "boom" in capsys.readouterr().err


def test_main_without_wslgs_msrdc_lists_the_paths_it_saw(
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = f"process\t200\t{RDP}\nprocess\t300\t\n" + row("0x20", 200, 1, "Work RDP")
    run = runner(completed(out))

    code = w.main([], kernel_release=LINUX, environ={}, powershell="/ps.exe", run=run)

    captured = capsys.readouterr()
    assert code == 1
    assert RDP in captured.err and "(no path)" in captured.err
    assert "Work RDP" not in captured.out


def test_main_with_no_msrdc_at_all_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    code = w.main(
        [],
        kernel_release=LINUX,
        environ={},
        powershell="/ps.exe",
        run=runner(completed("default-dpi-awareness=0\n")),
    )

    assert code == 1
    assert "no msrdc.exe is running" in capsys.readouterr().err


def test_the_command_round_trips_through_encoded_command() -> None:
    argv = w.command("/ps.exe", "Write-Output 'é'")

    assert argv[:5] == ["/ps.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden"]
    assert argv[5] == "-EncodedCommand"
    assert base64.b64decode(argv[6]).decode("utf-16-le") == "Write-Output 'é'"
    assert base64.b64decode(w.command("p")[6]).decode("utf-16-le") == w.SCRIPT


def test_the_script_lists_every_window_of_every_msrdc_and_filters_nothing_by_path() -> None:
    assert "Get-Process -Name msrdc" in w.SCRIPT
    assert "process`t" in w.SCRIPT
    assert "-like" not in w.SCRIPT
    assert "IsWindowVisible(h) ?" in w.SCRIPT
    assert "pids.Contains(pid)) {" in w.SCRIPT  # not "&& IsWindowVisible"
    assert "&& IsWindowVisible" not in w.SCRIPT
    assert "default-dpi-awareness=" in w.SCRIPT
    assert "$" not in w.SCRIPT.split('"@')[0].split('@"')[1]  # a here-string would expand it


def test_powershell_is_found_on_the_path_first() -> None:
    assert (
        w.find_powershell(lambda name: "/bin/" + name, lambda path: True) == "/bin/powershell.exe"
    )


def test_powershell_falls_back_to_its_usual_place() -> None:
    assert (
        w.find_powershell(lambda name: None, lambda path: path == w.FALLBACK_POWERSHELL)
        == w.FALLBACK_POWERSHELL
    )
    assert w.find_powershell(lambda name: None, lambda path: False) is None


def test_run_powershell_asks_subprocess_for_utf8_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs, argv=argv)
        return completed("ok")

    monkeypatch.setattr(w.subprocess, "run", fake)

    assert w.run_powershell(["p", "x"]).stdout == "ok"
    assert seen["argv"] == ["p", "x"]
    assert seen["capture_output"] is True and seen["text"] is True
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert seen["check"] is False and seen["timeout"] == w.TIMEOUT


def test_the_task_runs_main_and_fails_outside_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    task = gcm.task_wslg_windows()
    assert task["verbosity"] == 2
    (action,) = task["actions"]
    calls: list[Sequence[str] | None] = []

    def fake(argv: Sequence[str] | None = None) -> int:
        calls.append(argv)
        return 2

    monkeypatch.setattr(w, "main", fake)

    assert action() is False
    assert calls == [[]]
    monkeypatch.setattr(w, "main", lambda argv=None: 0)
    assert action() is True


def test_the_real_main_outside_wsl_fails() -> None:
    assert w.main([], kernel_release=NOT_WSL, environ={}) == 2
