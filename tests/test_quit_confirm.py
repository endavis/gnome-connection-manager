"""Quitting asks first when Confirm on exit is set and a console is open (#497)."""

from types import ModuleType, SimpleNamespace

import pytest


def make(app_module: ModuleType, monkeypatch: pytest.MonkeyPatch, answer: object, count: int):
    wmain = object.__new__(app_module.Wmain)
    wmain.count = count
    wmain.get_widget = lambda name: SimpleNamespace(get_size=lambda: (10, 20))
    calls: list[str] = []
    wmain.writeConfig = lambda: calls.append("write")
    wmain.end_sessions = lambda: calls.append("end")
    wmain.quit_application = lambda: calls.append("quit")
    asked: list[str] = []
    monkeypatch.setattr(app_module, "msgconfirm", lambda text: asked.append(text) or answer)
    return wmain, calls, asked


def test_cancel_keeps_gcm_running(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "CONFIRM_ON_EXIT", True)
    wmain, calls, asked = make(app_module, monkeypatch, app_module.Gtk.ResponseType.CANCEL, 2)
    wmain.request_quit()
    assert len(asked) == 1 and " 2 " in asked[0]
    assert calls == []
    assert wmain.on_wMain_delete_event(None) is True


def test_ok_quits(app_module, monkeypatch):
    monkeypatch.setattr(app_module.conf, "CONFIRM_ON_EXIT", True)
    wmain, calls, asked = make(app_module, monkeypatch, app_module.Gtk.ResponseType.OK, 2)
    wmain.request_quit()
    assert calls == ["write", "end", "quit"]
    assert wmain.on_wMain_delete_event(None) is None


@pytest.mark.parametrize(("confirm", "count"), [(False, 3), (True, 0)])
def test_no_question_when_not_needed(app_module, monkeypatch, confirm, count):
    monkeypatch.setattr(app_module.conf, "CONFIRM_ON_EXIT", confirm)
    wmain, calls, asked = make(app_module, monkeypatch, app_module.Gtk.ResponseType.CANCEL, count)
    wmain.request_quit()
    assert asked == []
    assert calls == ["write", "end", "quit"]
    assert wmain.on_wMain_delete_event(None) is None
