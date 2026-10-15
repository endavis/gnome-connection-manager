"""A host's files outside its console (#267): the `sftp://` address the file manager is
given, the sshfs command that mounts a host under ~/mnt, how the mount table is read, and
the askpass helper that answers ssh with a host's stored password.

All of it without a display, a file manager or FUSE. tests/test_host_files.py runs it in
GCM, with real sshfs mounts.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from gnome_connection_manager.utils import placeholders, remotefiles

REPO = Path(__file__).resolve().parents[1]
ASKPASS = REPO / "data" / "scripts" / "gcm-askpass"


@pytest.mark.parametrize(
    ("address", "user", "port", "expected"),
    [
        ("files.example", "eric", "22", "sftp://eric@files.example/"),
        ("files.example", "eric", "2222", "sftp://eric@files.example:2222/"),
        ("files.example", "eric", "", "sftp://eric@files.example/"),
        ("files.example", "eric", " 2222 ", "sftp://eric@files.example:2222/"),
        ("files.example", "", "22", "sftp://files.example/"),
        ("files.example", None, "2222", "sftp://files.example:2222/"),
        # A user's own @ and : stay the user's, so the address names the right host.
        ("files.example", "ops@corp", "22", "sftp://ops%40corp@files.example/"),
        ("files.example", "a:b c", "22", "sftp://a%3Ab%20c@files.example/"),
        ("192.0.2.7", "eric", "2222", "sftp://eric@192.0.2.7:2222/"),
        ("2001:db8::7", "eric", "2222", "sftp://eric@[2001:db8::7]:2222/"),
        ("::1", "eric", "22", "sftp://eric@[::1]/"),
    ],
)
def test_the_sftp_address_of_a_hosts_files(address, user, port, expected):
    assert remotefiles.sftp_address(address, user, port) == expected


def test_the_address_never_holds_a_password():
    """There is nowhere to put one: the file manager asks for it."""
    assert "password" not in remotefiles.sftp_address.__code__.co_varnames


# Read from the desktop files of Ubuntu 24.04's packages, each the one declaring
# inode/directory: Exec as written, and no MimeType of any of them names
# x-scheme-handler/sftp.
MEASURED_EXEC = {
    "nautilus": "nautilus --new-window %U",
    "nemo": "nemo %U",
    "caja": "/usr/bin/caja --no-desktop %U",
    "thunar": "thunar %U",
    "dolphin": "dolphin %u",
    "pcmanfm-qt": "pcmanfm-qt %U",
    "pcmanfm": "pcmanfm %U",
}


def test_each_file_manager_is_given_its_desktop_files_arguments():
    for command in remotefiles.FILE_MANAGERS:
        exec_line = MEASURED_EXEC[command[0]].split()
        assert exec_line[-1] in ("%U", "%u"), exec_line
        assert Path(exec_line[0]).name == command[0]
        assert tuple(exec_line[1:-1]) == command[1:], command
    assert {command[0] for command in remotefiles.FILE_MANAGERS} == set(MEASURED_EXEC)


def test_the_first_file_manager_found_opens_the_address():
    installed = {"thunar": "/usr/bin/thunar", "pcmanfm": "/usr/bin/pcmanfm"}

    assert remotefiles.file_manager_command(installed.get) == ["/usr/bin/thunar"]


def test_a_file_managers_own_arguments_come_first():
    installed = {"caja": "/usr/bin/caja", "nautilus": "/usr/bin/nautilus"}

    assert remotefiles.file_manager_command(installed.get) == [
        "/usr/bin/nautilus",
        "--new-window",
    ]
    assert remotefiles.file_manager_command({"caja": "/usr/bin/caja"}.get) == [
        "/usr/bin/caja",
        "--no-desktop",
    ]


def test_no_file_manager_found_is_none():
    assert remotefiles.file_manager_command({}.get) is None


@pytest.mark.parametrize(
    ("name", "folder"),
    [
        ("web01", "web01"),
        ("probe box", "probe box"),
        # A / cannot reach another folder, nor a leading dot walk up.
        ("prod/web01", "prod_web01"),
        ("../../etc", "etc"),
        ("..", "session"),
    ],
)
def test_a_host_is_mounted_under_mnt_by_its_name(name, folder):
    assert remotefiles.mount_folder("/home/eric", name) == Path("/home/eric/mnt", folder)


@pytest.mark.parametrize(
    ("address", "user", "source"),
    [
        ("files.example", "eric", "eric@files.example:"),
        ("files.example", "", "files.example:"),
        # As the mount table lists it, measured.
        ("2001:db8::7", "tester", "tester@[2001:db8::7]:"),
    ],
)
def test_what_sshfs_mounts_is_the_login_folder(address, user, source):
    assert remotefiles.sshfs_source(address, user) == source


@pytest.mark.parametrize(
    ("address", "user", "option"),
    [
        ("files.example", "-oProxyCommand=touch x", True),
        ("-oProxyCommand=touch x", "", True),
        # Behind a user, an address is a destination, which ssh refuses, measured.
        ("-oProxyCommand=touch x", "eric", False),
        ("files.example", "eric", False),
        ("2001:db8::7", "", False),
    ],
)
def test_a_host_ssh_would_read_as_an_option_is_known(address, user, option):
    """Measured: sshfs hands ssh such a source as it is, after `--` or not."""
    assert remotefiles.read_as_option(address, user) is option


def test_sshfs_mounts_with_the_hosts_port_and_key_and_a_log_for_ssh():
    command = remotefiles.sshfs_command(
        "/usr/bin/sshfs",
        "files.example",
        "eric",
        "2222",
        "/home/eric/.ssh/id_ed25519",
        "/home/eric/mnt/web01",
        "/run/user/1000/gcm/sshfs-web01.log",
    )

    assert command == [
        "/usr/bin/sshfs",
        "-p",
        "2222",
        "-o",
        "reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,ConnectTimeout=15,"
        "ssh_command=ssh -E /run/user/1000/gcm/sshfs-web01.log,"
        "IdentityFile=/home/eric/.ssh/id_ed25519",
        "eric@files.example:",
        "/home/eric/mnt/web01",
    ]


def test_without_a_port_key_or_log_sshfs_is_given_none():
    command = remotefiles.sshfs_command(
        "sshfs", "files.example", "eric", " ", "", "/home/eric/mnt/web01", None
    )

    assert command == [
        "sshfs",
        "-o",
        "reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,ConnectTimeout=15",
        "eric@files.example:",
        "/home/eric/mnt/web01",
    ]


def test_a_comma_in_a_value_is_escaped_and_a_space_in_a_key_quoted():
    """Measured with sshfs 3.7.3 and libfuse 3.14: `\\,` reached ssh as a comma and `\\\\`
    as a backslash. ssh refused a key path holding a space unless it was quoted."""
    command = remotefiles.sshfs_command(
        "sshfs", "h", "u", "22", "/keys/a b,c\\d", "/m", "/logs,x/sshfs-m.log"
    )
    options = command[command.index("-o") + 1]

    assert options.endswith(
        'ssh_command=ssh -E /logs\\,x/sshfs-m.log,IdentityFile="/keys/a b\\,c\\\\d"'
    )


def test_ssh_logs_to_the_first_folder_without_whitespace_or_a_backslash():
    """sshfs splits ssh_command at spaces, and measured, no escaping got one through. Its
    source reads a backslash there as escaping the next character."""
    log = remotefiles.ssh_log(["/run/user/1000/gcm", "/home/eric/.cache/gcm"], "probe box\twide")

    assert log == Path("/run/user/1000/gcm/sshfs-probe_box_wide.log")
    assert remotefiles.ssh_log(
        ["/home/My Name/.cache/gcm", "/home/eric/.cache/gcm"], "web01"
    ) == Path("/home/eric/.cache/gcm/sshfs-web01.log")
    assert remotefiles.ssh_log(["/home/My Name/.cache/gcm"], "web01") is None
    assert remotefiles.ssh_log(["/home/back\\slash/gcm"], "web01") is None


MOUNTINFO = (
    "23 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw\n"
    "228 82 0:78 / /home/eric/mnt/web01 rw,nosuid,nodev,relatime - fuse.sshfs "
    "eric@files.example: rw,user_id=1000,group_id=1000\n"
    "229 82 0:79 / /home/eric/mnt/my\\040files rw,nosuid,nodev,relatime - fuse.sshfs "
    "tester@[2001:db8::7]: rw,user_id=1000,group_id=1000\n"
    "230 82 0:80 / /home/eric/mnt/back\\134slash rw shared:9 master:2 - tmpfs a\\040b rw\n"
    "not a mount table line\n"
)


def test_the_mount_table_names_a_mounts_type_and_source():
    assert remotefiles.mount_at(MOUNTINFO, "/home/eric/mnt/web01") == (
        "fuse.sshfs",
        "eric@files.example:",
    )
    assert remotefiles.mount_at(MOUNTINFO, Path("/home/eric/mnt/web01")) == (
        "fuse.sshfs",
        "eric@files.example:",
    )


def test_the_mount_tables_escapes_are_read():
    """Measured, the kernel writes a space in a mount point as \\040."""
    assert remotefiles.mount_at(MOUNTINFO, "/home/eric/mnt/my files") == (
        "fuse.sshfs",
        "tester@[2001:db8::7]:",
    )
    assert remotefiles.mount_at(MOUNTINFO, "/home/eric/mnt/back\\slash") == ("tmpfs", "a b")


def test_nothing_mounted_at_a_folder_is_none():
    assert remotefiles.mount_at(MOUNTINFO, "/home/eric/mnt/web02") is None
    assert remotefiles.mount_at(MOUNTINFO, "/home/eric/mnt/my\\040files") is None
    assert remotefiles.mount_at("", "/home/eric/mnt/web01") is None


def test_of_two_mounts_at_a_folder_the_one_on_top_counts():
    table = MOUNTINFO + (
        "231 228 0:81 / /home/eric/mnt/web01 rw - fuse.sshfs ops@other.example: rw\n"
    )

    assert remotefiles.mount_at(table, "/home/eric/mnt/web01") == (
        "fuse.sshfs",
        "ops@other.example:",
    )


@pytest.mark.parametrize(
    ("ssh_log", "sshfs_output", "reason"),
    [
        # Each measured against a real sshd.
        ("Host key verification failed.\n", "read: Connection reset by peer\n", None),
        (
            "Permission denied, please try again.\nPermission denied, please try again.\n"
            "eric@127.0.0.1: Permission denied (publickey,password).\n",
            "read: Connection reset by peer\n",
            "eric@127.0.0.1: Permission denied (publickey,password).",
        ),
        ("", "fuse: bad mount point `/m': No such file or directory\n", None),
        ("\n  \n", "", ""),
    ],
)
def test_a_failure_is_explained_by_ssh_first(ssh_log, sshfs_output, reason):
    if reason is None:
        reason = (ssh_log or sshfs_output).strip()
    assert remotefiles.failure_reason(ssh_log, sshfs_output) == reason


# -- the askpass helper -----------------------------------------------------------------


def ask(question, password: str | None = "s3cret; $HOME 'x' \"y\""):
    environment = dict(os.environ)
    environment.pop(placeholders.PASSWORD_VARIABLE, None)
    if password is not None:
        environment[placeholders.PASSWORD_VARIABLE] = password
    return subprocess.run(
        [str(ASKPASS), question], capture_output=True, text=True, env=environment, timeout=10
    )


@pytest.mark.parametrize(
    "question",
    [
        # ssh's own, measured against a real sshd, and the keyboard-interactive forms.
        "endavis@127.0.0.1's password: ",
        "(eric@files.example) Password: ",
        "Password:",
    ],
)
def test_a_password_prompt_gets_the_stored_password_as_it_is(question):
    answered = ask(question)

    assert answered.returncode == 0
    assert answered.stdout == "s3cret; $HOME 'x' \"y\"\n"


@pytest.mark.parametrize(
    "question",
    [
        # Measured: ssh asks this through askpass under SSH_ASKPASS_REQUIRE=force.
        "The authenticity of host '[127.0.0.1]:44765 ([127.0.0.1]:44765)' can't be "
        "established.\nED25519 key fingerprint is SHA256:r5WU4VkF7sQfb110k2SJzmzWo3hLwCNpw"
        "Sd1YzVtH9Q.\nThis key is not known by any other names.\nAre you sure you want to "
        "continue connecting (yes/no/[fingerprint])? ",
        "Enter passphrase for key '/home/eric/.ssh/id_ed25519': ",
        "Verification code: ",
        "",
    ],
)
def test_any_other_question_is_refused(question):
    answered = ask(question)

    assert answered.returncode != 0
    assert answered.stdout == ""


def test_with_no_stored_password_a_password_prompt_is_refused():
    for password in (None, ""):
        answered = ask("eric@files.example's password: ", password)
        assert answered.returncode != 0
        assert answered.stdout == ""


def test_the_helper_reads_the_variable_gcm_puts_the_password_in():
    assert f'"${placeholders.PASSWORD_VARIABLE}"' in ASKPASS.read_text()


# -- packaging --------------------------------------------------------------------------


def test_every_script_is_installed_and_executable():
    """ssh runs the helper itself, so a copy installed without its mode runs nothing."""
    makefile = (REPO / "Makefile").read_text()
    for script in sorted((REPO / "data" / "scripts").iterdir()):
        assert os.access(script, os.X_OK), script
        assert re.search(rf"^\tcp data/scripts/{re.escape(script.name)} ", makefile, re.M), script
        assert re.search(rf"^\tchmod \+x .*/scripts/{re.escape(script.name)}$", makefile, re.M), (
            script
        )
