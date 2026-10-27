"""RDP hosts opened in Windows Remote Desktop, mstsc.exe, under WSL (#283).

Preferences offers it where WSL's interop finds mstsc.exe. An RDP host's tab then runs
it with the host's address and an option for each RDP setting mstsc has one for. Windows
asks for the password in its own dialog, so GCM gives mstsc neither the user nor the
password.

The real mstsc.exe opens its windows on the Windows desktop, so no test here may reach
it. Every scenario that chooses it runs with a PATH of its own, without the folders WSL
adds from Windows, and a fake mstsc.exe first.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from gnome_connection_manager.utils import connections
from gnome_connection_manager.utils.hosts import Host

REPO = Path(__file__).resolve().parents[1]
FREERDP = connections.Programs(expect="/gcm/ssh.expect", username="localme")
WINDOWS = connections.Programs(expect="/gcm/ssh.expect", username="localme", rdp_client="mstsc")
MSTSC = "/mnt/c/WINDOWS/system32/mstsc.exe"
NO_FREERDP = "Neither xfreerdp3 nor xfreerdp was found. Install FreeRDP to open RDP hosts."


def rdp_host(address="win.example.test", port="3389", **settings):
    host = Host("Work", "build box", "", address, "CORP\\me", "not-a-password")
    host.type, host.port = "rdp", port
    host.extra_params = "/drive:shared,/home/me/shared /sound"
    host.type_settings = {f"rdp.{key}": value for key, value in settings.items()}
    return host


def installed(monkeypatch, *names):
    """Pretend that only `names` are found: mstsc.exe where WSL finds Windows' own, and
    anything else in /usr/bin."""
    places = {connections.WINDOWS_RDP_CLIENT: MSTSC}
    monkeypatch.setattr(
        connections.shutil,
        "which",
        lambda name: places.get(name, f"/usr/bin/{name}") if name in names else None,
    )


# -- what mstsc is given ------------------------------------------------------


def test_a_host_left_as_it_was_gives_mstsc_its_address_alone():
    """With no option, mstsc's own settings decide the rest: a window of the size they
    say, or full screen, resizing, scaling and what it shares."""
    assert connections.mstsc_arguments(rdp_host()) == ["/v:win.example.test:3389"]


@pytest.mark.parametrize(
    ("settings", "options"),
    [
        ({"display": "full-screen"}, ["/f"]),
        ({"display": "all-monitors"}, ["/f", "/multimon"]),
        ({"size": "1920x1080"}, ["/w:1920", "/h:1080"]),
        ({"size": " 1280 X 800 "}, ["/w:1280", "/h:800"]),
        # Full screen is the screen's size, as it is for FreeRDP.
        ({"display": "full-screen", "size": "1920x1080"}, ["/f"]),
        ({"display": "all-monitors", "size": "1920x1080"}, ["/f", "/multimon"]),
        # mstsc has no option for any of these, so its own settings decide them.
        ({"size": "80%"}, []),
        ({"size": "50%w"}, []),
        ({"resize": "False"}, []),
        ({"scale": "150"}, []),
        # What a hand edit left that the dialog would refuse is not passed on.
        ({"size": "199x200"}, []),
        ({"display": "fullscreen"}, []),
    ],
)
def test_each_setting_mstsc_has_an_option_for_gives_it(settings, options):
    assert connections.mstsc_arguments(rdp_host(**settings)) == [
        "/v:win.example.test:3389",
        *options,
    ]


@pytest.mark.parametrize(
    ("address", "port", "target"),
    [
        ("win.example.test", "3390", "/v:win.example.test:3390"),
        ("192.0.2.7", "3389", "/v:192.0.2.7:3389"),
        # mstsc reads the port after the last colon, so an IPv6 address is bracketed.
        ("2001:db8::7", "3389", "/v:[2001:db8::7]:3389"),
        ("win.example.test", "", "/v:win.example.test"),
    ],
)
def test_mstsc_is_given_the_address_and_the_port_as_one(address, port, target):
    assert connections.mstsc_arguments(rdp_host(address, port))[0] == target


def test_mstsc_is_never_given_the_user_the_password_or_the_extra_arguments(monkeypatch):
    """Windows asks for the user and the password in its own dialog, and the extra
    arguments are written for FreeRDP."""
    installed(monkeypatch, "mstsc.exe", "xfreerdp3")
    host = rdp_host(display="full-screen")

    command = connections.RDP.command(host, WINDOWS)

    assert command.argv == [MSTSC, "/v:win.example.test:3389", "/f"]
    assert command.environment is None


# -- which client -------------------------------------------------------------


def test_freerdp_unless_preferences_chose_windows_remote_desktop(monkeypatch):
    installed(monkeypatch, "mstsc.exe", "xfreerdp3")

    command = connections.RDP.command(rdp_host(), FREERDP)

    assert command.argv[:3] == ["/gcm/ssh.expect", "rdp", "xfreerdp3"]
    assert command.environment == {"GCM_PASSWORD": "not-a-password"}


def test_windows_remote_desktop_chosen_but_not_found_leaves_the_host_to_freerdp(monkeypatch):
    """A gcm.conf taken from WSL to a Linux desktop, or WSL with its interop turned off."""
    installed(monkeypatch, "xfreerdp3")

    command = connections.RDP.command(rdp_host(), WINDOWS)

    assert command.argv[:3] == ["/gcm/ssh.expect", "rdp", "xfreerdp3"]


@pytest.mark.parametrize(
    ("programs", "found", "problem"),
    [
        (WINDOWS, ("mstsc.exe",), None),
        (WINDOWS, ("mstsc.exe", "xfreerdp3"), None),
        (WINDOWS, ("xfreerdp",), None),
        (WINDOWS, (), NO_FREERDP),
        (FREERDP, ("mstsc.exe",), NO_FREERDP),
        (FREERDP, ("xfreerdp3",), None),
    ],
)
def test_an_rdp_host_needs_the_client_it_will_open_in(monkeypatch, programs, found, problem):
    installed(monkeypatch, *found)

    assert connections.RDP.missing(programs) == problem


def test_the_client_preferences_chose_reaches_each_spawn(app_module, monkeypatch):
    assert app_module.conf.RDP_CLIENT == "freerdp"
    assert app_module.connection_programs().rdp_client == "freerdp"

    monkeypatch.setattr(app_module.conf, "RDP_CLIENT", "mstsc")

    assert app_module.connection_programs().rdp_client == "mstsc"


# -- what the host dialog greys (#285) -----------------------------------------

IGNORED_BY_MSTSC = frozenset({"credentials", "arguments", "resize", "scale"})


@pytest.mark.parametrize(
    ("programs", "found", "ignored"),
    [
        (WINDOWS, ("mstsc.exe",), IGNORED_BY_MSTSC),
        (WINDOWS, ("mstsc.exe", "xfreerdp3"), IGNORED_BY_MSTSC),
        # FreeRDP opens the host, and uses every one of them.
        (WINDOWS, ("xfreerdp3",), frozenset()),
        (FREERDP, ("mstsc.exe", "xfreerdp3"), frozenset()),
    ],
)
def test_an_rdp_host_ignores_what_its_client_is_never_given(monkeypatch, programs, found, ignored):
    installed(monkeypatch, *found)

    assert connections.RDP.ignores(programs) == ignored


def test_what_windows_remote_desktop_ignores_changes_nothing_it_is_given(monkeypatch):
    """The dialog greys what mstsc's command is the same without, and nothing else, so
    an option mstsc is one day given for a setting cannot stay greyed."""
    installed(monkeypatch, "mstsc.exe")

    def argv(host):
        return connections.RDP.command(host, WINDOWS).argv

    someone_else = rdp_host()
    someone_else.user, someone_else.password = "CORP\\other", "another-password"
    other_arguments = rdp_host()
    other_arguments.extra_params = "/sound"
    unchanged = {
        name
        for name, host in {
            "credentials": someone_else,
            "arguments": other_arguments,
            "display": rdp_host(display="full-screen"),
            "resize": rdp_host(resize="False"),
            "size": rdp_host(size="1600x900"),
            "scale": rdp_host(scale="150"),
        }.items()
        if argv(host) == argv(rdp_host())
    }

    assert connections.RDP.ignores(WINDOWS) == unchanged == IGNORED_BY_MSTSC


def test_no_other_type_ignores_anything_whichever_client(monkeypatch):
    installed(monkeypatch, "mstsc.exe", "xfreerdp3")

    for kind in connections.CONNECTION_TYPES:
        if kind is not connections.RDP:
            assert kind.ignores(WINDOWS) == frozenset(), kind.id
            assert kind.ignores(FREERDP) == frozenset(), kind.id


# -- against real GTK ---------------------------------------------------------

_FAKE_MSTSC = r"""#!/bin/sh
printf 'mstsc:'; printf ' [%s]' "$@"; printf '\n'
"""

_FAKE_XFREERDP = r"""#!/bin/sh
printf 'xfreerdp3:'; printf ' [%s]' "$@"; printf '\n'
"""

_SCRIPT = r"""
import os, sys, tempfile, time
from pathlib import Path
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk, Vte
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
app.conf.AUTO_CLOSE_TAB = 0
shown_messages = []
app.msgbox = lambda text, *args, **kwargs: shown_messages.append(text)

def pump(until, what, limit=30):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        Gtk.main_iteration_do(False)
        if until():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for " + what)

def whole(v):
    text, _ = v.get_text_range_format(Vte.Format.TEXT, 0, 0, v.get_cursor_position()[1], 10000)
    return text or ""

def row(prefs, field):
    # The control Preferences drew for `field`, and the label beside it.
    controls = [child for child in prefs.tblGeneral.get_children() if getattr(child, "field", None) == field]
    labels = [child.get_text() for child in prefs.tblGeneral.get_children() if isinstance(child, Gtk.Label)]
    return controls, labels

def dialog_for(host):
    dialog = app.Whost()
    dialog.init("Work", host)
    return dialog

def greyed(dialog):
    # What the host dialog greys, of the fields an RDP host uses: Properties' by name, and
    # the RDP page's by setting.
    _page, controls = dialog.type_pages["rdp"]
    fields = {"user": dialog.txtUser, "password": dialog.txtPassword, "arguments": dialog.txtExtraParams}
    return sorted(name for name, widget in {**fields, **controls}.items() if not widget.get_sensitive())

def saved_host():
    app.groups.clear()
    app.wMain.loadConfig()
    [saved] = app.groups["Work"]
    return saved

def stored(host):
    # The host as GCM holds it, read back from gcm.conf, which is what the dialog is
    # given. A saved key and commands are text, where the Host below leaves them None.
    host.private_key, host.commands = "", ""
    app.groups.setdefault("Work", []).append(host)
    app.wMain.writeConfig()
    return saved_host()

app.wMain = app.Wmain(application=None)
nb = app.wMain.nbConsole
host = app.Host("Work", "build box", "", "win.example.test", "CORP\\me", "not-a-password")
host.type, host.port = "rdp", "3389"
mstsc = os.path.join(os.environ["GCM_TEST_BIN"], "mstsc.exe")
IGNORED = ["arguments", "password", "resize", "scale", "user"]

if scenario == "preferences-offers-windows-remote-desktop-where-mstsc-is-found":
    prefs = app.Wconfig()
    controls, labels = row(prefs, "conf.RDP_CLIENT")
    assert app._("RDP client") in labels, labels
    [combo] = controls
    offered = [(choice[1], choice[0]) for choice in combo.get_model()]
    assert offered == [("freerdp", "FreeRDP"), ("mstsc", "Windows Remote Desktop")], offered
    assert combo.get_active_id() == "freerdp"
    assert "password" in combo.get_tooltip_text(), combo.get_tooltip_text()
    combo.set_active_id("mstsc")
    prefs.on_okbutton1_clicked(None)
    assert app.conf.RDP_CLIENT == "mstsc", app.conf.RDP_CLIENT
    saved = Path(app.CONFIG_FILE).read_text()
    assert "rdp-client = mstsc\n" in saved, saved
    app.conf.RDP_CLIENT = "freerdp"
    app.wMain.loadConfig()
    assert app.conf.RDP_CLIENT == "mstsc", app.conf.RDP_CLIENT
    # And Preferences opens on the choice it saved.
    controls, _ = row(app.Wconfig(), "conf.RDP_CLIENT")
    assert controls[0].get_active_id() == "mstsc"
elif scenario == "preferences-offers-no-client-where-mstsc-is-not-found":
    prefs = app.Wconfig()
    controls, labels = row(prefs, "conf.RDP_CLIENT")
    assert controls == [] and app._("RDP client") not in labels, labels
    # Every other setting is still drawn.
    controls, _ = row(prefs, "conf.APP_TITLE")
    assert len(controls) == 1
elif scenario == "a-client-gcm-does-not-know-shows-as-freerdp":
    app.conf.RDP_CLIENT = "remmina"
    controls, _ = row(app.Wconfig(), "conf.RDP_CLIENT")
    assert controls[0].get_active_id() == "freerdp", controls[0].get_active_id()
elif scenario == "an-rdp-host-opens-in-windows-remote-desktop":
    app.conf.RDP_CLIENT = "mstsc"
    host.type_settings = {"rdp.display": "full-screen"}
    host.extra_params = "/sound"
    app.wMain.addTab(nb, host)
    v = app.page_terminal(nb.get_nth_page(nb.get_n_pages() - 1))
    assert v.command == (mstsc, [mstsc, "/v:win.example.test:3389", "/f"], None), v.command
    pump(lambda: "mstsc: [/v:win.example.test:3389] [/f]" in whole(v), "mstsc's arguments")
    assert "not-a-password" not in whole(v), whole(v)
    assert shown_messages == [], shown_messages
elif scenario == "without-mstsc-an-rdp-host-opens-in-freerdp":
    app.conf.RDP_CLIENT = "mstsc"
    host.password = ""
    app.wMain.addTab(nb, host)
    v = app.page_terminal(nb.get_nth_page(nb.get_n_pages() - 1))
    assert v.command[0] == "xfreerdp3", v.command
    pump(lambda: "xfreerdp3: [/v:win.example.test]" in whole(v), "FreeRDP's arguments")
    assert shown_messages == [], shown_messages
elif scenario == "the-dialog-greys-what-windows-remote-desktop-ignores":
    app.conf.RDP_CLIENT = "mstsc"
    host.extra_params = "/sound"
    host.type_settings = {"rdp.resize": "False", "rdp.size": "1600x900", "rdp.scale": "150"}
    dialog = dialog_for(stored(host))
    assert greyed(dialog) == IGNORED, greyed(dialog)
    # Greyed, not cleared: FreeRDP has them still, if the client changes back.
    texts = [dialog.txtUser.get_text(), dialog.txtPassword.get_text(), dialog.txtExtraParams.get_text()]
    assert texts == ["CORP\\me", "not-a-password", "/sound"], texts
    _page, controls = dialog.type_pages["rdp"]
    assert not controls["resize"].get_active() and controls["scale"].get_text() == "150"
    dialog.on_okbutton1_clicked(None)
    assert shown_messages == [], shown_messages
    saved = saved_host()
    assert (saved.user, saved.password, saved.extra_params) == ("CORP\\me", "not-a-password", "/sound")
    assert saved.type_settings == host.type_settings, saved.type_settings
    # Another type uses them, and RDP greys them again, still without clearing them. init()
    # fills them in after choosing the type, so only a change of type here would show it.
    dialog = dialog_for(saved)
    dialog.cmbType.set_active_id("telnet")
    assert [widget.get_sensitive() for widget in (dialog.txtUser, dialog.txtPassword, dialog.txtExtraParams)] == [True] * 3
    dialog.cmbType.set_active_id("rdp")
    assert greyed(dialog) == IGNORED, greyed(dialog)
    texts = [dialog.txtUser.get_text(), dialog.txtPassword.get_text(), dialog.txtExtraParams.get_text()]
    assert texts == ["CORP\\me", "not-a-password", "/sound"], texts
elif scenario in ("freerdp-chosen-greys-nothing", "windows-remote-desktop-not-found-greys-nothing"):
    app.conf.RDP_CLIENT = "freerdp" if scenario.startswith("freerdp") else "mstsc"
    host.type_settings = {"rdp.resize": "False", "rdp.scale": "150"}
    dialog = dialog_for(stored(host))
    assert greyed(dialog) == [], greyed(dialog)
elif scenario == "a-greyed-setting-left-wrong-by-hand-does-not-block-ok":
    host.type_settings = {"rdp.scale": "abc"}
    host = stored(host)
    # FreeRDP uses it, so the dialog refuses it, as before.
    dialog = dialog_for(host)
    dialog.on_okbutton1_clicked(None)
    expected = app._("The desktop scale is a percentage from 100 to 500, such as 150.")
    assert shown_messages == [expected], shown_messages
    dialog.get_widget("wHost").destroy()
    shown_messages.clear()
    # Windows Remote Desktop leaves it unused, and greyed, it could not be corrected.
    app.conf.RDP_CLIENT = "mstsc"
    dialog = dialog_for(host)
    assert "scale" in greyed(dialog), greyed(dialog)
    dialog.on_okbutton1_clicked(None)
    assert shown_messages == [], shown_messages
    assert saved_host().type_settings == {"rdp.scale": "abc"}
else:
    raise SystemExit("no scenario " + scenario)
print("OK")
"""


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)
@pytest.mark.parametrize(
    ("scenario", "programs"),
    [
        ("preferences-offers-windows-remote-desktop-where-mstsc-is-found", ("mstsc.exe",)),
        ("preferences-offers-no-client-where-mstsc-is-not-found", ()),
        ("a-client-gcm-does-not-know-shows-as-freerdp", ("mstsc.exe",)),
        ("an-rdp-host-opens-in-windows-remote-desktop", ("mstsc.exe", "xfreerdp3")),
        ("without-mstsc-an-rdp-host-opens-in-freerdp", ("xfreerdp3",)),
        ("the-dialog-greys-what-windows-remote-desktop-ignores", ("mstsc.exe",)),
        ("freerdp-chosen-greys-nothing", ("mstsc.exe",)),
        ("windows-remote-desktop-not-found-greys-nothing", ()),
        ("a-greyed-setting-left-wrong-by-hand-does-not-block-ok", ("mstsc.exe",)),
    ],
)
def test_windows_remote_desktop_against_real_gtk(tmp_path, scenario, programs):
    pytest.importorskip("gi", reason="PyGObject not available")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {"mstsc.exe": _FAKE_MSTSC, "xfreerdp3": _FAKE_XFREERDP}
    for name in programs:
        fake = bin_dir / name
        fake.write_text(fakes[name])
        fake.chmod(0o755)
    # Never the real mstsc.exe: WSL adds Windows' folders to PATH under /mnt.
    path = [str(bin_dir)] + [
        folder for folder in os.environ["PATH"].split(os.pathsep) if not folder.startswith("/mnt/")
    ]
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PATH": os.pathsep.join(path), "GCM_TEST_BIN": str(bin_dir)},
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert "OK" in result.stdout
