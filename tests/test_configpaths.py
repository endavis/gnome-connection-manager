"""Which directory GCM reads and writes its configuration in (#192).

The rule has three branches and the order between them is the whole point, so each is
tested on its own, and separately the property that makes the order hold: resolving
creates nothing. `app.py` used to mkdir the directory while it was being imported, and a
create that runs ahead of the choice satisfies the rule that looks for the directory --
``~/.config/gcm`` created eagerly would put ``~/.gcm`` out of reach for good.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import configpaths


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A home directory with neither configuration directory in it."""
    path = tmp_path / "home"
    path.mkdir()
    return path


def test_a_fresh_install_gets_the_xdg_directory(home: Path) -> None:
    chosen = configpaths.resolve(home, {})

    assert chosen.path == home / ".config" / "gcm"
    assert chosen.source == configpaths.FROM_DEFAULT
    assert not chosen.exists


def test_an_existing_pre_xdg_directory_is_kept(home: Path) -> None:
    """The fallback, and the reason nothing is copied: an install that has ~/.gcm goes on
    using it where it is."""
    (home / ".gcm").mkdir()

    chosen = configpaths.resolve(home, {})

    assert chosen.path == home / ".gcm"
    assert chosen.source == configpaths.FROM_LEGACY
    assert chosen.exists


def test_the_xdg_directory_wins_when_both_are_there(home: Path) -> None:
    """Someone who has moved their directory keeps an empty ~/.gcm behind more often than
    not, so the new location has to be the one that wins."""
    (home / ".gcm").mkdir()
    (home / ".config" / "gcm").mkdir(parents=True)

    chosen = configpaths.resolve(home, {})

    assert chosen.path == home / ".config" / "gcm"
    assert chosen.source == configpaths.FROM_XDG


def test_xdg_config_home_is_honoured(home: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "gcm").mkdir(parents=True)

    chosen = configpaths.resolve(home, {"XDG_CONFIG_HOME": str(elsewhere)})

    assert chosen.path == elsewhere / "gcm"
    assert chosen.source == configpaths.FROM_XDG


def test_xdg_config_home_is_honoured_for_a_fresh_install_too(home: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"

    chosen = configpaths.resolve(home, {"XDG_CONFIG_HOME": str(elsewhere)})

    assert chosen.path == elsewhere / "gcm"
    assert chosen.source == configpaths.FROM_DEFAULT


@pytest.mark.parametrize("value", ["", "   ", "relative/config", "./config"])
def test_an_unusable_xdg_config_home_falls_back_to_the_default(home: Path, value: str) -> None:
    """The specification says a value that is empty or relative is to be ignored. A
    relative one would put the configuration somewhere that depends on the directory GCM
    was started from, which is worse than not honouring the variable at all."""
    assert configpaths.config_home(home, {"XDG_CONFIG_HOME": value}) == home / ".config"


def test_an_unset_xdg_config_home_falls_back_to_the_default(home: Path) -> None:
    assert configpaths.config_home(home, {}) == home / ".config"


def test_resolving_creates_nothing(home: Path) -> None:
    """The property the three branches rest on. Creating the XDG directory here would make
    the pre-XDG branch unreachable on every later start."""
    before = sorted(home.iterdir())

    configpaths.resolve(home, {})
    configpaths.resolve(home, {"XDG_CONFIG_HOME": str(home / "config")})

    assert sorted(home.iterdir()) == before
    assert not (home / ".config").exists()


def test_a_file_where_the_directory_would_be_is_not_mistaken_for_it(home: Path) -> None:
    """`is_dir`, not `exists`: a stray file named .gcm would otherwise be chosen and every
    write would fail against it."""
    (home / ".gcm").write_text("not a directory")

    chosen = configpaths.resolve(home, {})

    assert chosen.path == home / ".config" / "gcm"
    assert chosen.source == configpaths.FROM_DEFAULT


def test_the_pre_xdg_location_is_reported_whichever_is_chosen(home: Path) -> None:
    """So a caller can name it without working it out again."""
    assert configpaths.resolve(home, {}).legacy == home / ".gcm"

    (home / ".gcm").mkdir()
    assert configpaths.resolve(home, {}).legacy == home / ".gcm"


def test_ensure_creates_the_directory_and_its_parents(home: Path) -> None:
    chosen = configpaths.resolve(home, {})

    assert configpaths.ensure(chosen.path) == chosen.path
    assert chosen.path.is_dir()


def test_ensure_is_content_with_a_directory_already_there(home: Path) -> None:
    (home / ".gcm").mkdir()
    chosen = configpaths.resolve(home, {})

    configpaths.ensure(chosen.path)

    assert chosen.path.is_dir()


# -- how app.py is wired to it -----------------------------------------------------


def _reimport(app_module, home: Path):
    """Import app again under the same gi stubs, after changing what is in `home`.

    The app_module fixture sets HOME and imports, so the only way to see the module read a
    directory that was already there is to put one there and import again.
    """
    del app_module  # taken for the gi stubs it installs, which stay in sys.modules
    sys.modules.pop("gnome_connection_manager.app", None)
    os.environ["HOME"] = str(home)
    return importlib.import_module("gnome_connection_manager.app")


def test_the_config_file_and_the_key_sit_in_the_chosen_directory(app_module) -> None:
    """The key is the passphrase for every stored password; it travels with the file it
    decrypts."""
    directory = Path(app_module.CONFIG_DIR)

    assert Path(app_module.CONFIG_FILE) == directory / "gcm.conf"
    assert Path(app_module.KEY_FILE) == directory / ".gcm.key"
    assert app_module.CONFIG_DIRECTORY.path == directory


def test_the_default_log_path_follows_the_chosen_directory(app_module) -> None:
    assert Path(app_module.conf.LOG_PATH) == Path(app_module.CONFIG_DIR) / "logs"


def test_a_fresh_home_is_pointed_at_the_xdg_directory(app_module) -> None:
    home = Path(os.environ["HOME"])

    assert Path(app_module.CONFIG_DIR) == home / ".config" / "gcm"
    assert app_module.CONFIG_DIRECTORY.source == configpaths.FROM_DEFAULT


def test_a_home_with_the_pre_xdg_directory_keeps_using_it(app_module, tmp_path: Path) -> None:
    home = tmp_path / "existing-home"
    (home / ".gcm").mkdir(parents=True)

    reimported = _reimport(app_module, home)

    assert Path(reimported.CONFIG_DIR) == home / ".gcm"
    assert reimported.CONFIG_DIRECTORY.source == configpaths.FROM_LEGACY
    assert Path(reimported.CONFIG_FILE) == home / ".gcm" / "gcm.conf"


def test_require_config_dir_creates_the_chosen_directory(app_module) -> None:
    directory = Path(app_module.CONFIG_DIR)
    assert not directory.exists()

    app_module.require_config_dir()

    assert directory.is_dir()


def test_require_config_dir_does_not_disturb_one_already_there(app_module, tmp_path: Path) -> None:
    home = tmp_path / "existing-home"
    (home / ".gcm").mkdir(parents=True)
    (home / ".gcm" / "gcm.conf").write_text("[options]\n")
    reimported = _reimport(app_module, home)

    reimported.require_config_dir()

    assert (home / ".gcm" / "gcm.conf").read_text() == "[options]\n"
    assert not (home / ".config").exists()


# Importing must create nothing, which is what keeps the choice above reachable, and it
# cannot be shown with the gi stub in place -- the stub is what an in-process import gets,
# and the property is about the real module body. HOME is a throwaway, so this can never
# touch a real ~/.gcm.
_IMPORT_SCRIPT = textwrap.dedent("""
    import os, sys
    os.environ["SHELL"] = "/bin/sh"
    home = sys.argv[1]
    import gi
    gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
    from gnome_connection_manager import app
    print(app.CONFIG_DIR)
    print(sorted(p.name for p in os.scandir(home)))
""")


def _import_under(
    home: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    environment = dict(os.environ, HOME=str(home))
    environment.pop("XDG_CONFIG_HOME", None)
    environment.update(extra_env or {})
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _IMPORT_SCRIPT, str(home)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=environment,
    )


def test_importing_the_app_creates_no_directory(tmp_path: Path) -> None:
    """The regression this change exists to allow (#118, #192). Before it, importing the
    module made ~/.gcm, so the choice could never see an empty home."""
    home = tmp_path / "untouched-home"
    home.mkdir()

    result = _import_under(home)

    assert result.returncode == 0, result.stderr[-2000:]
    chosen, listing = result.stdout.splitlines()[:2]
    assert chosen == str(home / ".config" / "gcm")
    assert listing == "[]", f"importing created {listing}"


def test_a_real_import_finds_an_existing_pre_xdg_directory(tmp_path: Path) -> None:
    home = tmp_path / "old-home"
    (home / ".gcm").mkdir(parents=True)

    result = _import_under(home)

    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.splitlines()[0] == str(home / ".gcm")


class RefusalDialog:
    """Records the dialog `require_config_dir` shows. Its methods are checked against the
    real Gtk.MessageDialog below, because conftest stubs all of gi and a fake is otherwise
    free to offer methods GTK has never had (#30, #41)."""

    shown: list = []

    def __init__(self, **kwargs):
        self.text = kwargs["text"]
        self.message_type = kwargs["message_type"]
        self.detail = None

    def format_secondary_text(self, text):
        self.detail = text

    def run(self):
        RefusalDialog.shown.append(self)

    def destroy(self):
        pass


def _unmakeable_home(tmp_path: Path) -> Path:
    """A home where the chosen directory cannot be created: ~/.config is a file."""
    home = tmp_path / "blocked-home"
    home.mkdir()
    (home / ".config").write_text("in the way")
    return home


def test_a_directory_that_cannot_be_created_refuses_on_stderr(
    app_module, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Without the directory nothing can be saved, and a window full of hosts that cannot
    be kept is the worse way to find that out. With no display there is nobody to click
    OK, so a dialog would be a hang."""
    home = _unmakeable_home(tmp_path)
    reimported = _reimport(app_module, home)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        reimported.require_config_dir()

    assert exit_info.value.code == 1
    said = capsys.readouterr().err
    assert "could not create its configuration directory" in said
    assert str(home / ".config" / "gcm") in said
    assert (home / ".config").read_text() == "in the way"


def test_a_directory_that_cannot_be_created_says_it_in_a_dialog(
    app_module, tmp_path: Path, monkeypatch
) -> None:
    home = _unmakeable_home(tmp_path)
    reimported = _reimport(app_module, home)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(RefusalDialog, "shown", [])
    monkeypatch.setattr(reimported.Gtk, "MessageDialog", RefusalDialog)

    with pytest.raises(SystemExit) as exit_info:
        reimported.require_config_dir()

    assert exit_info.value.code == 1
    [dialog] = RefusalDialog.shown
    assert "could not create its configuration directory" in dialog.text
    assert str(home / ".config" / "gcm") in dialog.detail


def test_the_refusal_dialog_fake_matches_real_gtk() -> None:
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for method in ("format_secondary_text", "run", "destroy"):
        assert hasattr(Gtk.MessageDialog, method), method


# Creating the directory is main()'s job, but nothing may *depend* on main() having run:
# both writers below report a failure through `msgbox`, and a modal dialog where nobody
# is there to click OK is a hang, not an error (#118). Measured before this was fixed: a
# real Wmain built in a throwaway HOME sat there until it was killed, which is how the
# real-GTK tests found it.


def test_writing_the_key_creates_the_directory_itself(app_module) -> None:
    directory = Path(app_module.CONFIG_DIR)
    assert not directory.exists()

    app_module.initialise_encyption_key()

    assert Path(app_module.KEY_FILE).exists()
    assert (Path(app_module.KEY_FILE).stat().st_mode & 0o777) == 0o600


def test_writing_the_config_creates_the_directory_itself(app_module, monkeypatch) -> None:
    directory = Path(app_module.CONFIG_DIR)
    monkeypatch.setattr(app_module, "groups", {})
    monkeypatch.setattr(app_module, "shortcuts", {})
    assert not directory.exists()

    wmain = object.__new__(app_module.Wmain)
    wmain.hpMain = types.SimpleNamespace(get_position=lambda: 333)
    wmain.wMain = types.SimpleNamespace(is_maximized=lambda: False)
    wmain.get_collapsed_nodes = lambda: []
    wmain.get_collapsed_folder_ids = lambda: []
    wmain.writeConfig()

    assert Path(app_module.CONFIG_FILE).exists()
