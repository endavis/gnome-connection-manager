"""Tests for the update check (#295): utils/updates.py, and CheckUpdates in app.py."""

from __future__ import annotations

import gettext
import io
import json
import socket
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from gnome_connection_manager.utils import updates

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
    """Answer the check's request with `tags`, or `body` as it is, or raise `error`.
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


def scheduled(app_module, monkeypatch):
    """What the check hands the main loop to run."""
    queued = []
    monkeypatch.setattr(
        app_module.GLib, "idle_add", lambda callback, *args: queued.append((callback, args))
    )
    return queued


def test_the_check_asks_this_repository_for_its_tags(app_module, monkeypatch):
    asked = github(monkeypatch, tags=["v2.0.0"])
    scheduled(app_module, monkeypatch)
    set_globally: list[float | None] = []
    monkeypatch.setattr(socket, "setdefaulttimeout", set_globally.append)

    app_module.CheckUpdates(None).run()

    [(request, timeout)] = asked
    assert request.full_url == updates.TAGS_URL
    assert updates.TAGS_URL.startswith(
        "https://api.github.com/repos/endavis/gnome-connection-manager/"
    )
    # The timeout is the request's: set for the process, it applied to every socket after.
    assert timeout == 5
    assert set_globally == []


def test_a_newer_release_is_shown_as_information(app_module, monkeypatch):
    github(monkeypatch, tags=["v2.0.0", "v2.1.0", "latest"])
    queued = scheduled(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "app_version", "2.0.0")
    shown = []
    monkeypatch.setattr(
        app_module, "msginfo", lambda text, parent=None: shown.append((text, parent))
    )
    window = object()
    wmain = types.SimpleNamespace(get_widget=lambda name: window if name == "wMain" else None)

    app_module.CheckUpdates(wmain).run()

    [(callback, args)] = queued
    assert callback(*args) is False, "an idle callback that returns True runs again"
    [(text, parent)] = shown
    assert "2.1.0" in text
    assert "2.0.0" in text
    assert updates.INSTALL_PAGE in text
    assert parent is window


@pytest.mark.parametrize("tags", [["v2.0.0"], ["v1.2.1"], []])
def test_no_newer_release_shows_nothing(app_module, monkeypatch, tags):
    github(monkeypatch, tags=tags)
    queued = scheduled(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "app_version", "2.0.0")

    app_module.CheckUpdates(None).run()

    assert queued == []


@pytest.mark.parametrize(
    "failure",
    [
        {"error": urllib.error.URLError("no network")},
        {"error": TimeoutError()},
        {"body": b"<html>Service Unavailable</html>"},
        {"body": json.dumps({"message": "API rate limit exceeded"}).encode()},
    ],
    ids=["no network", "timeout", "not json", "not a list"],
)
def test_a_failure_shows_nothing(app_module, monkeypatch, failure):
    github(monkeypatch, **failure)
    queued = scheduled(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "app_version", "1.0.0")

    app_module.CheckUpdates(None).run()

    assert queued == []


def test_the_check_never_holds_up_quitting(app_module):
    assert app_module.CheckUpdates(None).daemon


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
    assert "https://example.invalid" in install.format(url="https://example.invalid")
