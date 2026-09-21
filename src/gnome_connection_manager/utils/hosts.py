"""The stored-host model and its INI serialization.

`Host` is the record behind one entry in the tree: connection details, tunnels, terminal
overrides, colors and command sequences. `HostUtils` reads and writes it to the
`configparser` object backing gcm.conf.

Pure by design, so it is tested directly rather than through the `gi` stub in
tests/conftest.py (#138). Two things stayed in app.py to make that possible, and both
are now arguments rather than hidden defaults: the passphrase, which `get_password()`
derives from a module global, and whether a stored value predates the v2 format, which
is `conf.VERSION`.

Keep `Host.clone`, `save_host_to_ini`, the `Whost` dialogs and import/export in step:
adding an attribute means touching all four.

Every record carries an `id` (ADR-0001). It is the one attribute not derived from what the
user typed: identity used to be the `(group, name)` pair plus a section number that is
renumbered on every write, so nothing outside a record could refer to a host and still be
right after a rename.
"""

from __future__ import annotations

import configparser
import secrets

from gnome_connection_manager.utils import crypto
from gnome_connection_manager.utils.folders import parse_position

HOST_ID_BYTES = 4


def new_host_id():
    """Mint a host id: eight random hex characters.

    Random rather than sequential because GCM imports. `on_importar_servidores1_activate`
    replaces the whole host list from an exported config whose ids were minted in another
    install, so a counter would hand out values that are already in use here. Eight hex
    characters do not collide in practice across a config holding tens to hundreds of
    entries, and `ensure_unique_ids` catches it when they do (ADR-0001).
    """
    return secrets.token_hex(HOST_ID_BYTES)


# int(Vte.EraseBinding.AUTO), measured as 0 against VTE 2.91. Held as a plain int so
# this module needs no gi import; tests/test_hosts.py asserts it still matches the real
# enum, which is the check that catches the value drifting.
ERASE_BINDING_AUTO = 0


class Host:
    def __init__(self, *args):
        # Before the try: its bare except leaves every attribute after the failure
        # unset, and an id is the one attribute no consumer should have to test for.
        self.id = ""
        self.folder = ""
        self.position: int | None = None
        try:
            self.i = 0
            self.group = self.get_arg(args, None)
            self.name = self.get_arg(args, None)
            self.description = self.get_arg(args, None)
            self.host = self.get_arg(args, None)
            self.user = self.get_arg(args, None)
            self.password = self.get_arg(args, None)
            self.private_key = self.get_arg(args, None)
            self.port = self.get_arg(args, 22)
            self.tunnel = self.get_arg(args, "").split(",")
            self.type = self.get_arg(args, "ssh")
            self.commands = self.get_arg(args, None)
            self.keep_alive = self.get_arg(args, 0)
            self.font_color = self.get_arg(args, "")
            self.back_color = self.get_arg(args, "")
            self.x11 = self.get_arg(args, False)
            self.agent = self.get_arg(args, False)
            self.compression = self.get_arg(args, False)
            self.compressionLevel = self.get_arg(args, "")
            self.extra_params = self.get_arg(args, "")
            self.log = self.get_arg(args, False)
            self.backspace_key = self.get_arg(args, ERASE_BINDING_AUTO)
            self.delete_key = self.get_arg(args, ERASE_BINDING_AUTO)
            self.term = self.get_arg(args, "")
            # Positionally last before `id`: every caller passes the arguments
            # positionally, so a new attribute goes on the end. Defaults False so a Host
            # built with no commands is not described as running them.
            self.commands_enabled = self.get_arg(args, False)
            # After commands_enabled, for the same reason. Absent or empty means the
            # record predates ADR-0001 and is minted one below, which is the whole of the
            # migration: a config gets ids by being read, with no version bump.
            self.id = self.get_arg(args, "")
            # The id of the folder this host is filed under (ADR-0002); `group` is the
            # path derived from it. Empty until FolderTree.bind resolves `group`.
            self.folder = self.get_arg(args, "")
            # Last. Where it sits among that folder's children, or None for name order.
            self.position = self.get_arg(args, None)
        except (IndexError, ValueError, AttributeError):
            pass
        if not self.id:
            self.id = new_host_id()

    def get_arg(self, args, default):
        arg = args[self.i] if len(args) > self.i else default
        self.i += 1
        return arg

    def __repr__(self):
        return f"group=[{self.group}],\t name=[{self.name}],\t host=[{self.host}],\t type=[{self.type}]"

    def tunnel_as_string(self):
        return ",".join(self.tunnel)

    def clone(self):
        """A copy of this record as a separate entry.

        The id is deliberately not carried: a clone is a second host, and two entries
        sharing an id is the thing `ensure_unique_ids` exists to undo. The folder is: the
        copy is filed beside the original. The position is not, since two siblings cannot
        hold one place; a duplicate in the tree is placed by the caller.
        """
        return Host(
            self.group,
            self.name,
            self.description,
            self.host,
            self.user,
            self.password,
            self.private_key,
            self.port,
            self.tunnel_as_string(),
            self.type,
            self.commands,
            self.keep_alive,
            self.font_color,
            self.back_color,
            self.x11,
            self.agent,
            self.compression,
            self.compressionLevel,
            self.extra_params,
            self.log,
            self.backspace_key,
            self.delete_key,
            self.term,
            self.commands_enabled,
            "",
            self.folder,
        )


class HostUtils:
    @staticmethod
    def get_val(cp, section, name, default):
        try:
            return (
                cp.get(section, name)
                if not isinstance(default, bool)
                else cp.getboolean(section, name)
            )
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return default

    @staticmethod
    def load_host_from_ini(cp, section, pwd, *, legacy=False):
        """Read one host. `pwd` and `legacy` are the caller's to supply.

        They used to be defaulted here from `get_password()` and `conf.VERSION`, both of
        which live in app.py -- the two couplings that kept this out of utils/ (#138).
        """
        group = cp.get(section, "group")
        name = cp.get(section, "name")
        host = cp.get(section, "host")
        user = cp.get(section, "user")
        password = crypto.decrypt(pwd, cp.get(section, "pass"), legacy=legacy)
        description = HostUtils.get_val(cp, section, "description", "")
        private_key = HostUtils.get_val(cp, section, "private_key", "")
        port = HostUtils.get_val(cp, section, "port", "22")
        tunnel = HostUtils.get_val(cp, section, "tunnel", "")
        ctype = HostUtils.get_val(cp, section, "type", "ssh")
        commands = (
            HostUtils.get_val(cp, section, "commands", "")
            .replace("\x00", "\n")
            .replace("\\n", "\n")
        )
        keepalive = HostUtils.get_val(cp, section, "keepalive", "")
        fcolor = HostUtils.get_val(cp, section, "font-color", "")
        bcolor = HostUtils.get_val(cp, section, "back-color", "")
        x11 = HostUtils.get_val(cp, section, "x11", False)
        agent = HostUtils.get_val(cp, section, "agent", False)
        compression = HostUtils.get_val(cp, section, "compression", False)
        compressionLevel = HostUtils.get_val(cp, section, "compression-level", "")
        extra_params = HostUtils.get_val(cp, section, "extra_params", "")
        log = HostUtils.get_val(cp, section, "log", False)
        backspace_key = int(HostUtils.get_val(cp, section, "backspace-key", ERASE_BINDING_AUTO))
        delete_key = int(HostUtils.get_val(cp, section, "delete-key", ERASE_BINDING_AUTO))
        term = HostUtils.get_val(cp, section, "term", "")
        # Written since #151. Before it the text was the flag -- the dialog cleared
        # `commands` when the box was unticked -- so an entry with no key predates the
        # split and its stored commands were being run.
        commands_enabled = HostUtils.get_val(cp, section, "commands-enabled", commands != "")
        # Absent before ADR-0001. Host() mints one when this is empty, so reading an old
        # config is the migration; the value lands in the file at the next write.
        host_id = HostUtils.get_val(cp, section, "id", "")
        # Absent before ADR-0002; FolderTree.bind resolves `group` for it instead.
        folder = HostUtils.get_val(cp, section, "folder", "")
        # Written only for a host in a folder the user has arranged.
        position = parse_position(cp.get(section, "position", fallback=None))
        h = Host(
            group,
            name,
            description,
            host,
            user,
            password,
            private_key,
            port,
            tunnel,
            ctype,
            commands,
            keepalive,
            fcolor,
            bcolor,
            x11,
            agent,
            compression,
            compressionLevel,
            extra_params,
            log,
            backspace_key,
            delete_key,
            term,
            commands_enabled,
            host_id,
            folder,
            position,
        )
        return h

    @staticmethod
    def save_host_to_ini(cp, section, host, pwd):
        """Write one host. `pwd` is the caller's to supply, as for load_host_from_ini."""
        cp.set(section, "group", host.group)
        cp.set(section, "name", host.name)
        cp.set(section, "description", host.description)
        cp.set(section, "host", host.host)
        cp.set(section, "user", host.user)
        cp.set(section, "pass", crypto.encrypt(pwd, host.password))
        cp.set(section, "private_key", host.private_key)
        cp.set(section, "port", host.port)
        cp.set(section, "tunnel", host.tunnel_as_string())
        cp.set(section, "type", host.type)
        cp.set(section, "commands", host.commands.replace("\n", "\\n"))
        cp.set(section, "keepalive", host.keep_alive)
        cp.set(section, "font-color", host.font_color)
        cp.set(section, "back-color", host.back_color)
        cp.set(section, "x11", host.x11)
        cp.set(section, "agent", host.agent)
        cp.set(section, "compression", host.compression)
        cp.set(section, "compression-level", host.compressionLevel)
        cp.set(section, "extra_params", host.extra_params)
        cp.set(section, "log", host.log)
        cp.set(section, "backspace-key", host.backspace_key)
        cp.set(section, "delete-key", host.delete_key)
        cp.set(section, "term", host.term)
        cp.set(section, "commands-enabled", host.commands_enabled)
        cp.set(section, "id", host.id)
        cp.set(section, "folder", host.folder)
        if host.position is not None:
            cp.set(section, "position", str(host.position))

    @staticmethod
    def ensure_unique_ids(hosts):
        """Give every host a distinct id, reassigning the ones that collide.

        `Host` mints an id for any record that arrives without one, so a fresh read is
        already unique. This covers what a read cannot: gcm.conf is a text file people
        edit and merge by hand, and an imported export carries ids minted in another
        install. A repeated id would silently alias two entries the first time anything
        looked a host up by one.

        The first holder keeps the id and later ones are reassigned, so the outcome does
        not depend on how often this runs. Returns the hosts that were reassigned.
        """
        seen = set()
        reassigned = []
        for host in hosts:
            if not host.id or host.id in seen:
                host.id = new_host_id()
                while host.id in seen:
                    host.id = new_host_id()
                reassigned.append(host)
            seen.add(host.id)
        return reassigned
