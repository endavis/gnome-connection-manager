"""Tests for the update check (#295): utils/updates.py, and Wmain.check_updates in app.py,
which makes the request in a process of its own (#369)."""

from __future__ import annotations

import ast
import email.message
import gettext
import io
import json
import re
import subprocess
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gnome_connection_manager.utils import childpython, updates
from tests.test_connections import glib_complaints

if TYPE_CHECKING:
    from collections.abc import Callable

REPO = Path(__file__).resolve().parents[1]


def test_only_a_release_tag_names_a_version():
    assert updates.release_version("v2.0.0") == (2, 0, 0)
    assert updates.release_version("v10.11.12") == (10, 11, 12)
    for tag in ("2.0.0", "v2.1.0rc1", "v2.0", "latest", "v2.0.0-beta", " v2.0.0"):
        assert updates.release_version(tag) is None, tag


def test_versions_compare_as_numbers():
    """The check this replaced compared strings, under which 10.0.0 is less than 9.0.0."""
    assert "10.0.0" < "9.0.0"
    assert updates.newer_release(["v9.0.0", "v10.0.0"], "9.0.0") == "10.0.0"
    assert updates.newer_release(["v2.0.10"], "2.0.9") == "2.0.10"


def test_the_newest_release_is_offered_in_whatever_order_they_are_listed():
    assert updates.newer_release(["v2.1.0", "v3.0.0", "v2.9.9"], "2.0.0") == "3.0.0"


@pytest.mark.parametrize("tags", [[], ["v2.0.0"], ["v1.2.1", "v1.9.9"], ["latest", "v3.0.0rc1"]])
def test_nothing_newer_is_no_release(tags):
    assert updates.newer_release(tags, "2.0.0") is None


def test_a_running_version_no_release_has_is_told_nothing():
    assert updates.newer_release(["v9.0.0"], "2.0.0.dev1") is None
    assert updates.newer_release(["v9.0.0"], "") is None


def test_tag_names_reads_the_list_github_gives():
    answer = [{"name": "v2.0.0", "commit": {"sha": "18d1e9d"}}, {"name": "v1.0.0"}]
    assert updates.tag_names(answer) == ["v2.0.0", "v1.0.0"]


@pytest.mark.parametrize(
    "answer",
    [
        None,
        5,
        {"message": "API rate limit exceeded"},
        "v9.9.9",
        ["v9.9.9"],
        [{"tag": "v9.9.9"}],
        [{"name": 9}],
    ],
)
def test_any_other_answer_lists_no_tags(answer):
    assert updates.tag_names(answer) == []


def github(monkeypatch, tags=(), body=None, error=None):
    """Answer the request with `tags`, or `body` as it is, or raise `error`.
    Returns each request made, with its timeout."""
    asked = []

    def urlopen(request, timeout=None):
        asked.append((request, timeout))
        if error is not None:
            raise error
        return io.BytesIO(
            body if body is not None else json.dumps([{"name": t} for t in tags]).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return asked


def test_the_request_asks_this_repository_for_its_tags(monkeypatch):
    asked = github(monkeypatch, tags=["v2.0.0"])

    assert updates.main([updates.TAGS_URL]) == 0

    [(request, timeout)] = asked
    assert request.full_url == updates.TAGS_URL
    assert updates.TAGS_URL.startswith(
        "https://api.github.com/repos/endavis/gnome-connection-manager/"
    )
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert timeout == 5


def test_the_answer_is_written_as_it_came(monkeypatch, capsysbinary):
    """As bytes, so that GCM reads what GitHub sent, whatever it holds."""
    body = b'[{"name": "v2.1.0"}]\n' + bytes([0xFF])
    github(monkeypatch, body=body)

    assert updates.main(["https://example.invalid/tags"]) == 0

    assert capsysbinary.readouterr().out == body


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no network"),
        TimeoutError(),
        urllib.error.HTTPError(updates.TAGS_URL, 403, "rate limit", email.message.Message(), None),
    ],
    ids=["no network", "timeout", "refused"],
)
def test_a_failed_request_writes_nothing(monkeypatch, capsysbinary, error):
    github(monkeypatch, error=error)

    assert updates.main([updates.TAGS_URL]) == 1

    assert capsysbinary.readouterr().out == b""


def test_the_request_runs_as_gcm_runs_it(app_module, monkeypatch, tmp_path):
    answer = tmp_path / "tags.json"
    answer.write_bytes(b'[{"name": "v9.9.9"}]')
    # The command Wmain.check_updates builds, bar the URL it asks for (#415).
    *command, asked = start_check(app_module, monkeypatch).process.argv
    assert asked == updates.TAGS_URL

    found = subprocess.run([*command, answer.as_uri()], capture_output=True, timeout=60)
    missing = subprocess.run(
        [*command, (tmp_path / "none.json").as_uri()], capture_output=True, timeout=60
    )

    assert (found.returncode, found.stdout) == (0, answer.read_bytes())
    assert (missing.returncode, missing.stdout, missing.stderr) == (1, b"", b"")


def tags_listed(*tags):
    """GitHub's answer listing `tags`."""
    return json.dumps([{"name": tag} for tag in tags]).encode()


class Bytes:
    """GLib.Bytes, as the check reads it."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def get_data(self) -> bytes:
        return self.data


class LaunchError(Exception):
    """GLib.Error, which the stub has no class for."""


# The real values, which test_the_fakes_match_real_gio holds these to.
FLAGS = types.SimpleNamespace(STDOUT_PIPE=4, STDERR_SILENCE=32)


class Process:
    """Gio.Subprocess as the check uses it: started, read once it has ended, and killed
    if GCM quits first. `end` is the main loop calling back as the process ends."""

    def __init__(self, argv, flags, answer, status):
        self.argv = argv
        self.flags = flags
        self.answer = answer
        self.status = status
        self.callback: Callable[[Process, object], None] | None = None
        self.killed = False

    def communicate_async(self, stdin_buf, cancellable, callback):
        self.callback = callback

    def communicate_finish(self, result):
        return True, Bytes(self.answer), None

    def get_successful(self):
        return self.status == 0 and not self.killed

    def force_exit(self):
        self.killed = True

    def end(self):
        assert self.callback is not None, "the check never asked for its answer"
        self.callback(self, object())


def start_check(app_module, monkeypatch, answer=b"", status=0, new=None):
    """Start the check on a Wmain built without new(), as GCM starts it 2 s in, against a
    fake process that writes `answer` and exits with `status`."""
    started: list[Process] = []

    def start(argv, flags):
        started.append(Process(argv, flags, answer, status))
        return started[-1]

    monkeypatch.setattr(app_module.Gio, "Subprocess", types.SimpleNamespace(new=new or start))
    monkeypatch.setattr(app_module.Gio, "SubprocessFlags", FLAGS)
    monkeypatch.setattr(app_module.GLib, "Error", LaunchError)
    shown: list[tuple[str, object]] = []
    monkeypatch.setattr(
        app_module, "msginfo", lambda text, parent=None: shown.append((text, parent))
    )
    window = object()
    wmain = object.__new__(app_module.Wmain)
    wmain.get_widget = lambda name: window if name == "wMain" else None
    wmain.check_updates()
    return types.SimpleNamespace(
        wmain=wmain, window=window, process=started[0] if started else None, shown=shown
    )


def test_the_check_asks_in_a_process_of_its_own(app_module, monkeypatch):
    """Not on a thread: GCM quit during the request exited with the thread still inside
    it, as did the test that crashed at exit in #316 (#369)."""
    check = start_check(app_module, monkeypatch)

    assert check.process.argv == [
        *childpython.module_command("gnome_connection_manager.utils.updates"),
        updates.TAGS_URL,
    ]
    # Its answer through a pipe, and anything it says on stderr nowhere.
    assert check.process.flags == FLAGS.STDOUT_PIPE | FLAGS.STDERR_SILENCE
    assert check.wmain.update_check is check.process
    assert check.shown == []


def test_a_newer_release_is_shown_as_information(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "app_version", "2.0.0")
    check = start_check(app_module, monkeypatch, tags_listed("v2.0.0", "v2.1.0", "latest"))

    check.process.end()

    [(text, parent)] = check.shown
    assert "2.1.0" in text
    assert "2.0.0" in text
    assert updates.INSTALL_PAGE in text
    assert parent is check.window
    assert check.wmain.update_check is None


@pytest.mark.parametrize("tags", [["v2.0.0"], ["v1.2.1"], []])
def test_no_newer_release_shows_nothing(app_module, monkeypatch, tags):
    monkeypatch.setattr(app_module, "app_version", "2.0.0")
    check = start_check(app_module, monkeypatch, tags_listed(*tags))

    check.process.end()

    assert check.shown == []


@pytest.mark.parametrize(
    "failure",
    [
        {"answer": tags_listed("v9.9.9"), "status": 1},
        {"answer": b"<html>Service Unavailable</html>"},
        {"answer": json.dumps({"message": "API rate limit exceeded"}).encode()},
    ],
    ids=["failed", "not json", "not a list"],
)
def test_a_failure_shows_nothing(app_module, monkeypatch, failure):
    monkeypatch.setattr(app_module, "app_version", "1.0.0")
    check = start_check(app_module, monkeypatch, **failure)

    check.process.end()

    assert check.shown == []
    assert check.wmain.update_check is None


def test_an_answer_that_cannot_be_read_shows_nothing(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "app_version", "1.0.0")
    check = start_check(app_module, monkeypatch, tags_listed("v9.9.9"))

    def unread(result):
        raise LaunchError("Error reading from file descriptor")

    check.process.communicate_finish = unread
    check.process.end()

    assert check.shown == []


def test_a_check_that_cannot_start_says_nothing(app_module, monkeypatch):
    def cannot_start(argv, flags):
        raise LaunchError("Failed to execute child process")

    check = start_check(app_module, monkeypatch, new=cannot_start)

    assert check.wmain.update_check is None
    assert check.shown == []


def test_quitting_ends_a_check_still_asking(app_module, monkeypatch):
    check = start_check(app_module, monkeypatch)

    check.wmain.quit_application()

    assert check.process.killed


def test_quitting_once_the_check_has_ended_ends_nothing(app_module, monkeypatch):
    check = start_check(app_module, monkeypatch)
    check.process.end()

    check.wmain.quit_application()

    assert not check.process.killed


def test_quitting_before_the_check_starts(app_module, monkeypatch):
    quits: list[bool] = []
    monkeypatch.setattr(app_module.Gtk, "main_quit", lambda: quits.append(True))
    wmain = object.__new__(app_module.Wmain)
    wmain.get_widget = lambda name: None

    wmain.quit_application()

    assert quits == [True]


def test_the_fakes_match_real_gio():
    pytest.importorskip("gi", reason="PyGObject not available")
    from gi.repository import Gio, GLib

    assert callable(Gio.Subprocess.new)
    for method in ("communicate_async", "communicate_finish", "get_successful", "force_exit"):
        assert hasattr(Gio.Subprocess, method), method
    assert hasattr(GLib.Bytes, "get_data")
    assert issubclass(GLib.Error, Exception)
    assert Gio.SubprocessFlags.STDOUT_PIPE == FLAGS.STDOUT_PIPE
    assert Gio.SubprocessFlags.STDERR_SILENCE == FLAGS.STDERR_SILENCE


_SCRIPT = r"""
import os, signal, socket, sys, tempfile, threading, time
from pathlib import Path
scenario, scratch = sys.argv[1], sys.argv[2]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
# Started as GCM starts, so that its quit action is the one Ctrl+Q runs. Each scenario
# starts the check itself, against an answer of its own.
application = app.GcmApplication()
assert application.register(None)
application.activate()
w = application._controller

def until(condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        Gtk.main_iteration_do(False)
        time.sleep(0.005)
    return condition()

if scenario == "a-newer-release-is-shown":
    answer = Path(scratch) / "tags.json"
    answer.write_text('[{"name": "v99.0.0"}]')
    app.updates.TAGS_URL = answer.as_uri()
    shown = []
    app.msginfo = lambda text, parent=None: shown.append((text, parent))
    w.check_updates()
    assert until(lambda: shown), "no notice"
    [(text, parent)] = shown
    assert "99.0.0" in text, text
    assert parent is w.get_widget("wMain")
elif scenario == "quit-during-the-request":
    # A port that takes the connection and never answers, so that the request is still
    # waiting when GCM quits.
    port = socket.create_server(("127.0.0.1", 0))
    port.setblocking(False)
    app.updates.TAGS_URL = "http://127.0.0.1:%d/tags" % port.getsockname()[1]
    w.check_updates()
    check = w.update_check
    connections = []

    def connected():
        try:
            connections.append(port.accept()[0])
        except BlockingIOError:
            pass
        return connections

    assert until(connected), "the request never came"
    asked = time.monotonic()
    application.activate_action("quit", None)
    check.wait(None)
    # The request would wait out its 5 s.
    assert time.monotonic() - asked < 3, "quitting waited for the request"
    assert check.get_if_signaled() and check.get_term_sig() == signal.SIGKILL
else:
    raise SystemExit("no scenario " + scenario)
# Nothing of GCM's still running as the process exits (#369).
assert threading.enumerate() == [threading.main_thread()], threading.enumerate()
print("OK")
"""


@pytest.mark.parametrize("scenario", ["a-newer-release-is-shown", "quit-during-the-request"])
def test_the_check_against_real_gtk(scenario, tmp_path):
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []


def test_no_scenario_runs_the_check():
    """A scenario builds GCM with the check off (#316), and one about the check starts it
    itself, against an answer of its own: with it on, every scenario longer than 2 s asked
    GitHub for the tags. On the daemon thread the check had before #369, the registry's
    open-in-browser scenario, which ends about then, exited 16 ms into its request on
    every run, measured, and died of SIGSEGV at exit on CI now and then."""
    builds = re.compile(r"app\.(Wmain|GcmApplication)\(")
    scripts: list[str] = []
    on: list[str] = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            built = builds.search(node.value)
            if built:
                scripts.append(path.name)
                if not 0 <= node.value.find("app.conf.CHECK_UPDATES = False") < built.start():
                    on.append(f"{path.name}:{node.lineno}")
    assert "test_connections.py" in scripts, scripts  # the scan finds the scripts at all
    assert on == [], on


def test_gcm_neither_asks_nor_links_to_the_original_authors_site():
    """The copyright lines credit its author by address, and stay."""
    for path in ("src/gnome_connection_manager/app.py", "data/ui/gnome-connection-manager.glade"):
        assert "kuthulu.com" not in (REPO / path).read_text(encoding="utf-8"), path


@pytest.mark.parametrize(
    "language",
    sorted(p.parent.parent.name for p in (REPO / "lang").glob("*/LC_MESSAGES/gcm-lang.mo")),
)
def test_every_translation_of_the_notice_takes_its_values(language):
    """A placeholder misspelt in a translation raises as the notice is built, and the
    notice is lost."""
    with (REPO / "lang" / language / "LC_MESSAGES" / "gcm-lang.mo").open("rb") as mo:
        catalog = gettext.GNUTranslations(mo)
    available = catalog.gettext("GCM {new} is available. You are running {current}.")
    install = catalog.gettext("How to install it: {url}")

    filled = available.format(new="9.9.9", current="2.0.0")
    assert "9.9.9" in filled
    assert "2.0.0" in filled
    # Not an address: CodeQL reads `"https://..." in text` as a URL checked by substring.
    assert "WHERE-TO-INSTALL" in install.format(url="WHERE-TO-INSTALL")
