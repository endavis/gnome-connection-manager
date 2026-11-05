"""GCM_TRACE's areas, stamp and safety (#507)."""

import io
import logging
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gnome_connection_manager.utils import trace


@pytest.fixture(autouse=True)
def reset() -> object:
    yield
    trace.configure({})


def test_parse_names_areas() -> None:
    both = frozenset({"drag", "menu"})
    assert trace.parse("drag,menu") == (both, ())
    assert trace.parse(" Drag , ") == (frozenset({"drag"}), ())
    assert trace.parse("all") == (frozenset(trace.AREAS), ())
    assert trace.parse(None) == (frozenset(), ())
    assert trace.parse("") == (frozenset(), ())
    assert trace.parse("drag,bogus,bogus") == (frozenset({"drag"}), ("bogus",))


def test_stamp_is_libwaylands() -> None:
    assert trace.stamp(0) == "[      0.000]"
    assert trace.stamp(1_234_567) == "[   1234.567]"
    assert trace.stamp(2**32 + 5) == trace.stamp(5)
    assert trace.stamp(2**32 - 1) == "[4294967.295]"


def test_a_line_starts_with_the_stamp_and_area() -> None:
    out = io.StringIO()
    trace.configure({"GCM_TRACE": "drag"}, stream=out)

    trace.note(trace.DRAG, lambda: "hello 50% done")

    assert re.match(r"^\[\s*\d+\.\d{3}\] drag: hello 50% done\n$", out.getvalue())


def test_an_area_that_is_off_calls_nothing_whatever_the_log_level() -> None:
    out = io.StringIO()
    trace.configure({"GCM_TRACE": "drag"}, stream=out)
    logging.getLogger("gnome_connection_manager").setLevel(logging.DEBUG)
    called = []

    trace.note(trace.MENU, lambda: called.append(1) or "x")

    assert called == []
    assert out.getvalue() == ""


def test_note_swallows_what_the_message_or_a_handler_raises() -> None:
    out = io.StringIO()
    trace.configure({"GCM_TRACE": "drag"}, stream=out)

    def boom() -> str:
        raise RuntimeError("no")

    trace.note(trace.DRAG, boom)
    with patch.object(trace.TraceHandler, "emit", side_effect=OSError("closed")):
        trace.note(trace.DRAG, lambda: "x")

    assert out.getvalue() == ""


def test_configure_is_idempotent_and_keeps_the_root_handler_out() -> None:
    out = io.StringIO()
    seen: list[str] = []

    class Root(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    root = Root()
    logging.getLogger().addHandler(root)
    try:
        trace.configure({"GCM_TRACE": "drag,menu"}, stream=out)
        trace.configure({"GCM_TRACE": "drag"}, stream=out)
        trace.note(trace.DRAG, lambda: "once")
    finally:
        logging.getLogger().removeHandler(root)

    assert out.getvalue().count("once") == 1
    assert seen == []
    assert not logging.getLogger("gnome_connection_manager.drag").propagate
    menu = logging.getLogger("gnome_connection_manager.menu")
    assert not [h for h in menu.handlers if isinstance(h, trace.TraceHandler)]
    assert menu.propagate


def test_the_handler_writes_to_stderr_as_it_is_then(capsys: pytest.CaptureFixture[str]) -> None:
    trace.configure({"GCM_TRACE": "menu"})
    trace.note(trace.MENU, lambda: "to stderr")
    assert "menu: to stderr" in capsys.readouterr().err


def test_first_enabled_and_enabled() -> None:
    assert trace.first_enabled() is None
    trace.configure({"GCM_TRACE": "menu"})
    assert trace.first_enabled() == "menu"
    assert trace.enabled("menu")
    assert not trace.enabled("drag")


def test_environment_line_has_a_fixed_order() -> None:
    line = trace.environment_line({"commit": "abc", "gtk": "3.24.1", "font": "Ubuntu 11"})
    assert line.startswith("environment gtk=3.24.1 display=(unset) ")
    assert 'font="Ubuntu 11"' in line
    assert line.endswith("commit=abc")
    keys = re.findall(r"(\w+)=", line)
    assert keys == list(trace.ENVIRONMENT_KEYS)


def test_place_forms() -> None:
    assert trace.place(2, 3, None) == "pane 2 of 3"
    assert trace.place(None, 0, 1) == "window 1"
    assert trace.place(None, 3, None) == "place not read during a drag"


def test_tabs_line() -> None:
    line = trace.tabs_line([(1, "pane 1 of 1", ["a", "b"]), (2, "window 1", [])], ["b"])
    assert (
        line
        == "tabs notebook 1 (pane 1 of 1): a, b | notebook 2 (window 1): (no tabs) | stray labels: b"
    )
    assert trace.tabs_line([], []).endswith("stray labels: none")
    assert trace.tabs_line([], [], checked=False).endswith("labels not checked")


def test_mark_line() -> None:
    assert trace.mark_line("after drop") == "=== MARK after drop ==="


def test_read_mark_label(tmp_path: Path) -> None:
    assert trace.read_mark_label(tmp_path / "none") == "(no label)"
    path = tmp_path / "trace-mark"
    path.write_text("  first \nsecond\n")
    assert trace.read_mark_label(path) == "first"
    path.write_text("x" * 500)
    assert len(trace.read_mark_label(path)) == 200
    path.write_text("")
    assert trace.read_mark_label(path) == "(no label)"


def test_checkout_commit(tmp_path: Path) -> None:
    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    with patch.object(trace.subprocess, "run") as run:
        assert trace.checkout_commit(package) is None
        run.assert_not_called()

    (tmp_path / ".git").write_text("gitdir: elsewhere")
    with patch.object(trace.subprocess, "run", return_value=MagicMock(returncode=1, stdout="")):
        assert trace.checkout_commit(package) is None
    with patch.object(trace.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 2)):
        assert trace.checkout_commit(package) is None
    with patch.object(trace.subprocess, "run", side_effect=OSError):
        assert trace.checkout_commit(package) is None
    done = MagicMock(returncode=0, stdout="abc1234\n")
    with patch.object(trace.subprocess, "run", return_value=done) as run:
        assert trace.checkout_commit(package) == "abc1234"
    assert str(tmp_path) in run.call_args.args[0]
