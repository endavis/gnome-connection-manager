"""A host's files outside its console, in GCM (#267).

The server tree's menu offers an SSH host's files. Open in File Manager reaches the
application GIO names for folders, or a file manager on PATH, and never a browser. Mount with
SSHFS mounts a host under ~/mnt, and Unmount SSHFS unmounts it.

The decisions are tested in tests/test_remotefiles.py. Here GCM's side runs, first with the
toolkit stubbed, then against real GTK and GIO, and real sshfs mounts through a real ssh and
sshd. That sshd runs as this user on 127.0.0.1, with keys and a configuration of its own,
and ssh reads only a configuration of the test's, so nothing in ~/.ssh is read or written.
An sshd not run as root cannot check a password. So the mount a stored password makes is
shown through a fake ssh, which asks the askpass helper as ssh does. That ssh asks it is
shown against the real sshd, which logs the password it was sent.
"""

from __future__ import annotations

import os
import pwd
import shutil
import socket
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from gnome_connection_manager.utils import placeholders, remotefiles
from tests.test_connections import glib_complaints
from tests.test_console_window import _private_display
from tests.test_wmain import make_host, make_wmain_for_tree, make_wmain_with_host

REPO = Path(__file__).resolve().parents[1]


class Item:
    """A tree menu item, as prepare_files_items uses one. Gtk.MenuItem has each (below)."""

    def __init__(self):
        self.visible = True

    def set_visible(self, visible):
        self.visible = visible

    def get_visible(self):
        return self.visible


def test_the_menu_item_fake_matches_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("set_visible", "get_visible"):
        assert hasattr(Item, name), f"fake is missing {name}"
        assert hasattr(Gtk.MenuItem, name), f"Gtk.MenuItem has no {name}"


def offered(wmain, host):
    """Which of Open in File Manager, Mount with SSHFS and Unmount SSHFS the tree's menu
    shows for `host`."""
    menu = wmain.popupMenuFolder = types.SimpleNamespace(
        mnuOpenFiles=Item(), mnuMount=Item(), mnuUnmount=Item()
    )
    wmain.prepare_files_items(host)
    return menu.mnuOpenFiles.visible, menu.mnuMount.visible, menu.mnuUnmount.visible


def mount_table(app_module, monkeypatch, *lines):
    monkeypatch.setattr(app_module, "read_mount_table", lambda: "".join(lines))


def mounted_line(folder, kind="fuse.sshfs", source="netops@router.example.com:"):
    escaped = str(folder).replace(" ", "\\040")
    return f"228 82 0:78 / {escaped} rw,nosuid,nodev,relatime - {kind} {source} rw\n"


def router_folder():
    return Path(os.environ["HOME"], "mnt", "router")


def test_an_ssh_hosts_menu_offers_its_files(app_module, monkeypatch):
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line("/elsewhere"))

    assert offered(wmain, host) == (True, True, False)


def test_while_that_host_is_mounted_there_it_offers_unmount(app_module, monkeypatch):
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    assert offered(wmain, host) == (True, False, True)


@pytest.mark.parametrize(
    "line",
    [
        mounted_line("FOLDER", source="netops@other.example:"),
        mounted_line("FOLDER", kind="tmpfs", source="netops@router.example.com:"),
        mounted_line("FOLDER/below"),
    ],
)
def test_another_mount_there_is_not_that_hosts(app_module, monkeypatch, line):
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, line.replace("FOLDER", str(router_folder())))

    assert offered(wmain, host) == (True, True, False)


@pytest.mark.parametrize("ctype", ["telnet", "rdp", "vnc", "web", "command", "local"])
def test_no_other_types_host_is_offered_its_files(app_module, monkeypatch, ctype):
    host = make_host(app_module)
    host.type = ctype
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    assert offered(wmain, host) == (False, False, False)


def test_an_ssh_host_with_no_address_opens_a_local_shell_and_has_no_files(app_module, monkeypatch):
    host = make_host(app_module)
    host.host = ""
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch)

    assert offered(wmain, host) == (False, False, False)


def test_a_folder_or_blank_space_offers_no_files(app_module, monkeypatch):
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)

    assert offered(wmain, None) == (False, False, False)


def test_open_in_file_manager_is_given_the_hosts_address(app_module, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(app_module, "open_in_file_manager", opened.append)
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)

    wmain.open_selected_files()

    assert opened == ["sftp://netops@router.example.com:2200/"]


def test_a_host_with_no_user_is_opened_as_the_local_one(app_module, monkeypatch):
    """As its console connects."""
    opened: list[str] = []
    monkeypatch.setattr(app_module, "open_in_file_manager", opened.append)
    monkeypatch.setattr(app_module, "get_username", lambda: "localme")
    host = make_host(app_module)
    host.user, host.port = "", "22"
    wmain, _iter = make_wmain_with_host(app_module, host)

    wmain.open_selected_files()

    assert opened == ["sftp://localme@router.example.com/"]


def test_another_types_host_is_neither_opened_nor_mounted(app_module, monkeypatch):
    opened: list[str] = []
    toggled: list[tuple] = []
    monkeypatch.setattr(app_module, "open_in_file_manager", opened.append)
    host = make_host(app_module)
    host.type = "telnet"
    wmain, _iter = make_wmain_with_host(app_module, host)
    wmain.mount_files = lambda *args: toggled.append(args)
    wmain.unmount_files = lambda *args: toggled.append(args)
    mount_table(app_module, monkeypatch)

    wmain.open_selected_files()
    wmain.mount_selected_files()
    wmain.unmount_selected_files()

    assert opened == [] and toggled == []


def said(app_module, monkeypatch):
    """What GCM says, each as ("info", text) through msginfo, for what worked or needed
    nothing doing, or ("error", text) through msgbox, which draws an error."""
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(app_module, "msgbox", lambda text: shown.append(("error", text)))
    monkeypatch.setattr(app_module, "msginfo", lambda text: shown.append(("info", text)))
    return shown


class Dialog:
    """Gtk.MessageDialog, as msgbox and msginfo use one. The real class has each (below)."""

    made: list = []

    def __init__(self, **properties):
        self.properties = properties
        Dialog.made.append(self)

    def set_icon_from_file(self, path):
        pass

    def run(self):
        return 0

    def destroy(self):
        pass


def test_the_dialog_fake_matches_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    for name in ("set_icon_from_file", "run", "destroy"):
        assert hasattr(Dialog, name), f"fake is missing {name}"
        assert hasattr(Gtk.MessageDialog, name), f"Gtk.MessageDialog has no {name}"


@pytest.mark.parametrize(("helper", "kind"), [("msginfo", "INFO"), ("msgbox", "ERROR")])
def test_what_worked_is_drawn_as_information_and_a_failure_as_an_error(
    app_module, monkeypatch, helper, kind
):
    """Measured with the Yaru theme, GTK draws a message's type as its icon: a no-entry
    sign for an error, which a mount that worked was drawn with."""
    monkeypatch.setattr(Dialog, "made", [])
    monkeypatch.setattr(app_module.Gtk, "MessageDialog", Dialog)

    getattr(app_module, helper)("Unmounted router from /home/netops/mnt/router.")

    [dialog] = Dialog.made
    assert dialog.properties["message_type"] == getattr(app_module.Gtk.MessageType, kind)
    assert dialog.properties["text"] == "Unmounted router from /home/netops/mnt/router."


def chosen(app_module, monkeypatch, action, *lines, name="router"):
    """Mount with SSHFS or Unmount SSHFS chosen for the selected host, called `name`, with
    `lines` in the mount table: what GCM went on to do, and what it said."""
    shown = said(app_module, monkeypatch)
    calls: list[tuple] = []
    host = make_host(app_module)
    host.name = name
    wmain, _iter = make_wmain_with_host(app_module, host)
    wmain.mount_files = lambda *args: calls.append(("mount", *args))
    wmain.unmount_files = lambda *args: calls.append(("unmount", *args))
    mount_table(app_module, monkeypatch, *lines)
    getattr(wmain, action)()
    return host, calls, shown


def test_mount_with_sshfs_mounts_at_mnt_and_the_hosts_name(app_module, monkeypatch):
    host, calls, shown = chosen(app_module, monkeypatch, "mount_selected_files")

    assert calls == [("mount", host, router_folder())] and shown == []


def test_mount_with_sshfs_says_so_while_that_host_is_mounted(app_module, monkeypatch):
    """As from the Servers menu, which offers it whatever the host's state."""
    line = mounted_line(router_folder())
    _host, calls, shown = chosen(app_module, monkeypatch, "mount_selected_files", line)

    assert calls == []
    assert shown == [("info", f"router is mounted at {router_folder()} already.")]


def test_something_else_mounted_there_is_left_alone_and_named(app_module, monkeypatch):
    line = mounted_line(router_folder(), kind="tmpfs", source="scratch")
    _host, calls, shown = chosen(app_module, monkeypatch, "mount_selected_files", line)

    assert calls == []
    assert shown == [("error", f"Something else is mounted at {router_folder()}: scratch")]


def test_unmount_sshfs_unmounts_that_folder(app_module, monkeypatch):
    line = mounted_line(router_folder())
    _host, calls, shown = chosen(app_module, monkeypatch, "unmount_selected_files", line)

    assert calls == [("unmount", "router", router_folder())] and shown == []


@pytest.mark.parametrize(
    "lines",
    [(), (mounted_line("FOLDER", kind="tmpfs", source="scratch"),)],
    ids=["nothing-there", "something-else-there"],
)
def test_unmount_sshfs_unmounts_nothing_but_that_host(app_module, monkeypatch, lines):
    lines = tuple(line.replace("FOLDER", str(router_folder())) for line in lines)
    _host, calls, shown = chosen(app_module, monkeypatch, "unmount_selected_files", *lines)

    assert calls == []
    assert shown == [("info", f"router is not mounted at {router_folder()}.")]


def test_a_host_renamed_while_mounted_is_found_where_its_old_name_put_it(app_module, monkeypatch):
    host = make_host(app_module)
    host.name = "router-a"
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    assert offered(wmain, host) == (True, False, True)
    assert wmain.files_mount(host) == router_folder()


def test_mount_with_sshfs_does_not_mount_a_renamed_host_twice(app_module, monkeypatch):
    line = mounted_line(router_folder())
    _host, calls, shown = chosen(
        app_module, monkeypatch, "mount_selected_files", line, name="router-a"
    )

    assert calls == []
    assert shown == [("info", f"router-a is mounted at {router_folder()} already.")]


def test_unmount_sshfs_unmounts_a_renamed_host_from_where_it_is(app_module, monkeypatch):
    line = mounted_line(router_folder())
    _host, calls, shown = chosen(
        app_module, monkeypatch, "unmount_selected_files", line, name="router-a"
    )

    assert calls == [("unmount", "router-a", router_folder())] and shown == []


def test_a_mount_either_of_two_hosts_could_have_made_is_neithers(app_module, monkeypatch):
    """Two hosts at one address with one user, on two ports, as behind one gateway: the
    mount table names no port, so a mount where neither's name puts it is left alone."""
    host = make_host(app_module)
    host.name = "router-1"
    twin = make_host(app_module)
    twin.name, twin.port = "router-2", "2201"
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host, twin]})
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    assert offered(wmain, host) == (True, True, False)
    assert offered(wmain, twin) == (True, True, False)


def test_a_host_whose_files_do_not_open_never_shares_a_mount(app_module, monkeypatch):
    """A device in the tree twice, over SSH and over telnet: only the SSH host's files
    open, so the renamed SSH host is still found, and the telnet host never is."""
    host = make_host(app_module)
    host.name = "router-a"
    console = make_host(app_module)
    console.name, console.type = "router-telnet", "telnet"
    monkeypatch.setattr(app_module, "groups", {"ops/prod": [host, console]})
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    assert wmain.find_mounts()[1] == {host: router_folder()}


def test_a_mnt_that_is_a_link_is_found_where_it_leads(app_module, monkeypatch):
    """Measured with sshfs 3.7.3, a mount made through a link is listed at the folder the
    link leads to."""
    home = Path(os.environ["HOME"])
    (home / "elsewhere").mkdir()
    (home / "mnt").symlink_to(home / "elsewhere")
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)
    mount_table(app_module, monkeypatch, mounted_line(home / "elsewhere" / "router"))

    assert offered(wmain, host) == (True, False, True)
    assert wmain.files_mount(host) == router_folder()


def test_something_else_mounted_through_a_link_is_named(app_module, monkeypatch):
    home = Path(os.environ["HOME"])
    (home / "elsewhere").mkdir()
    (home / "mnt").symlink_to(home / "elsewhere")
    line = mounted_line(home / "elsewhere" / "router", kind="tmpfs", source="scratch")
    _host, calls, shown = chosen(app_module, monkeypatch, "mount_selected_files", line)

    assert calls == []
    assert shown == [("error", f"Something else is mounted at {router_folder()}: scratch")]


def test_a_host_still_being_mounted_is_not_yet_mounted(app_module, monkeypatch):
    """sshfs mounts before it connects, measured, so the mount table has the host while
    it may yet fail. Choosing Mount again meanwhile does nothing."""
    shown = said(app_module, monkeypatch)
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)
    wmain.mounting = frozenset({router_folder()})
    calls: list = []
    wmain.mount_files = lambda *args: calls.append(args)
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    assert offered(wmain, host) == (True, True, False)
    assert wmain.find_mounts() == ({}, {})
    wmain.mount_selected_files()
    assert calls == [] and shown == []


# -- Open in File Manager ------------------------------------------------------------------


class LaunchError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def file_managers(app_module, monkeypatch, default=None, installed=()):
    asked: list[tuple] = []
    shown: list[str] = []
    ran: list[tuple] = []
    monkeypatch.setattr(
        app_module.Gio,
        "AppInfo",
        types.SimpleNamespace(
            get_default_for_type=lambda kind, uris: asked.append((kind, uris)) or default
        ),
    )
    monkeypatch.setattr(app_module.GLib, "Error", LaunchError)
    monkeypatch.setattr(app_module, "msgbox", shown.append)
    monkeypatch.setattr(app_module, "open_with", lambda argv, target: ran.append((argv, target)))
    monkeypatch.setattr(
        app_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    return asked, shown, ran


def test_the_default_application_for_folders_opens_the_address(app_module, monkeypatch):
    launched = []
    default = types.SimpleNamespace(launch_uris=lambda uris, context: launched.append(uris))
    asked, shown, ran = file_managers(app_module, monkeypatch, default, installed=("thunar",))

    app_module.open_in_file_manager("sftp://eric@files.example/")

    assert asked == [("inode/directory", True)]
    assert launched == [["sftp://eric@files.example/"]]
    assert ran == [] and shown == []


def test_a_default_that_fails_to_start_is_reported(app_module, monkeypatch):
    def refuse(uris, context):
        raise LaunchError("Failed to execute child process")

    default = types.SimpleNamespace(launch_uris=refuse)
    _asked, shown, ran = file_managers(app_module, monkeypatch, default)

    app_module.open_in_file_manager("sftp://eric@files.example/")

    assert shown == ["Could not open sftp://eric@files.example/: Failed to execute child process"]
    assert ran == []


def test_with_no_default_the_first_file_manager_on_path_opens_it(app_module, monkeypatch):
    _asked, shown, ran = file_managers(app_module, monkeypatch, installed=("caja", "dolphin"))

    app_module.open_in_file_manager("sftp://eric@files.example/")

    assert ran == [
        (
            ["/usr/bin/caja", "--no-desktop", "sftp://eric@files.example/"],
            "sftp://eric@files.example/",
        )
    ]
    assert shown == []


def test_with_no_file_manager_at_all_it_says_so_and_opens_nothing(app_module, monkeypatch):
    _asked, shown, ran = file_managers(app_module, monkeypatch)

    app_module.open_in_file_manager("sftp://eric@files.example/")

    assert ran == []
    assert len(shown) == 1
    assert shown[0].startswith("No file manager was found to open sftp://eric@files.example/.")


# -- Mount with SSHFS, and Unmount SSHFS --------------------------------------------------


class Spawned:
    """GLib.spawn_async and child_watch_add, recording a spawn and handing back the end
    of a pipe the test writes the child's stderr into."""

    def __init__(self, app_module, monkeypatch, fail=None):
        self.calls, self.watches, self.pipes = [], [], []
        self.fail = fail
        monkeypatch.setattr(app_module.GLib, "spawn_async", self.spawn_async)
        monkeypatch.setattr(app_module.GLib, "child_watch_add", self.child_watch_add)
        monkeypatch.setattr(app_module.GLib, "spawn_close_pid", lambda pid: None)
        monkeypatch.setattr(app_module.GLib, "Error", LaunchError)
        monkeypatch.setattr(
            app_module.GLib,
            "SpawnFlags",
            types.SimpleNamespace(
                SEARCH_PATH=1, DO_NOT_REAP_CHILD=2, STDIN_FROM_DEV_NULL=4, STDOUT_TO_DEV_NULL=8
            ),
        )

    def spawn_async(self, argv, **kwargs):
        if self.fail:
            raise LaunchError(self.fail)
        self.calls.append((argv, kwargs))
        read, write = os.pipe()
        self.pipes.append(write)
        return 4242, None, None, read

    def child_watch_add(self, priority, pid, callback):
        self.watches.append((pid, callback))

    def exit(self, code, stderr="", which=-1):
        """End a child, having written `stderr`: the last one started, or `which`."""
        write = self.pipes.pop(which)
        os.write(write, stderr.encode())
        os.close(write)
        pid, callback = self.watches.pop(which)
        callback(pid, code << 8)

    def environment(self):
        return dict(entry.split("=", 1) for entry in self.calls[0][1]["envp"])


def count_refreshes(wmain):
    """Count each time the tree's marks and Servers ▸ Mounted are brought up to date."""
    wmain.refreshes = 0

    def show_mounts():
        wmain.refreshes += 1

    wmain.show_mounts = show_mounts


def mounting(app_module, monkeypatch, tmp_path, installed=("sshfs",), fail=None):
    shown = said(app_module, monkeypatch)
    monkeypatch.setattr(
        app_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    runtime = tmp_path / "run"
    monkeypatch.setattr(app_module.GLib, "get_user_runtime_dir", lambda: str(runtime))
    host = make_host(app_module)
    wmain, _iter = make_wmain_with_host(app_module, host)
    count_refreshes(wmain)
    spawned = Spawned(app_module, monkeypatch, fail)
    return host, wmain, spawned, shown, runtime / "gcm" / "sshfs-router.log"


def test_mounting_runs_sshfs_as_a_daemon_with_the_password_in_its_environment(
    app_module, monkeypatch, tmp_path
):
    host, wmain, spawned, shown, log = mounting(app_module, monkeypatch, tmp_path)
    folder = router_folder()

    wmain.mount_files(host, folder)

    argv, options = spawned.calls[0]
    assert argv == remotefiles.sshfs_command(
        "/usr/bin/sshfs",
        "router.example.com",
        "netops",
        "2200",
        "/home/netops/.ssh/id_rsa",
        folder,
        log,
    )
    environment = spawned.environment()
    assert environment["SSH_ASKPASS"] == app_module.ASKPASS_COMMAND
    assert environment["SSH_ASKPASS_REQUIRE"] == "force"
    assert environment[placeholders.PASSWORD_VARIABLE] == "secret"
    assert not any("secret" in argument for argument in argv)
    # In a session of its own, so its terminal closing cannot end the mount.
    assert options["child_setup"] is os.setsid
    assert options["standard_error"] is True
    assert folder.is_dir() and log.read_text() == ""
    assert wmain.mounting == {folder}

    assert wmain.refreshes == 0
    spawned.exit(0)

    assert shown == [("info", f"Mounted router at {folder}.")]
    assert wmain.mounting == set()
    # Marked mounted, now that sshfs has connected.
    assert wmain.refreshes == 1
    # Kept: the host is mounted there now.
    assert folder.is_dir()


def test_with_no_stored_password_none_reaches_ssh(app_module, monkeypatch, tmp_path):
    """Not even one GCM was started with."""
    monkeypatch.setenv(placeholders.PASSWORD_VARIABLE, "inherited")
    host, wmain, spawned, _shown, _log = mounting(app_module, monkeypatch, tmp_path)
    host.password = ""

    wmain.mount_files(host, router_folder())

    assert placeholders.PASSWORD_VARIABLE not in spawned.environment()


def test_a_failed_mount_says_why_in_ssh_s_words(app_module, monkeypatch, tmp_path):
    host, wmain, spawned, shown, log = mounting(app_module, monkeypatch, tmp_path)
    folder = router_folder()
    wmain.mount_files(host, folder)

    log.write_text("Host key verification failed.\n")
    spawned.exit(1, "read: Connection reset by peer\n")

    assert shown == [
        ("error", f"Could not mount router at {folder}: Host key verification failed.")
    ]
    assert wmain.mounting == set()
    # Removed again, though not ~/mnt: one for every host that failed would pile up.
    assert not folder.exists() and folder.parent.is_dir()


def test_a_failed_mount_keeps_a_folder_that_holds_anything(app_module, monkeypatch, tmp_path):
    """Measured, sshfs mounts over a folder that holds files, and rmdir refuses one."""
    host, wmain, spawned, _shown, _log = mounting(app_module, monkeypatch, tmp_path)
    folder = router_folder()
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("mine\n")

    wmain.mount_files(host, folder)
    spawned.exit(1)

    assert (folder / "notes.txt").read_text() == "mine\n"


def test_without_ssh_s_words_sshfs_s_own_are_given_or_its_status(app_module, monkeypatch, tmp_path):
    host, wmain, spawned, shown, _log = mounting(app_module, monkeypatch, tmp_path)
    folder = router_folder()
    wmain.mount_files(host, folder)
    spawned.exit(1, "fuse: bad mount point\n")

    second = Spawned(app_module, monkeypatch)
    wmain.mount_files(host, folder)
    second.exit(3)

    assert shown == [
        ("error", f"Could not mount router at {folder}: fuse: bad mount point"),
        ("error", f"Could not mount router at {folder}: sshfs exited with status 3"),
    ]


def test_a_user_ssh_would_read_as_an_option_is_not_mounted(app_module, monkeypatch, tmp_path):
    """It would run the command: measured, sshfs hands ssh such a source as it is. An
    address so made comes after the user, local or the host's, and ssh refuses it."""
    host, wmain, spawned, shown, _log = mounting(app_module, monkeypatch, tmp_path)
    host.user = "-oProxyCommand=touch x"

    wmain.mount_files(host, router_folder())

    assert spawned.calls == [] and not router_folder().exists()
    assert shown == [
        (
            "error",
            f"Could not mount router at {router_folder()}: its user begins with -, "
            "which ssh would read as an option.",
        )
    ]


def test_a_second_mount_while_one_is_under_way_does_nothing(app_module, monkeypatch, tmp_path):
    host, wmain, spawned, shown, _log = mounting(app_module, monkeypatch, tmp_path)

    wmain.mount_files(host, router_folder())
    wmain.mount_files(host, router_folder())

    assert len(spawned.calls) == 1 and shown == []


def test_without_sshfs_it_says_so(app_module, monkeypatch, tmp_path):
    host, wmain, spawned, shown, _log = mounting(app_module, monkeypatch, tmp_path, installed=())

    wmain.mount_files(host, router_folder())

    assert spawned.calls == []
    assert shown == [("error", "Mounting a host needs sshfs, which is not installed.")]


def test_sshfs_failing_to_start_is_reported(app_module, monkeypatch, tmp_path):
    host, wmain, _spawned, shown, _log = mounting(
        app_module, monkeypatch, tmp_path, fail="Failed to execute child process"
    )

    wmain.mount_files(host, router_folder())

    assert shown == [
        ("error", f"Could not mount router at {router_folder()}: Failed to execute child process")
    ]
    assert wmain.mounting == frozenset()
    assert not router_folder().exists()


def test_a_runtime_folder_with_whitespace_leaves_ssh_no_log(app_module, monkeypatch, tmp_path):
    """The mount still runs, with sshfs's own words for a failure. And no log goes anywhere
    shared, such as /tmp, where another user could put a link where it goes, for GCM to
    empty the file the link names."""
    host, wmain, spawned, shown, _log = mounting(app_module, monkeypatch, tmp_path)
    monkeypatch.setattr(app_module.GLib, "get_user_runtime_dir", lambda: str(tmp_path / "a b"))
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(app_module.tempfile, "gettempdir", lambda: str(shared))

    wmain.mount_files(host, router_folder())

    assert not any("ssh_command" in argument for argument in spawned.calls[0][0])
    assert list(shared.iterdir()) == [] and shown == []


def test_a_log_that_cannot_be_made_leaves_the_mount_to_run(app_module, monkeypatch, tmp_path):
    host, wmain, spawned, shown, _log = mounting(app_module, monkeypatch, tmp_path)
    taken = tmp_path / "taken"
    taken.write_text("")
    monkeypatch.setattr(app_module.GLib, "get_user_runtime_dir", lambda: str(taken))

    wmain.mount_files(host, router_folder())

    assert len(spawned.calls) == 1 and shown == []
    assert not any("ssh_command" in argument for argument in spawned.calls[0][0])


def unmounting(app_module, monkeypatch, installed):
    shown = said(app_module, monkeypatch)
    monkeypatch.setattr(
        app_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    wmain = object.__new__(app_module.Wmain)
    count_refreshes(wmain)
    return make_host(app_module), wmain, Spawned(app_module, monkeypatch), shown


@pytest.mark.parametrize(
    ("installed", "program"),
    [
        (("fusermount3", "fusermount"), "/usr/bin/fusermount3"),
        (("fusermount",), "/usr/bin/fusermount"),
    ],
)
def test_unmounting_uses_fuse_3s_fusermount_or_else_fuse_2s(
    app_module, monkeypatch, installed, program
):
    host, wmain, spawned, shown = unmounting(app_module, monkeypatch, installed)

    wmain.unmount_files(host.name, router_folder())
    spawned.exit(0)

    assert spawned.calls[0][0] == [program, "-u", str(router_folder())]
    # Said once it is done, as mounting says so, and no longer marked mounted.
    assert shown == [("info", f"Unmounted router from {router_folder()}.")]
    assert wmain.refreshes == 1


def test_unmounting_removes_the_hosts_folder(app_module, monkeypatch):
    """So that one is not left in ~/mnt for every host ever mounted. ~/mnt stays."""
    host, wmain, spawned, _shown = unmounting(app_module, monkeypatch, ("fusermount3",))
    router_folder().mkdir(parents=True)

    wmain.unmount_files(host.name, router_folder())
    spawned.exit(0)

    assert not router_folder().exists() and router_folder().parent.is_dir()


def test_unmounting_keeps_a_folder_that_holds_anything(app_module, monkeypatch):
    """What the mount hid in the folder is there again, and stays, folder and all."""
    host, wmain, spawned, shown = unmounting(app_module, monkeypatch, ("fusermount3",))
    router_folder().mkdir(parents=True)
    (router_folder() / "notes.txt").write_text("mine\n")

    wmain.unmount_files(host.name, router_folder())
    spawned.exit(0)

    assert (router_folder() / "notes.txt").read_text() == "mine\n"
    assert shown == [("info", f"Unmounted router from {router_folder()}.")]


def test_a_failed_unmount_says_why(app_module, monkeypatch):
    host, wmain, spawned, shown = unmounting(app_module, monkeypatch, ("fusermount3",))
    router_folder().mkdir(parents=True)

    wmain.unmount_files(host.name, router_folder())
    spawned.exit(1, f"fusermount3: failed to unmount {router_folder()}: Device or resource busy\n")

    assert shown == [
        (
            "error",
            f"Could not unmount {router_folder()}: fusermount3: failed to unmount "
            f"{router_folder()}: Device or resource busy",
        )
    ]
    # Still mounted there, so kept.
    assert router_folder().is_dir()


def test_without_fusermount_it_says_so(app_module, monkeypatch):
    host, wmain, spawned, shown = unmounting(app_module, monkeypatch, ())

    wmain.unmount_files(host.name, router_folder())

    assert spawned.calls == []
    assert shown == [("error", "Unmounting needs fusermount, which is not installed.")]


# -- what is mounted: the tree's marks, and Servers ▸ Mounted -----------------------------


class MenuModel:
    """Gio.Menu, as list_mounts fills one. The real class has each (below)."""

    def __init__(self):
        self.items: list = []
        self.emptied = 0

    def remove_all(self):
        self.items.clear()
        self.emptied += 1

    def append_item(self, item):
        self.items.append((item.label, item.action, item.target))

    def append(self, label, action):
        self.items.append((label, action, None))


class MenuEntry:
    """Gio.MenuItem, as list_mounts makes one."""

    def __init__(self, label, action):
        self.label, self.action, self.target = label, action, None

    @classmethod
    def new(cls, label, action):
        return cls(label, action)

    def set_action_and_target_value(self, action, target):
        self.action, self.target = action, target


class Action:
    """Gio.SimpleAction, as list_mounts enables one."""

    def __init__(self):
        self.enabled = True

    def set_enabled(self, enabled):
        self.enabled = enabled


class Application:
    """GcmApplication, as list_mounts reaches it: the Mounted list, and Unmount All."""

    def __init__(self):
        self.mounts_section = MenuModel()
        self.unmount_all = Action()

    def lookup_action(self, name):
        assert name == "unmount-all", name
        return self.unmount_all


class Rows:
    """Gtk.TreeStore, as show_mounts walks one: each row a list, as the tree has it."""

    def __init__(self, *rows):
        self.rows = [list(row) for row in rows]
        self.changed: list = []

    def foreach(self, func):
        for index, row in enumerate(self.rows):
            if func(self, index, row):
                return

    def get_value(self, row, column):
        return row[column]

    def set_value(self, row, column, value):
        row[column] = value
        self.changed.append((row[0], column))


class Tree:
    """The server tree, as its tooltip reads a row."""

    def __init__(self, row):
        self.row = row

    def convert_widget_to_bin_window_coords(self, x, y):
        return x, y

    def get_path_at_pos(self, x, y):
        return (0,), None, x, y

    def get_model(self):
        return {(0,): self.row}


class Tooltip:
    def set_markup(self, text):
        self.text = text


def test_the_menu_and_tree_fakes_match_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gio, Gtk

    for fake, real, names in (
        (MenuModel, Gio.Menu, ("remove_all", "append_item", "append")),
        (MenuEntry, Gio.MenuItem, ("new", "set_action_and_target_value")),
        (Action, Gio.SimpleAction, ("set_enabled",)),
        (Application, Gtk.Application, ("lookup_action",)),
        (Rows, Gtk.TreeStore, ("foreach", "get_value", "set_value")),
        (
            Tree,
            Gtk.TreeView,
            ("convert_widget_to_bin_window_coords", "get_path_at_pos", "get_model"),
        ),
        (Tooltip, Gtk.Tooltip, ("set_markup",)),
    ):
        for name in names:
            assert hasattr(fake, name), f"{fake.__name__} is missing {name}"
            assert hasattr(real, name), f"{real.__name__} has no {name}"


def mnt(name):
    return Path(os.environ["HOME"], "mnt", name)


def host_called(app_module, name, address):
    host = make_host(app_module)
    host.name, host.host = name, address
    return host


def with_mounts(app_module, monkeypatch, hosts, *lines):
    """A Wmain with `hosts` in the tree and `lines` in the mount table, and an application
    whose Mounted list it fills."""
    monkeypatch.setattr(app_module, "groups", {"ops/prod": list(hosts)})
    mount_table(app_module, monkeypatch, *lines)
    monkeypatch.setattr(app_module.Gio, "MenuItem", MenuEntry)
    monkeypatch.setattr(app_module.GLib, "Variant", lambda kind, value: (kind, value))
    wmain = object.__new__(app_module.Wmain)
    wmain.application = Application()
    wmain.treeModel = Rows()
    return wmain


def three_mounts(app_module, monkeypatch):
    """router and lab_box mounted where their names put them, and a mount of no host's."""
    router = make_host(app_module)
    lab = host_called(app_module, "lab_box", "lab.example")
    lines = (
        mounted_line(router_folder()),
        mounted_line(mnt("old"), source="eric@gone.example:"),
        mounted_line(mnt("lab_box"), source="netops@lab.example:"),
        mounted_line(mnt("scratch"), kind="tmpfs", source="scratch"),
        mounted_line(mnt("deeper") / "box", source="netops@router.example.com:"),
    )
    return router, lab, with_mounts(app_module, monkeypatch, [router, lab], *lines)


def test_each_mount_in_mnt_is_listed_to_unmount_by_its_hosts_name(app_module, monkeypatch):
    """Or by what is mounted, for a mount that is no host's. Each `_` is doubled, which a
    menu built from a model would otherwise read as a mnemonic, measured."""
    _router, _lab, wmain = three_mounts(app_module, monkeypatch)

    wmain.show_mounts()

    assert wmain.application.mounts_section.items == [
        (
            "Unmount router from ~/mnt/router",
            "app.unmount-folder",
            ("s", str(router_folder())),
        ),
        (
            "Unmount eric@gone.example: from ~/mnt/old",
            "app.unmount-folder",
            ("s", str(mnt("old"))),
        ),
        (
            "Unmount lab__box from ~/mnt/lab__box",
            "app.unmount-folder",
            ("s", str(mnt("lab_box"))),
        ),
    ]
    assert wmain.application.unmount_all.enabled


def test_with_nothing_mounted_the_list_says_so_greyed(app_module, monkeypatch):
    """Given Unmount All, which is disabled, so that GTK draws it greyed: measured, an item
    with no action is drawn as one to choose."""
    wmain = with_mounts(app_module, monkeypatch, [make_host(app_module)])

    wmain.show_mounts()

    assert wmain.application.mounts_section.items == [
        ("Nothing is mounted", "app.unmount-all", None)
    ]
    assert not wmain.application.unmount_all.enabled


def test_the_list_is_rebuilt_only_when_what_is_mounted_changes(app_module, monkeypatch):
    """The mount table changes for any mount at all, and a menu rebuilt under the pointer
    loses its place."""
    router = make_host(app_module)
    wmain = with_mounts(app_module, monkeypatch, [router], mounted_line(router_folder()))

    wmain.show_mounts()
    wmain.show_mounts()
    assert wmain.application.mounts_section.emptied == 1

    mount_table(app_module, monkeypatch)
    wmain.show_mounts()
    assert wmain.application.mounts_section.emptied == 2
    assert wmain.application.mounts_section.items == [
        ("Nothing is mounted", "app.unmount-all", None)
    ]
    # And again once a host is renamed, which the list names it by.
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))
    wmain.show_mounts()
    router.name = "edge"
    wmain.show_mounts()
    assert wmain.application.mounts_section.emptied == 4
    assert wmain.application.mounts_section.items[0][0] == "Unmount edge from ~/mnt/router"


def test_the_tree_marks_each_host_mounted_and_unmarks_one_no_longer(app_module, monkeypatch):
    router, lab, wmain = three_mounts(app_module, monkeypatch)
    mail = host_called(app_module, "mail", "mail.example")
    wmain.treeModel = rows = Rows(
        ["prod", None, "gtk-directory", "#fff", "f1", ""],
        ["router", router, "gtk-network", "#fff", "", ""],
        ["mail", mail, "gtk-network", "#fff", "", str(mnt("mail"))],
        ["lab_box", lab, "gtk-network", "#fff", "", str(mnt("lab_box"))],
    )

    wmain.show_mounts()

    assert [row[5] for row in rows.rows] == ["", str(router_folder()), "", str(mnt("lab_box"))]
    # Only what changed is set, as each change redraws its row.
    assert rows.changed == [("router", 5), ("mail", 5)]
    rows.changed.clear()
    wmain.show_mounts()
    assert rows.changed == []


def test_the_tree_is_drawn_with_each_host_mounted_marked(app_module, monkeypatch):
    """As updateTree draws it: again for a host renamed or deleted, which changes which
    mount is whose."""
    router = make_host(app_module)
    mail = host_called(app_module, "mail", "mail.example")
    wmain = make_wmain_for_tree(app_module, monkeypatch, {"ops/prod": [router, mail]})
    mount_table(app_module, monkeypatch, mounted_line(router_folder()))

    wmain.updateTree()

    assert wmain.treeModel.find("router")[1].row[5:] == [str(router_folder())]
    assert wmain.treeModel.find("mail")[1].row[5:] == [""]
    assert wmain.treeModel.find("prod")[1].row[5:] == [""]


def test_the_tooltip_says_where_a_host_is_mounted(app_module, monkeypatch):
    escaped: list = []

    def escape(text, length):
        escaped.append(text)
        return text.replace("&", "&amp;")

    monkeypatch.setattr(app_module.GLib, "markup_escape_text", escape)
    host = make_host(app_module)
    wmain = object.__new__(app_module.Wmain)
    row = [host.name, host, "gtk-network", "#fff", "", "/home/x/mnt/R&D"]
    tooltip = Tooltip()

    assert wmain.on_treeServers_tooltip(Tree(row), 5, 5, False, tooltip)

    assert "\nMounted at /home/x/mnt/R&amp;D\n" in tooltip.text
    assert escaped == ["Mounted at /home/x/mnt/R&D"]
    row[5] = ""
    wmain.on_treeServers_tooltip(Tree(row), 5, 5, False, tooltip)
    assert "Mounted" not in tooltip.text


class Cell:
    """The tree's first Gtk.CellRendererPixbuf, as draw_mount_mark sets it."""

    def __init__(self):
        self.properties: dict = {}

    def set_property(self, name, value):
        self.properties[name] = value


def test_a_host_mounted_is_drawn_with_a_folder_on_a_network(app_module):
    """In place of its own icon, which the row's stock icon draws: its end is out of sight
    where a name is wider than the tree, measured."""
    model = Rows(["router", None, "gtk-network", "#fff", "", "/home/x/mnt/router"])
    mounted, plain = Cell(), Cell()

    app_module.draw_mount_mark(None, mounted, model, model.rows[0], None)
    model.rows[0][5] = ""
    app_module.draw_mount_mark(None, plain, model, model.rows[0], None)

    assert mounted.properties == {"icon-name": "folder-remote"}
    assert plain.properties == {}


def test_the_cell_fake_matches_real_gtk():
    gi = pytest.importorskip("gi", reason="PyGObject not available")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    assert hasattr(Cell, "set_property")
    assert Gtk.CellRendererPixbuf.find_property("icon-name") is not None
    assert Gtk.IconTheme.get_default().has_icon("folder-remote")


def test_unmounting_from_the_list_unmounts_that_folder(app_module, monkeypatch):
    _router, _lab, wmain = three_mounts(app_module, monkeypatch)
    calls: list = []
    wmain.unmount_files = lambda *args: calls.append(args)

    wmain.unmount_folder(router_folder())
    wmain.unmount_folder(mnt("old"))

    assert calls == [("router", router_folder()), ("eric@gone.example:", mnt("old"))]


@pytest.mark.parametrize("name", ["scratch", "gone", "deeper/box"])
def test_the_list_unmounts_nothing_but_an_sshfs_mount_in_mnt(app_module, monkeypatch, name):
    shown = said(app_module, monkeypatch)
    _router, _lab, wmain = three_mounts(app_module, monkeypatch)
    calls: list = []
    wmain.unmount_files = lambda *args: calls.append(args)

    wmain.unmount_folder(mnt(name))

    assert calls == []
    assert shown == [("info", f"{mnt(name).name} is not mounted at {mnt(name)}.")]


def unmounting_all(app_module, monkeypatch, installed=("fusermount3",)):
    shown = said(app_module, monkeypatch)
    monkeypatch.setattr(
        app_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in installed else None
    )
    _router, _lab, wmain = three_mounts(app_module, monkeypatch)
    count_refreshes(wmain)
    return wmain, Spawned(app_module, monkeypatch), shown


def test_unmount_all_unmounts_each_and_says_so_once_all_have_ended(app_module, monkeypatch):
    wmain, spawned, shown = unmounting_all(app_module, monkeypatch)
    for folder in (router_folder(), mnt("old"), mnt("lab_box")):
        folder.mkdir(parents=True)

    wmain.unmount_all_files()

    assert [argv for argv, _options in spawned.calls] == [
        ["/usr/bin/fusermount3", "-u", str(folder)]
        for folder in (router_folder(), mnt("old"), mnt("lab_box"))
    ]
    spawned.exit(0)
    spawned.exit(0, which=0)
    assert shown == []
    spawned.exit(0)
    # In the order listed, whatever the order they ended in.
    assert shown == [
        (
            "info",
            f"Unmounted router from {router_folder()}.\n"
            f"Unmounted eric@gone.example: from {mnt('old')}.\n"
            f"Unmounted lab_box from {mnt('lab_box')}.",
        )
    ]
    assert not any(folder.exists() for folder in (router_folder(), mnt("old"), mnt("lab_box")))
    assert wmain.refreshes == 3


def test_unmount_all_says_which_could_not_be_unmounted(app_module, monkeypatch):
    wmain, spawned, shown = unmounting_all(app_module, monkeypatch)

    wmain.unmount_all_files()
    spawned.exit(0)
    busy = f"fusermount3: failed to unmount {mnt('old')}: Device or resource busy\n"
    spawned.exit(1, busy)
    spawned.exit(0)

    assert shown == [
        (
            "error",
            f"Unmounted router from {router_folder()}.\n"
            f"Could not unmount {mnt('old')}: {busy.strip()}\n"
            f"Unmounted lab_box from {mnt('lab_box')}.",
        )
    ]


def test_unmount_all_with_nothing_mounted_does_nothing(app_module, monkeypatch):
    shown = said(app_module, monkeypatch)
    wmain = with_mounts(app_module, monkeypatch, [make_host(app_module)])
    spawned = Spawned(app_module, monkeypatch)

    wmain.unmount_all_files()

    assert spawned.calls == [] and shown == []


def test_unmount_all_without_fusermount_says_so(app_module, monkeypatch):
    wmain, spawned, shown = unmounting_all(app_module, monkeypatch, installed=())

    wmain.unmount_all_files()

    assert spawned.calls == []
    assert shown == [("error", "Unmounting needs fusermount, which is not installed.")]


def test_mount_changes_are_followed_as_the_mount_table_reports_them(app_module, monkeypatch):
    """However they were made: GCM, a terminal, or a mount that dropped."""
    connected: list = []
    monitor = types.SimpleNamespace(
        connect=lambda signal, handler: connected.append((signal, handler))
    )
    monkeypatch.setattr(
        app_module.Gio, "UnixMountMonitor", types.SimpleNamespace(get=lambda: monitor)
    )
    wmain = object.__new__(app_module.Wmain)
    count_refreshes(wmain)

    wmain.watch_mounts()

    [(signal, handler)] = connected
    assert signal == "mounts-changed" and wmain.mount_monitor is monitor
    handler(monitor)
    assert wmain.refreshes == 1


# -- against real GTK, GIO, sshfs and sshd ------------------------------------------------

_SCRIPT = r'''
import faulthandler, os, sys, time
faulthandler.dump_traceback_later(100, exit=True)
scenario, scratch = sys.argv[1], sys.argv[2]
os.environ["HOME"] = os.path.join(scratch, "home")
os.makedirs(os.environ["HOME"], exist_ok=True)
os.environ["XDG_RUNTIME_DIR"] = os.path.join(scratch, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)
os.environ["SHELL"] = "/bin/sh"
sys.argv = ["gcm"]
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import Gtk
from gnome_connection_manager import app

app.conf.STARTUP_LOCAL = False
app.conf.CHECK_UPDATES = False
application = app.GcmApplication()
assert application.register(None)
application.activate()
w = application._controller
shown = []
app.msgbox = shown.append
app.msginfo = shown.append

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def until(condition, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not condition():
        Gtk.main_iteration_do(False)
        time.sleep(0.005)
    return condition()

def ssh_host(name, address, user="", password="", port="22", key="", group=""):
    return app.Host(group, name, "", address, user, password, key, port, "", "ssh", "")

if scenario == "the-tree-menu":
    # Real clicks, through XTest, on the scenario's own display.
    import ctypes
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    xtst.XTestFakeMotionEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
    ]
    display = x11.XOpenDisplay(None)
    assert display, "no connection to the display for XTest"

    def click(number, x, y):
        xtst.XTestFakeMotionEvent(display, -1, int(x), int(y), 0)
        x11.XFlush(display)
        pump(0.1)
        xtst.XTestFakeButtonEvent(display, number, True, 0)
        xtst.XTestFakeButtonEvent(display, number, False, 0)
        x11.XFlush(display)

    box = ssh_host("box", "192.0.2.10", "eric", port="2222", group="Lab")
    switch = ssh_host("switch", "192.0.2.11", "admin", group="Lab")
    switch.type = "telnet"
    app.groups.clear()
    app.groups["Lab"] = [box, switch]
    w.updateTree()
    w.treeServers.expand_all()
    # Started with no configuration, the window is 142 pixels tall, and the tree too short
    # to show three rows.
    w.wMain.resize(900, 600)
    w.wMain.present()
    assert until(w.wMain.is_active)
    assert until(lambda: w.treeServers.get_allocated_height() > 200)
    pump(0.5)
    menu = w.popupMenuFolder

    def row_point(name):
        """Where the row called `name` is on the screen, or with None the space below the
        rows."""
        rows = []
        w.treeModel.foreach(lambda model, path, it: rows.append((model.get_value(it, 0), path.copy())))
        column = w.treeServers.get_column(0)
        _, x, y = w.treeServers.get_bin_window().get_origin()
        if name is None:
            last = w.treeServers.get_cell_area(rows[-1][1], column)
            return x + last.x + last.width // 2, y + last.y + last.height + 40
        found = [path for row, path in rows if row == name]
        assert found, [row for row, path in rows]
        area = w.treeServers.get_cell_area(found[0], column)
        return x + area.x + area.width // 2, y + area.y + area.height // 2

    def right_click(name):
        """Right-click the row called `name`, or with None the space below the rows, and
        wait for the tree's menu."""
        click(3, *row_point(name))
        assert until(menu.get_visible), "the tree's menu did not open"
        pump(0.6)

    def widget_point(widget):
        allocation = widget.get_allocation()
        _, x, y = widget.get_window().get_origin()
        return x + allocation.x + allocation.width // 2, y + allocation.y + allocation.height // 2

    def labelled(shell, text):
        """The item of a menu or menubar drawn with `text`."""
        drawn = {}
        for item in shell.get_children():
            if isinstance(item.get_child(), Gtk.Label):
                drawn[item.get_child().get_text()] = item
        assert text in drawn, sorted(drawn)
        return drawn[text]

    def from_servers_menu(text):
        """Choose `text` in the menubar's Servers menu, with real clicks."""
        servers = labelled(w.menubar, "Servers")
        click(1, *widget_point(servers))
        submenu = servers.get_submenu()
        assert until(submenu.get_visible), "the Servers menu did not open"
        pump(0.3)
        click(1, *widget_point(labelled(submenu, text)))
        assert until(lambda: not submenu.get_visible()), "the Servers menu stayed open"
        pump(0.3)

    def dismiss():
        menu.popdown()
        assert until(lambda: not menu.get_visible())
        pump(0.3)

    def choose(item):
        """Click `item` in the open menu."""
        allocation = item.get_allocation()
        _, x, y = item.get_window().get_origin()
        click(1, x + allocation.x + allocation.width // 2, y + allocation.y + allocation.height // 2)
        assert until(lambda: not menu.get_visible()), "the menu stayed open"
        pump(0.3)

    def offered():
        items = (menu.mnuOpenFiles, menu.mnuMount, menu.mnuUnmount)
        return tuple(item.get_visible() for item in items)

    opened, mounted, unmounted = [], [], []
    app.open_in_file_manager = opened.append
    w.mount_files = lambda host, folder: mounted.append((host.name, str(folder)))
    w.unmount_files = lambda name, folder: unmounted.append((name, str(folder)))
    folder = os.path.join(os.environ["HOME"], "mnt", "box")
    address = "sftp://eric@192.0.2.10:2222/"

    right_click("box")
    assert offered() == (True, True, False), offered()
    choose(menu.mnuOpenFiles)
    assert opened == [address], opened

    right_click("box")
    choose(menu.mnuMount)
    assert mounted == [("box", folder)], mounted

    # A telnet host, a folder and the space below the rows, each after an SSH host's menu
    # offered them, so that a menu left as that one was shows.
    for name in ("switch", "Lab", None):
        right_click("box")
        assert offered() == (True, True, False), offered()
        dismiss()
        right_click(name)
        assert offered() == (False, False, False), (name, offered())
        dismiss()

    # The Servers menu acts on the host selected in the tree, and offers every item
    # whatever that host's state.
    click(1, *row_point("box"))
    assert until(lambda: getattr(w.get_selected_host(), "name", None) == "box")
    pump(0.3)
    from_servers_menu("Open in File Manager")
    assert opened == [address, address], opened
    from_servers_menu("Unmount SSHFS")
    assert unmounted == [] and shown == [f"box is not mounted at {folder}."], shown
    shown.clear()
    from_servers_menu("Mount with SSHFS")
    assert mounted == [("box", folder), ("box", folder)], mounted

    # Mounted where Mount with SSHFS puts it, from it: Unmount in Mount's place.
    app.read_mount_table = lambda: f"300 1 0:90 / {folder} rw - fuse.sshfs eric@192.0.2.10: rw\n"
    right_click("box")
    assert offered() == (True, False, True), offered()
    choose(menu.mnuUnmount)
    assert unmounted == [("box", folder)], unmounted
    assert len(mounted) == 2 and opened == [address, address]
    assert shown == [], shown

    # A host mounted is drawn with a folder on a network in place of its own icon, as read
    # from the window, the row not selected. Each row is striped, so against itself.
    from gi.repository import Gdk

    def icon_of(name):
        w.treeServers.get_selection().unselect_all()
        w.wMain.present()
        pump(0.5)
        rows = []
        w.treeModel.foreach(lambda model, path, it: rows.append((model.get_value(it, 0), path.copy())))
        [path] = [path for row, path in rows if row == name]
        area = w.treeServers.get_cell_area(path, w.treeServers.get_column(0))
        return Gdk.pixbuf_get_from_window(
            w.treeServers.get_bin_window(), area.x, area.y + area.height // 2 - 8, 14, 16
        ).get_pixels()

    # Not yet marked: the mount table was changed without GIO telling.
    plain = icon_of("box")
    w.show_mounts()
    marked = icon_of("box")
    assert marked != plain

    def mounted_menu():
        """Open Servers ▸ Mounted with real clicks: each item it draws, and whether it can
        be chosen."""
        servers = labelled(w.menubar, "Servers")
        click(1, *widget_point(servers))
        assert until(servers.get_submenu().get_visible), "the Servers menu did not open"
        pump(0.3)
        item = labelled(servers.get_submenu(), "Mounted")
        click(1, *widget_point(item))
        assert until(item.get_submenu().get_visible), "Servers ▸ Mounted did not open"
        pump(0.4)
        listed = item.get_submenu()
        return listed, [
            (each.get_child().get_text(), each.is_sensitive())
            for each in listed.get_children()
            if isinstance(each.get_child(), Gtk.Label)
        ]

    def from_mounted_menu(text):
        listed, _drawn = mounted_menu()
        click(1, *widget_point(labelled(listed, text)))
        assert until(lambda: not listed.get_visible()), "Servers ▸ Mounted stayed open"
        pump(0.3)

    # Each mount listed, by its host's name, or by what is mounted for one of no host's,
    # a `_` drawn as one.
    table = (
        f"300 1 0:90 / {folder} rw - fuse.sshfs eric@192.0.2.10: rw\n"
        f"301 1 0:91 / {os.environ['HOME']}/mnt/an_old rw - fuse.sshfs ops@gone.example: rw\n"
    )
    app.read_mount_table = lambda: table
    w.show_mounts()
    listed, drawn = mounted_menu()
    assert drawn == [
        ("Unmount box from ~/mnt/box", True),
        ("Unmount ops@gone.example: from ~/mnt/an_old", True),
        ("Unmount All", True),
    ], drawn
    w.menubar.deactivate()
    assert until(lambda: not listed.get_visible())
    pump(0.3)
    from_mounted_menu("Unmount ops@gone.example: from ~/mnt/an_old")
    assert unmounted[-1] == ("ops@gone.example:", os.path.join(os.environ["HOME"], "mnt", "an_old"))
    everything = []
    w.unmount_all_files = lambda: everything.append(True)
    from_mounted_menu("Unmount All")
    assert everything == [True], everything

    # Renamed while mounted: still found where its old name put it, in the tree's menu
    # and in the list, and unmounted from there.
    box.name = "box renamed"
    w.updateTree()
    w.treeServers.expand_all()
    pump(0.5)
    assert icon_of("box renamed") == marked
    right_click("box renamed")
    assert offered() == (True, False, True), offered()
    choose(menu.mnuUnmount)
    assert unmounted[-1] == ("box renamed", folder), unmounted
    listed, drawn = mounted_menu()
    assert drawn[0] == ("Unmount box renamed from ~/mnt/box", True), drawn
    w.menubar.deactivate()
    assert until(lambda: not listed.get_visible())
    pump(0.3)

    # Nothing mounted: no mark, and the list says so, greyed, as Unmount All is.
    app.read_mount_table = lambda: ""
    w.show_mounts()
    assert icon_of("box renamed") == plain
    listed, drawn = mounted_menu()
    assert drawn == [("Nothing is mounted", False), ("Unmount All", False)], drawn
    w.menubar.deactivate()
    assert until(lambda: not listed.get_visible())
    assert shown == [], shown

elif scenario == "file-manager":
    address = "sftp://eric@files.example:2222/"
    marks, expected = os.environ["PROBE_MARKS"], os.environ["PROBE_EXPECT"]

    def marked():
        try:
            with open(marks) as lines:
                return lines.read().splitlines()
        except FileNotFoundError:
            return []

    app.open_in_file_manager(address)
    if expected:
        assert until(marked), "nothing was opened"
        pump(0.5)
        assert marked() == [expected + "|" + address], marked()
        assert shown == [], shown
    else:
        pump(1)
        assert len(shown) == 1, shown
        assert shown[0].startswith(f"No file manager was found to open {address}."), shown
        assert marked() == [], marked()

elif scenario in ("sshfs-real-sshd", "sshfs-stored-password"):
    remote = os.environ["PROBE_REMOTE"]
    w.selected = None
    w.get_selected_host = lambda: w.selected

    def mount(host):
        shown.clear()
        w.selected = host
        w.mount_selected_files()
        assert until(lambda: shown and not w.mounting), (shown, w.mounting)
        return shown[0]

    def unmount(host):
        shown.clear()
        w.selected = host
        w.unmount_selected_files()
        assert until(lambda: shown), "nothing was said"
        pump(0.3)
        assert len(shown) == 1, shown
        assert w.files_mount(host) is None, "still mounted"
        return shown[0]

    def mount_items(host):
        w.prepare_files_items(host)
        return w.popupMenuFolder.mnuMount.get_visible(), w.popupMenuFolder.mnuUnmount.get_visible()

    if scenario == "sshfs-real-sshd":
        port, key, user = os.environ["PROBE_PORT"], os.environ["PROBE_KEY"], os.environ["PROBE_USER"]
        known, host_key = os.environ["PROBE_KNOWN_HOSTS"], os.environ["PROBE_HOST_KEY"]
        box = ssh_host("probe box", "127.0.0.1", user, port=port, key=key)
        folder = w.files_folder(box)
        assert folder == app.Path(os.environ["HOME"], "mnt", "probe box"), folder

        # A key, and a host key ssh knows: the login folder, mounted at ~/mnt/<its name>.
        with open(known, "w") as out:
            out.write(host_key)
        said = mount(box)
        assert said == f"Mounted probe box at {folder}.", said
        assert w.files_mount(box) == folder
        assert sorted(os.listdir(folder)) == sorted(os.listdir(remote)), os.listdir(folder)
        # Neither sshfs nor its ssh is in GCM's session or process group, so what a terminal
        # sends GCM, Ctrl+C or the hangup as it closes, reaches neither.
        log = os.path.join(os.environ["XDG_RUNTIME_DIR"], "gcm", "sshfs-probe_box.log")
        tied = {}
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as cmdline:
                    argv = cmdline.read().split(b"\0")
                with open(f"/proc/{pid}/stat") as stat:
                    _state, _parent, group, session = stat.read().rsplit(")", 1)[1].split()[:4]
            except OSError:
                continue
            if int(pid) != os.getpid() and (log.encode() in argv or str(folder).encode() in argv):
                tied[os.path.basename(argv[0]).decode()] = (int(session), int(group))
        assert sorted(tied) == ["ssh", "sshfs"], tied
        for program, (session, group) in tied.items():
            assert session != os.getsid(0) and group != os.getpgrp(), (program, tied)
        assert mount_items(box) == (False, True)
        said = unmount(box)
        assert said == f"Unmounted probe box from {folder}.", said
        assert mount_items(box) == (True, False)
        # Removed with the mount, and ~/mnt kept.
        assert not folder.exists() and folder.parent.is_dir(), os.listdir(folder.parent)

        # A host key ssh does not know: the question is refused, at once, though there is
        # a password the helper could give.
        open(known, "w").close()
        asking = ssh_host("probe box", "127.0.0.1", user, password="not-a-key", port=port, key=key)
        start = time.monotonic()
        said = mount(asking)
        assert said == f"Could not mount probe box at {folder}: Host key verification failed.", said
        assert time.monotonic() - start < 10
        assert app.remotefiles.mount_at(app.read_mount_table(), folder) is None
        assert not folder.exists()

        # Nothing listening at the port: ssh's reason, at once, and nothing mounted.
        closed = os.environ["PROBE_CLOSED_PORT"]
        with open(known, "w") as out:
            out.write(host_key)
        nowhere = ssh_host("probe box", "127.0.0.1", user, port=closed, key=key)
        start = time.monotonic()
        said = mount(nowhere)
        reason = f"ssh: connect to host 127.0.0.1 port {closed}: Connection refused"
        assert said == f"Could not mount probe box at {folder}: {reason}", said
        assert time.monotonic() - start < 10
        assert app.remotefiles.mount_at(app.read_mount_table(), folder) is None
        assert not folder.exists()

        # A stored password, and no key: ssh asks the helper, which answers with it.
        locked = ssh_host("probe box", "127.0.0.1", user, password="not-a-key", port=port)
        said = mount(locked)
        assert said.startswith(f"Could not mount probe box at {folder}: "), said
        assert said.endswith("Permission denied (publickey,password)."), said
        assert app.remotefiles.mount_at(app.read_mount_table(), folder) is None
        assert not folder.exists()

        # A key whose path has a space and a comma in it.
        odd = os.path.join(scratch, "a key, b")
        os.makedirs(odd)
        app.shutil.copy(key, os.path.join(odd, "id key"))
        os.chmod(os.path.join(odd, "id key"), 0o600)
        oddly = ssh_host("odd", "127.0.0.1", user, port=port, key=os.path.join(odd, "id key"))
        said = mount(oddly)
        assert said == f"Mounted odd at {w.files_folder(oddly)}.", said
        said = unmount(oddly)
        assert said == f"Unmounted odd from {w.files_folder(oddly)}.", said
        assert not w.files_folder(oddly).exists()

        # A mount made outside GCM, and its unmount: the tree and Servers ▸ Mounted follow
        # them as GIO reports the mount table changing, with nothing asking GCM to look.
        app.groups.clear()
        app.groups["Lab"] = [box]
        w.updateTree()
        section = application.mounts_section

        def marked():
            found = []
            w.treeModel.foreach(
                lambda model, path, it: model.get_value(it, 1) is box
                and found.append(model.get_value(it, 5))
            )
            return found[0]

        def listed():
            return [
                section.get_item_attribute_value(index, "label").get_string()
                for index in range(section.get_n_items())
            ]

        assert marked() == "" and listed() == ["Nothing is mounted"], (marked(), listed())
        folder.mkdir()
        by_hand = ["sshfs", "-p", port, "-o", f"IdentityFile={key}", f"{user}@127.0.0.1:", str(folder)]
        import subprocess

        subprocess.run(by_hand, check=True, timeout=30)
        assert until(lambda: marked() == str(folder)), marked()
        assert until(lambda: listed() == ["Unmount probe box from ~/mnt/probe box"]), listed()
        subprocess.run([app.fusermount(), "-u", str(folder)], check=True, timeout=30)
        assert until(lambda: marked() == ""), marked()
        assert until(lambda: listed() == ["Nothing is mounted"]), listed()
        folder.rmdir()

        # Renamed while mounted: found where its old name put it, and unmounted from there.
        assert mount(box) == f"Mounted probe box at {folder}."
        assert marked() == str(folder)
        box.name = "renamed box"
        w.updateTree()
        assert w.files_folder(box) != folder
        assert w.files_mount(box) == folder and marked() == str(folder)
        assert listed() == ["Unmount renamed box from ~/mnt/probe box"], listed()
        assert mount_items(box) == (False, True)
        said = unmount(box)
        assert said == f"Unmounted renamed box from {folder}.", said
        assert not folder.exists() and marked() == "" and listed() == ["Nothing is mounted"]
        box.name = "probe box"

        # Mounted for the test to find once GCM has gone.
        assert mount(box) == f"Mounted probe box at {folder}."
        print("LEFT", folder)
    else:
        right = ssh_host("stored", "files.example", "eric", password="s3cret; $HOME 'x'", port="2200")
        folder = w.files_folder(right)
        said = mount(right)
        assert said == f"Mounted stored at {folder}.", said
        assert os.listdir(folder) == ["notes.txt"], os.listdir(folder)
        said = unmount(right)
        assert said == f"Unmounted stored from {folder}.", said
        assert not folder.exists()
        wrong = ssh_host("stored", "files.example", "eric", password="nope", port="2200")
        said = mount(wrong)
        reason = "eric@files.example: Permission denied (publickey,password)."
        assert said == f"Could not mount stored at {folder}: {reason}", said
        assert w.files_mount(wrong) is None
        assert not folder.exists()

else:
    raise SystemExit("no scenario " + scenario)
w.wMain.destroy()
print("OK")
'''


def run_scenario(scenario, tmp_path, display=None, **extra):
    """Run a scenario as GCM runs, and fail on what it raised or GLib complained of."""
    environment = dict(os.environ)
    for name in ("XDG_CONFIG_HOME", "GDK_SCALE", "GDK_DPI_SCALE"):
        environment.pop(name, None)
    if display is not None:
        environment.pop("WAYLAND_DISPLAY", None)
        environment.update(DISPLAY=display, GDK_BACKEND="x11")
    environment.update(extra)
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=environment,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]
    assert "OK" in result.stdout
    # PyGObject prints what a signal handler raises, and carries on.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == []
    return result


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="needs Xvfb for a display of its own")
def test_the_tree_menu_offers_an_ssh_hosts_files_against_real_gtk(tmp_path):
    """Its own display, since the clicks are real: on the one the other tests share,
    another test's window can be where the click lands."""
    pytest.importorskip("gi", reason="PyGObject not available")
    process, display = _private_display()
    try:
        run_scenario("the-tree-menu", tmp_path, display=display)
    finally:
        process.terminate()
        process.wait()


def without_applications(tmp_path):
    """The system's data folders, as links to all they hold but their applications.

    So GTK finds its icons, its schemas and the MIME database there as ever, and GIO only
    the applications a test gives it, and none the system has installed, which might be a
    default for folders."""
    folders = []
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for number, name in enumerate(system.split(os.pathsep)):
        source = Path(name)
        if not source.is_dir():
            continue
        copy = tmp_path / f"data-{number}"
        copy.mkdir()
        for entry in source.iterdir():
            if entry.name != "applications":
                (copy / entry.name).symlink_to(entry)
        folders.append(str(copy))
    return folders


@pytest.mark.parametrize(
    ("default", "on_path", "expected"),
    [
        # GIO's default application for folders, named by a MIME cache, before PATH.
        (True, ("thunar",), "files-app"),
        # A desktop file alone makes no default, measured: the first file manager on PATH.
        (False, ("dolphin", "thunar"), "thunar"),
        # Neither: GCM says so, and neither xdg-open nor a browser is handed the address.
        (False, (), ""),
    ],
)
def test_open_in_file_manager_against_real_gio(tmp_path, default, on_path, expected):
    pytest.importorskip("gi", reason="PyGObject not available")
    bin_dir, share = tmp_path / "bin", tmp_path / "share" / "applications"
    bin_dir.mkdir()
    share.mkdir(parents=True)
    marks = tmp_path / "marks"
    for name in ("files-app", "xdg-open", "x-www-browser", *on_path):
        program = bin_dir / name
        program.write_text(
            f'#!/bin/sh\nfor argument in "$@"; do printf "%s|%s\\n" {name} "$argument"; done'
            f' >> "{marks}"\n'
        )
        program.chmod(0o755)
    if expected:
        (share / "files-app.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Files app\n"
            f"Exec={bin_dir}/files-app %U\nMimeType=inode/directory;\n"
        )
    if default:
        (share / "mimeinfo.cache").write_text("[MIME Cache]\ninode/directory=files-app.desktop;\n")
    nothing = tmp_path / "nothing"
    nothing.mkdir()
    scratch = tmp_path / "scenario"
    scratch.mkdir()

    run_scenario(
        "file-manager",
        scratch,
        PATH=str(bin_dir),
        XDG_DATA_HOME=str(nothing),
        XDG_DATA_DIRS=os.pathsep.join([str(tmp_path / "share"), *without_applications(tmp_path)]),
        XDG_CONFIG_DIRS=str(nothing),
        PROBE_MARKS=str(marks),
        PROBE_EXPECT=expected,
    )


SSHD = shutil.which(
    "sshd", path=os.pathsep.join([os.environ.get("PATH", ""), "/usr/sbin", "/sbin"])
)
SSHFS = shutil.which("sshfs")
SSH = shutil.which("ssh")
FUSERMOUNT = shutil.which("fusermount3") or shutil.which("fusermount")


def sftp_server():
    """The sftp-server beside the sshd found, or the system's."""
    candidates = [Path("/usr/lib/openssh/sftp-server"), Path("/usr/libexec/openssh/sftp-server")]
    if SSHD:
        candidates.insert(0, Path(SSHD).resolve().parents[1] / "lib" / "openssh" / "sftp-server")
    return next((path for path in candidates if path.exists()), None)


needs_sshfs = pytest.mark.skipif(
    not (
        SSHD and SSHFS and SSH and FUSERMOUNT and sftp_server() and os.access("/dev/fuse", os.W_OK)
    ),
    reason="needs sshfs, FUSE, and sshd with its sftp-server",
)


def unmount_below(folder):
    """Unmount whatever a scenario left mounted under `folder`, so no test leaves a mount."""
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        point = line.split(" ")[4].replace("\\040", " ")
        if point.startswith(str(folder)):
            subprocess.run([str(FUSERMOUNT), "-u", point], capture_output=True, check=False)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def sshd(tmp_path):
    """sshd as this user on 127.0.0.1, serving SFTP from a folder of the test's, and an ssh
    that reads a configuration of the test's only: measured, ssh -F still reads the default
    keys in ~/.ssh unless told IdentityFile none."""
    root = tmp_path / "sshd"
    root.mkdir(mode=0o700)
    remote = tmp_path / "remote"
    (remote / "logs").mkdir(parents=True)
    (remote / "notes.txt").write_text("kept\n")
    for name in ("hostkey", "id"):
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(root / name)], check=True
        )
    shutil.copy(root / "id.pub", root / "authorized_keys")
    known = root / "known_hosts"
    known.write_text("")
    (root / "ssh_config").write_text(
        f"Host *\n  UserKnownHostsFile {known}\n  GlobalKnownHostsFile /dev/null\n"
        "  IdentitiesOnly yes\n  IdentityAgent none\n  IdentityFile none\n"
    )
    shim = root / "bin"
    shim.mkdir()
    (shim / "ssh").write_text(f'#!/bin/sh\nexec {SSH} -F {root}/ssh_config "$@"\n')
    (shim / "ssh").chmod(0o755)
    log = root / "sshd.log"
    # Another worker can take the port between its choosing and sshd binding it.
    for _attempt in range(5):
        port = free_port()
        (root / "sshd_config").write_text(
            f"Port {port}\nListenAddress 127.0.0.1\nHostKey {root}/hostkey\n"
            f"PidFile {root}/sshd.pid\nAuthorizedKeysFile {root}/authorized_keys\n"
            "UsePAM no\nStrictModes no\nPasswordAuthentication yes\n"
            "KbdInteractiveAuthentication no\n"
            f"Subsystem sftp internal-sftp -d {remote}\n"
        )
        with log.open("w") as out:
            server = subprocess.Popen(
                [str(SSHD), "-D", "-e", "-f", str(root / "sshd_config")],
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 10
        while server.poll() is None and time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), 1).close()
                break
            except OSError:
                time.sleep(0.05)
        if server.poll() is None:
            break
    else:
        pytest.fail(f"sshd did not start: {log.read_text()}")
    try:
        keyscan = subprocess.run(
            ["ssh-keyscan", "-p", str(port), "127.0.0.1"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert keyscan.stdout, keyscan.stderr
        yield types.SimpleNamespace(
            port=port,
            root=root,
            remote=remote,
            known=known,
            log=log,
            shim=shim,
            host_key=keyscan.stdout,
        )
    finally:
        server.terminate()
        server.wait(timeout=10)


@needs_sshfs
def test_mounting_with_sshfs_through_a_real_ssh_and_sshd(sshd, tmp_path):
    scratch = tmp_path / "scenario"
    scratch.mkdir()
    try:
        result = run_scenario(
            "sshfs-real-sshd",
            scratch,
            PATH=f"{sshd.shim}{os.pathsep}{os.environ['PATH']}",
            PROBE_PORT=str(sshd.port),
            PROBE_CLOSED_PORT=str(free_port()),
            PROBE_KEY=str(sshd.root / "id"),
            PROBE_USER=pwd.getpwuid(os.getuid()).pw_name,
            PROBE_REMOTE=str(sshd.remote),
            PROBE_KNOWN_HOSTS=str(sshd.known),
            PROBE_HOST_KEY=sshd.host_key,
        )
        # The password ssh asked the helper for reached sshd, which could not check it.
        assert "Failed password for" in sshd.log.read_text(), sshd.log.read_text()[-2000:]
        # The mount outlives GCM: sshfs runs as a daemon in a session of its own.
        left = result.stdout.split("LEFT ", 1)[1].splitlines()[0]
        table = Path("/proc/self/mountinfo").read_text()
        assert remotefiles.mount_at(table, left) is not None, "gone with GCM"
    finally:
        unmount_below(scratch)


FAKE_SSH = r"""#!/usr/bin/env python3
# ssh as far as sshfs and the askpass helper see it: it asks SSH_ASKPASS for the password,
# as ssh does under SSH_ASKPASS_REQUIRE=force, three times at most, and writes its failure
# to its -E log. Answered rightly, it serves SFTP from a folder of the test's.
import os, subprocess, sys
log = sys.argv[sys.argv.index("-E") + 1]
for _attempt in range(3):
    prompt = "eric@files.example's password: "
    with open(os.environ["PROBE_ASKED"], "a") as asked:
        asked.write(prompt + "\n")
    answer = subprocess.run([os.environ["SSH_ASKPASS"], prompt], capture_output=True, text=True)
    if answer.returncode == 0 and answer.stdout == os.environ["PROBE_PASSWORD"] + "\n":
        os.chdir(os.environ["PROBE_REMOTE"])
        os.execv(os.environ["PROBE_SFTP_SERVER"], ["sftp-server"])
with open(log, "a") as out:
    out.write("eric@files.example: Permission denied (publickey,password).\n")
sys.exit(255)
"""


@needs_sshfs
def test_a_stored_password_mounts_through_the_askpass_helper(tmp_path):
    """The success no real sshd here can show: one not run as root checks no password."""
    scratch = tmp_path / "scenario"
    scratch.mkdir()
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "notes.txt").write_text("kept\n")
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "ssh").write_text(FAKE_SSH)
    (shim / "ssh").chmod(0o755)
    asked = tmp_path / "asked"
    try:
        run_scenario(
            "sshfs-stored-password",
            scratch,
            PATH=f"{shim}{os.pathsep}{os.environ['PATH']}",
            PROBE_PASSWORD="s3cret; $HOME 'x'",
            PROBE_REMOTE=str(remote),
            PROBE_ASKED=str(asked),
            PROBE_SFTP_SERVER=str(sftp_server()),
        )
    finally:
        unmount_below(scratch)
    # Once for the right password, and as ssh does, three times for the wrong one.
    assert asked.read_text().splitlines() == ["eric@files.example's password: "] * 4
