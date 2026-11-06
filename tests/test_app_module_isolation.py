"""app_module keeps the real GtkVnc and GdkX11 out of app.py (#528)."""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def leaked_modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, types.ModuleType]:
    """Modules a test on the same worker left in sys.modules, as an import of the real ones does.

    Listed before ``app_module`` in the test, so they are in place when it imports app.py.
    """
    leaked: dict[str, types.ModuleType] = {}
    for name in ("GtkVnc", "GdkX11"):
        module = types.ModuleType(f"gi.repository.{name}")
        monkeypatch.setitem(sys.modules, f"gi.repository.{name}", module)
        leaked[name] = module
    return leaked


def test_app_does_not_pick_up_a_gtkvnc_or_gdkx11_left_in_sys_modules(
    leaked_modules: dict[str, types.ModuleType], app_module
) -> None:
    assert app_module.GtkVnc is None
    assert app_module.GdkX11 is None
    assert app_module.TYPE_PAGES == {}
