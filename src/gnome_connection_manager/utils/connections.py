"""Connection types: what makes an SSH, Telnet, RDP, VNC, local or command host different
(#228).

Each type is a class, and `CONNECTION_TYPES` lists them in the order the host dialog
offers them. Code that used to compare `host.type` with a name asks the type instead:
`addTab` for the command to run, the host dialog for the fields that apply, and
`host_sends_commands` for whether commands follow a login. A new type adds a class here,
not a branch in each of those.

A type whose tab is not a terminal has its page in app.py's `TYPE_PAGES`, by the type's
id, since a page is made of widgets and this module imports no toolkit. VNC was the first
(#234). Its page is there only where gtk-vnc is installed, and where it is not, addTab
asks the type for `missing` and `command` as for any other: a VNC viewer, run in a
terminal tab.

A type may have settings of its own, each a `Setting`. The host dialog draws them on a
page of the type's own, and a host keeps them in `Host.type_settings`, which clone and
export and import carry already, so a new type adds no attribute to `Host`. A command
host's command line was the first (#248).

Pure: what a command needs from outside comes in as `Programs`, as the log root does for
logpaths, so every command is built and tested without a display. `ssh.expect` still
branches on the type's name, which each command passes it first.
"""

from __future__ import annotations

import configparser
import ipaddress
import re
import shlex
import shutil
from dataclasses import dataclass
from typing import cast

from gnome_connection_manager.utils import placeholders

# FreeRDP's X11 client, newest first. Ubuntu 24.04 installs FreeRDP 3's as xfreerdp3
# (freerdp3-x11) and FreeRDP 2's as xfreerdp (freerdp2-x11), side by side (#225).
RDP_CLIENTS = ("xfreerdp3", "xfreerdp")

# The VNC viewers a VNC host runs in, where gtk-vnc cannot draw it in the tab (#234).
# vncviewer is whichever one Debian's alternatives chose.
VNC_VIEWERS = ("vncviewer", "xtigervncviewer", "xtightvncviewer")


def N_(message: str) -> str:
    """Mark a message for translation. app.py translates it where it shows it."""
    return message


@dataclass(frozen=True)
class Programs:
    """What a command needs from outside this module. app.py fills it in for each spawn."""

    expect: str  # ssh.expect, which types a stored password
    username: str | None  # the local user, for an SSH host that names none
    ssh: str = "ssh"
    telnet: str = "telnet"


@dataclass(frozen=True)
class Command:
    """What addTab spawns: the argv, program first, a password for ssh.expect to type, and
    variables the program is given in its environment besides those it inherits.

    GCM types the password 2 s after the spawn, when it is neither empty nor None.
    """

    argv: list
    password: str | None
    environment: dict[str, str] | None = None

    @property
    def program(self) -> str:
        return cast("str", self.argv[0])


@dataclass(frozen=True)
class Setting:
    """A setting of a type's own. A flag when its default is a bool, which the host dialog
    draws as a check box, and text otherwise, drawn as an entry. A type that needs another
    kind of control adds it here."""

    key: str
    label: str  # marked with N_, and translated where the dialog draws it
    default: str | bool = ""

    def __post_init__(self):
        # configparser folds an option's name to lower case as it writes it, so a key in
        # mixed case would be written and then never found again, once GCM restarts.
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.key):
            raise ValueError(f"a setting's key is lower case, digits and hyphens: {self.key!r}")

    @property
    def is_flag(self) -> bool:
        return isinstance(self.default, bool)

    def value(self, text: str | None) -> str | bool:
        """The value a host stored as `text`. The default when it stored none, or when a
        flag's text is not one configparser reads as a bool."""
        if text is None:
            return self.default
        if self.is_flag:
            return configparser.RawConfigParser.BOOLEAN_STATES.get(text.lower(), self.default)
        return text


class ConnectionType:
    """What the rest of GCM asks about a kind of host."""

    id = ""
    default_port = "23"
    remote = True  # False for a local shell, which has no address, user, password or port
    # True for a type whose command runs whether or not the host has an address, as a
    # command host's does. A host of any other type without one opens a local shell: the
    # Local button's host is of type ssh.
    runs_without_address = False
    credentials = True  # whether a remote host's user and password are used
    arguments = True  # whether a remote host's extra arguments are, by the program it runs
    ssh_options = False  # keep-alive, X11, agent, compression, key and port forwarding
    sends_commands = True  # whether the host's commands are typed after it connects
    # False for a type opened outside GCM, with no tab: a web host's page opens in the
    # browser, from its url() rather than a command.
    opens_tab = True
    # Settings of the type's own, drawn on a page of the host dialog, whose tab is
    # settings_title, with settings_hint as a line of help under them, both marked with N_.
    settings: tuple[Setting, ...] = ()
    settings_title = ""
    settings_hint = ""

    def invalid(self, values: dict) -> str | None:
        """Why a host of this type cannot be saved with `values`, its settings by key,
        marked with N_, or None. The host dialog asks on OK."""
        return None

    def missing(self) -> str | None:
        """Why a host of this type cannot be opened here, marked with N_, or None.

        Not asked of a type app.py draws a page for, which needs nothing more."""
        return None

    def command(self, host, programs: Programs) -> Command:
        raise NotImplementedError(f"a {self.id or 'local'} host runs no command")

    def dropped(self, status: int, tail: str) -> bool:
        """Whether a session whose program exited with `status`, with `tail` the last
        lines of its tab, lost its connection rather than ended (#239). Never, unless a
        type can tell. The exit status, not the wait status VTE reports.

        Telnet cannot: measured, it exits 0 however its session ends, a server that dies
        included, and says the same as for a remote `exit`.
        """
        return False

    def refused(self, status: int, tail: str) -> bool:
        """Whether connecting was refused in a way trying again cannot help, such as a
        login or a host key. Reconnecting stops at one."""
        return False

    def url(self, host) -> str:
        raise NotImplementedError(f"a {self.id or 'local'} host opens in a tab")

    def option(self, key: str) -> str:
        """The name the setting `key` is saved under in a host's section."""
        return f"{self.id}.{key}"

    def settings_of(self, host) -> dict[str, str | bool]:
        """Each of this type's settings for `host`, by key: what it stored, or the default."""
        return {
            setting.key: setting.value(host.type_settings.get(self.option(setting.key)))
            for setting in self.settings
        }

    def stored_settings(self, values: dict) -> dict[str, str]:
        """What a host of this type keeps for `values`, which are by key: each setting that
        differs from its default, as text, by the name it is saved under. A default is not
        written, as a folder's order is not while it is name order."""
        return {
            self.option(setting.key): str(values[setting.key])
            for setting in self.settings
            if values[setting.key] != setting.default
        }


# How OpenSSH says an established connection was lost. Every ssh failure exits 255,
# the user's own `~.` included, so the line is what tells (#239). The first two were
# measured against a server that died and one that froze; the other two are formats the
# installed binary carries for the same, not measured. Not anchored to a line's start:
# measured, the message follows the remote prompt on its line.
SSH_LOST = re.compile(
    r"Connection to \S+ closed by remote host\.|Timeout, server \S+ not responding\."
    r"|Read from remote host |client_loop: send disconnect: "
)
# A refused login and a refused host key, each measured, exiting 255 as well.
SSH_REFUSED = re.compile(r"Permission denied|Host key verification failed\.")


class Ssh(ConnectionType):
    id = "ssh"
    default_port = "22"
    ssh_options = True

    def dropped(self, status: int, tail: str) -> bool:
        return status == 255 and SSH_LOST.search(tail) is not None

    def refused(self, status: int, tail: str) -> bool:
        return status == 255 and SSH_REFUSED.search(tail) is not None

    def command(self, host, programs: Programs) -> Command:
        if len(host.user) == 0:
            # Into the host itself, as addTab always has.
            host.user = programs.username
        if host.password == "":
            args = [programs.ssh, "-l", host.user, "-p", host.port]
        else:
            args = [programs.expect, host.type, "-l", host.user, "-p", host.port]
        if host.keep_alive != "0" and host.keep_alive != "":
            args.append("-o")
            args.append(f"ServerAliveInterval={host.keep_alive}")
        for t in host.tunnel:
            if t != "":
                if t.endswith(":*:*"):
                    args.append("-D")
                    args.append(t[:-4])
                else:
                    args.append("-L")
                    args.append(t)
        if host.x11:
            args.append("-X")
        if host.agent:
            args.append("-A")
        if host.compression:
            args.append("-C")
            if host.compressionLevel != "":
                args.append("-o")
                args.append(f"CompressionLevel={host.compressionLevel}")
        if host.private_key is not None and host.private_key != "":
            args.append("-i")
            args.append(host.private_key)
        if host.extra_params is not None and host.extra_params != "":
            args += shlex.split(host.extra_params)
        args.append(host.host)
        return Command(args, host.password)


class Telnet(ConnectionType):
    id = "telnet"

    def command(self, host, programs: Programs) -> Command:
        if host.user == "" or host.password == "":
            password = ""
            args = [programs.telnet]
        else:
            password = host.password
            # host.type rather than "telnet": a type GCM does not know opens as Telnet,
            # and has always passed ssh.expect its own name, which the script runs as ssh.
            args = [programs.expect, host.type, "-l", host.user]
        if host.extra_params is not None and host.extra_params != "":
            args += shlex.split(host.extra_params)
        args += [host.host, host.port]
        return Command(args, password)


class Rdp(ConnectionType):
    """FreeRDP shows the desktop in a window of its own. The tab shows what it prints,
    takes its questions and ends with its status (#225)."""

    id = "rdp"
    default_port = "3389"
    # Its tab runs FreeRDP, which has no shell to run them, and a command typed while
    # FreeRDP asks something is taken for the answer, to its certificate question or as
    # the password.
    sends_commands = False

    def dropped(self, status: int, tail: str) -> bool:
        # FreeRDP 3's status for `Network disconnect!`, measured for #225. Closing its
        # window exits 0.
        return status == 147

    def refused(self, status: int, tail: str) -> bool:
        # A logon failure, and a certificate not trusted, also measured for #225.
        return status in (134, 143)

    def missing(self) -> str | None:
        if rdp_client() is None:
            return N_(
                "Neither xfreerdp3 nor xfreerdp was found. Install FreeRDP to open RDP hosts."
            )
        return None

    def command(self, host, programs: Programs) -> Command:
        client = rdp_client()
        if host.user == "" or host.password == "":
            return Command([client, *rdp_arguments(host)], "")
        return Command([programs.expect, host.type, client, *rdp_arguments(host)], host.password)


class Local(ConnectionType):
    id = "local"
    remote = False


class Web(ConnectionType):
    """A web page, such as a BMC's console or an admin page, opened in the desktop's
    browser. GCM opens no tab for it (#231)."""

    id = "web"
    default_port = "443"
    # The page asks for a login itself, and no program runs to take arguments or commands.
    credentials = False
    arguments = False
    sends_commands = False
    opens_tab = False

    def missing(self) -> str | None:
        if shutil.which("xdg-open") is None:
            return N_("xdg-open was not found. Install xdg-utils to open web hosts.")
        return None

    def url(self, host) -> str:
        """The address, when it is a URL. Otherwise an https:// one: the host name, the
        port unless it is 443, and any path written after the host name."""
        address: str = host.host.strip()
        if "://" in address:
            return address
        name, slash, path = address.partition("/")
        if _is_ipv6(name):
            name = f"[{name}]"
        port = str(host.port).strip()
        if port not in ("", "443"):
            name = f"{name}:{port}"
        return f"https://{name}{slash}{path}"


class Vnc(ConnectionType):
    """A remote desktop over VNC. app.py draws it in the tab with gtk-vnc, and this is the
    fallback: a VNC viewer run in a terminal tab, which asks for the password itself.
    TigerVNC's asks in a window of its own and TightVNC's in the tab, measured (#234)."""

    id = "vnc"
    default_port = "5900"
    # A viewer has no shell to run them, and a tab gtk-vnc draws has no terminal.
    sends_commands = False

    def missing(self) -> str | None:
        if vnc_viewer() is None:
            # One literal, or tests/test_i18n.py cannot find it to check the catalogs.
            return N_(
                "Neither gtk-vnc's GObject bindings nor a VNC viewer was found. Install either to open VNC hosts."
            )
        return None

    def command(self, host, programs: Programs) -> Command:
        args = [vnc_viewer()]
        if host.extra_params:
            args += shlex.split(host.extra_params)
        # host::port is a port, where host:n is a display, 5900 + n. An IPv6 address is
        # bracketed: TigerVNC's viewer connects to [::1]::5951 and not to ::1::5951.
        name = f"[{host.host}]" if _is_ipv6(host.host) else host.host
        args.append(f"{name}::{host.port}")
        return Command(args, "")


class CustomCommand(ConnectionType):
    """A command line of the host's own, such as `mosh`, `kubectl exec` or `ipmitool …
    sol activate`, run through sh in a terminal tab (#248).

    It names the host's values as a command it runs on this computer does (#238), each
    quoted for the shell, and `{password}` too, which the command gets in its environment
    and never on a command line. Nothing is typed at a prompt: its prompts are unknown,
    and a password typed blind is how one reaches the wrong place.
    """

    id = "command"
    default_port = "22"
    runs_without_address = True
    # The line is the whole command, and there is nothing to add arguments to.
    arguments = False
    settings = (Setting("line", N_("Command"), ""),)
    settings_title = N_("Command line")
    settings_hint = N_(
        "{name}, {address}, {port}, {user}, {group} and {type} are the host's, each quoted for the shell. {password} is its password, given to the command as GCM_PASSWORD in its environment, never on a command line. It runs through sh, from your home folder."
    )

    def invalid(self, values: dict) -> str | None:
        if not str(values["line"]).strip():
            return N_("A command host needs a command, on its Command line tab.")
        return None

    def command(self, host, programs: Programs) -> Command:
        line, names_password = placeholders.fill_command(
            str(self.settings_of(host)["line"]),
            placeholders.host_values(host),
            quote=shlex.quote,
        )
        # Only to a command that asks for it, and empty for a host that stores none.
        environment = None
        if names_password:
            environment = {placeholders.PASSWORD_VARIABLE: host.password or ""}
        return Command(["sh", "-c", line], "", environment)


def _is_ipv6(name: str) -> bool:
    try:
        return ipaddress.ip_address(name).version == 6
    except ValueError:
        return False


SSH, TELNET, RDP, LOCAL, WEB, VNC = Ssh(), Telnet(), Rdp(), Local(), Web(), Vnc()
COMMAND = CustomCommand()
CONNECTION_TYPES = (SSH, TELNET, RDP, LOCAL, WEB, VNC, COMMAND)


def named(name: str | None) -> ConnectionType:
    """The type called `name`. One GCM does not know is Telnet, as it always has been.

    Found in CONNECTION_TYPES at each call rather than in a copy made at import, so a
    test that adds a type of its own is heard."""
    return next((kind for kind in CONNECTION_TYPES if kind.id == name), TELNET)


def for_host(host) -> ConnectionType:
    """What addTab opens `host` as.

    With no address, a local shell, unless its type runs without one: the Local button's
    host is of type ssh. A local host given an address, which the dialog never saves, is
    Telnet, as addTab has always opened one.
    """
    kind = named(host.type)
    if (host.host == "" or host.host is None) and not kind.runs_without_address:
        return LOCAL
    return kind if kind.remote else TELNET


def rdp_client() -> str | None:
    """The FreeRDP client an RDP host opens in, or None when none is installed."""
    return next((name for name in RDP_CLIENTS if shutil.which(name)), None)


def vnc_viewer() -> str | None:
    """The VNC viewer a VNC host runs in without gtk-vnc, or None when none is installed."""
    return next((name for name in VNC_VIEWERS if shutil.which(name)), None)


def rdp_arguments(host) -> list[str]:
    """FreeRDP's arguments for an RDP host: everything but the program and the password.

    Never the password. FreeRDP 3 masks /p: in its own argv once it has read it, measured,
    but not in its parent's, and a session runs under relay.py when raw recording or OSC
    52 is on. ssh.expect types a stored one at FreeRDP's prompt instead (#225).
    """
    args = [f"/v:{host.host}", f"/port:{host.port}"]
    if host.user:
        args.append(f"/u:{host.user}")
    if host.extra_params:
        args += shlex.split(host.extra_params)
    return args
