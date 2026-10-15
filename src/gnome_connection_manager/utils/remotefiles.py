"""A host's files outside its console: an `sftp://` address for the file manager, and an
sshfs mount under ~/mnt (#267). Only a type with `sftp` set offers them, which is SSH.

The address never holds the password: the file manager asks for it. sshfs is given it
through ssh's askpass, by `data/scripts/gcm-askpass`, which answers a password prompt with
the host's stored password from its environment and refuses every other question. The host
key question above all, which is the user's to answer in a console (#216): measured, ssh
then fails at once with "Host key verification failed." rather than waiting on a question
nobody sees, and under `StrictHostKeyChecking accept-new` it asks nothing.

Measured with sshfs 3.7.3: it mounts before it connects, and unmounts again if connecting
fails, so the mount says nothing about whether it worked. As a daemon, its default, it
exits 0 once connected, so its exit status does. And as a daemon it sends ssh's messages
nowhere, printing `read: Connection reset by peer` for every failure, so ssh writes them
to a log of its own, given with `ssh -E`, which `failure_reason` reads.

Pure: the home folder, the programs found and the mount table come in as arguments, so all
of it is tested without a display, a file manager or FUSE.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from gnome_connection_manager.utils.connections import is_ipv6
from gnome_connection_manager.utils.logpaths import sanitize_log_name

if TYPE_CHECKING:
    from collections.abc import Callable

# Tried in order where GIO knows no default application for folders, as on a system with
# no MIME cache. Read from the desktop files of Ubuntu 24.04's packages: each declares
# inode/directory and takes an address where its Exec line has %U or %u, and these are the
# arguments before it. None declares x-scheme-handler/sftp.
FILE_MANAGERS = (
    ("nautilus", "--new-window"),
    ("nemo",),
    ("caja", "--no-desktop"),
    ("thunar",),
    ("dolphin",),
    ("pcmanfm-qt",),
    ("pcmanfm",),
)

SSH_PORT = "22"
# How sshfs keeps a mount: it reconnects when the connection drops, and ServerAlive notices
# one that has, as sshfs's own documentation pairs them. ConnectTimeout bounds the wait for
# a host that does not answer, which is otherwise the kernel's: about 127 s, tcp(7) says,
# with tcp_syn_retries at 6, its default and the value on the machine this was written on.
SSHFS_OPTIONS = (
    "reconnect",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "ConnectTimeout=15",
)


def host_name(address: str) -> str:
    """The address as an `sftp://` address or sshfs names a host: an IPv6 one in brackets."""
    return f"[{address}]" if is_ipv6(address) else address


def sftp_address(address: str, user: str | None, port: str) -> str:
    """The `sftp://` address of a host's files. The user is quoted, so that an `@` or a `:`
    in it stays the user's, and the port is left out when it is SSH's own."""
    location = host_name(address)
    if user:
        location = f"{quote(user, safe='')}@{location}"
    port = str(port).strip()
    if port and port != SSH_PORT:
        location = f"{location}:{port}"
    return f"sftp://{location}/"


def file_manager_command(which: Callable[[str], str | None]) -> list[str] | None:
    """The first of FILE_MANAGERS that `which` finds, as the arguments to open an address
    with, or None."""
    for command in FILE_MANAGERS:
        program = which(command[0])
        if program:
            return [program, *command[1:]]
    return None


def mount_folder(home: str | Path, name: str) -> Path:
    """Where a host is mounted: ~/mnt/<its name>, made safe for a folder name as a session
    log's is, so that a `/` in it cannot reach another folder."""
    return Path(home, "mnt", sanitize_log_name(name))


def sshfs_source(address: str, user: str | None) -> str:
    """What sshfs mounts, the login folder, `user@host:`. The mount table names the mount
    by it, as given, measured: `tester@[2001:db8::7]:` for an IPv6 address."""
    location = host_name(address)
    return f"{user}@{location}:" if user else f"{location}:"


def read_as_option(address: str, user: str | None) -> bool:
    """Whether ssh would read the host it is given as an option, as with a user
    `-oProxyCommand=...`, which would run a command.

    Measured with sshfs 3.7.3: given `--` first, sshfs takes such a source as its host and
    hands it to ssh as it is, ahead of no `--`, and without one sshfs takes it for an
    option of its own. A console passes the user as `-l`'s value, where it is safe."""
    return sshfs_source(address, user).startswith("-")


def _option(text: str) -> str:
    """`text` as a value in sshfs's -o, where a comma would end it. Measured with libfuse
    3.14, `\\,` arrives as a comma and `\\\\` as a backslash."""
    return text.replace("\\", "\\\\").replace(",", "\\,")


def ssh_log(folders: list[str | Path], name: str) -> Path | None:
    """Where ssh writes its messages for the mount at a folder called `name`: in the first
    of `folders` whose path holds no whitespace and no backslash, or nowhere.

    sshfs 3.7.3 splits ssh_command at spaces, and measured, a space escaped once split it
    all the same, while one escaped twice reached ssh with the backslash, so ssh opened
    another file. Its source reads a backslash there as escaping the next character. A
    path with either cannot be given at all, and ssh fails at once when it cannot open
    its log, so then there is none, and only sshfs's own words."""
    for folder in folders:
        if not any(c.isspace() or c == "\\" for c in str(folder)):
            return Path(
                folder, "sshfs-" + "".join("_" if c.isspace() else c for c in name) + ".log"
            )
    return None


def sshfs_command(
    sshfs: str,
    address: str,
    user: str | None,
    port: str,
    key: str | None,
    folder: str | Path,
    log: str | Path | None,
) -> list[str]:
    """sshfs mounting a host's login folder at `folder`, with ssh writing its messages to
    `log`. The host's port and key file go along; its tunnels, forwarding and extra
    parameters do not, since sshfs makes a connection of its own."""
    options: list[str] = list(SSHFS_OPTIONS)
    if log is not None:
        options.append("ssh_command=" + _option(f"ssh -E {log}"))
    if key:
        # ssh reads the value as a line of its configuration, and measured, refused a path
        # with a space in it unless it was in double quotes.
        options.append(
            "IdentityFile=" + _option(f'"{key}"' if any(c.isspace() for c in key) else key)
        )
    command = [sshfs]
    port = str(port).strip()
    if port:
        command += ["-p", port]
    return [*command, "-o", ",".join(options), sshfs_source(address, user), str(folder)]


def _unescape(field: str) -> str:
    """A mount table field as it was: the kernel writes a space, a tab, a newline and a
    backslash in octal, a space as \\040, measured."""
    out, index = [], 0
    while index < len(field):
        code = field[index + 1 : index + 4]
        if field[index] == "\\" and len(code) == 3 and all(c in "01234567" for c in code):
            out.append(chr(int(code, 8)))
            index += 4
        else:
            out.append(field[index])
            index += 1
    return "".join(out)


def mount_at(mountinfo: str, folder: str | Path) -> tuple[str, str] | None:
    """The type and source of what is mounted at `folder`, from the text of
    /proc/self/mountinfo, or None. The last of several, which is the one on top."""
    found = None
    for line in mountinfo.splitlines():
        head, separator, tail = line.partition(" - ")
        fields, rest = head.split(" "), tail.split(" ")
        if separator and len(fields) > 4 and len(rest) > 1 and _unescape(fields[4]) == str(folder):
            found = (rest[0], _unescape(rest[1]))
    return found


def failure_reason(ssh_log: str, sshfs_output: str) -> str:
    """Why a mount failed: ssh's last line, which says why it ended, else sshfs's own.
    Measured: "Host key verification failed.", "...: Permission denied (publickey,password).",
    "ssh: connect to host 127.0.0.1 port 1: Connection timed out"."""
    for text in (ssh_log, sshfs_output):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""
