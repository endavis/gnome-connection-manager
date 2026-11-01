---
title: "Packaging, the Installer and Releases"
description: "Why the .deb and the .rpm declare what they do and run no script, how install.sh installs and updates GCM, and what a release is, with what was measured of each"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - design
---

# Packaging, the Installer and Releases

Design notes for how GCM reaches a machine: the `.deb` and the `.rpm` the `Makefile` builds,
which `tools/packages.py` reads, the one-line installer `install.sh`, and a release. They say
why each choice was made, what was measured and with which versions, and what was rejected.
How to cut a release is `.github/CONTRIBUTING.md` (Release Process). These notes were moved
here from `AGENTS.md` (#430).

## The packages run no script

No package runs a script (#273). The `.deb`'s `postinst` ran `xdg-desktop-menu`, which
needs xdg-utils, only suggested, and a menu folder to write to. Measured in Ubuntu
24.04: without xdg-utils it exited 127, and without `/usr/share/desktop-directories` 3,
each leaving the package half-configured, and where `/usr/local/share/applications`
existed it put a copy of the entry there that no package owns. The entry needs none:
dpkg's desktop-file-utils trigger, and Fedora's file trigger, update the desktop
database for `/usr/share/applications`. `tests/test_packages.py` fails on a script in
either recipe.

## The rpm's names

The `rpm` recipe names the `.deb`'s packages by Fedora's names, checked in Fedora 43's
and 44's repositories: `python3-gobject` holds the cairo integration, `freerdp` installs
FreeRDP 3 as `xfreerdp`, `fuse-sshfs` is sshfs, and `gvfs` holds the sftp backend. fpm
has no option for an rpm's weak dependencies, so they are `--rpm-tag 'Recommends: …'`
and `'Suggests: …'`, which rpm 4.18.2 reads back, measured. The `.rpm` has been built
and read on Ubuntu, never installed on Fedora. Neither package names a VNC viewer, which
GCM runs only where gtk-vnc, which both install, is missing (#302, #273). A package
added to a recipe goes in the README's tables, under both names, and
`tests/test_packages.py` fails until it is.

## What the packages declare

`tools/packages.py` gives what the `.deb` and the `.rpm` declare, read from the Makefile's
`deb` and `rpm` recipes, the one list of what GCM needs and can use (#273). Given the
two built packages, it holds what fpm wrote into them to the recipes, as CI's `package`
job does, and `--names deb` lists every package the `.deb` names, which that job asks
apt for. `tests/test_packages.py` holds the README's tables and `tests/test_install.py`'s
lists to the same reading.

## The installer

`install.sh` is the one-line installer (#294), served from `main` and piped to bash. It
clones the repository bare into `~/.local/share/gnome-connection-manager/repo`, adds
each version as a worktree under `versions/`, and moves the link `current` to the one
in use. An update never changes a version's files, since a running GCM reads its glade
file for every dialog and runs `data/scripts/ssh.expect` for each tab. The launcher it
writes, `~/.local/bin/gnome-connection-manager`, resolves `current` once and holds a
shared `flock` on that version while GCM runs, and drops the `GCM_*_DIR` a GCM started
from another's tab inherits. An update keeps the version it replaces, as `previous`,
and removes an older one only if it can lock it exclusively. Measured: `flock(1)`
creates a file at a path that does not exist, so it is given only folders found; and
git exits 128 in a folder that is gone, `Unable to read current working directory`, so
the script works from `/`, as it may remove the one it was run from. The packages come
from the version's own `Makefile`, the `deb` recipe's `-d` and `--deb-recommends`, and
git. Its `--deb-suggests` are GCM's optional programs (#302), which `want_optional`
offers, asking once for all those missing. It asks on `/dev/tty`, since piped, the
script's input is the script, and with no terminal it asks nothing and installs none.
On a yes they are installed in an `apt-get install` of their own, after what GCM needs,
so that apt failing on one leaves GCM installed. Everything runs from a `main` called
on the last line, in braces: a download cut short just after `main` would run it
without its arguments. GLib's `get_executable` reads a quoted Exec up to the first
space, quote included, measured, so the desktop entry quotes the launcher's path only
where it must.

## Testing the installer

`tests/test_install.py` pipes it to bash against a repository of the test's own, with
`sudo`, `apt-get` and `dpkg-query` faked and `awk` as mawk, which a new Ubuntu has.
Each scenario runs in a session of its own, with no terminal: measured, run from a
developer's terminal without that, the script asked its question there. One that
answers it runs on a pty of its own, which `TAKE_TERMINAL` makes its controlling
terminal.

## Releases

A release is a `vX.Y.Z` tag on `main`, made through a `release/vX.Y.Z` PR as
`.github/CONTRIBUTING.md` (Release Process) describes (#291). `cz bump --files-only`
writes the version into the four files `tests/test_package.py` keeps equal, which
`[tool.commitizen]` in `pyproject.toml` names, and the test fails if the two lists part.
The same section's `update_changelog_on_bump = false` keeps `CHANGELOG.md` hand-written
(#311). Measured, `true` has `cz bump --files-only` write the changelog too, from commit
subjects. False is commitizen's default, and the template's `doit release` reads a
missing key so since pyproject-template#992, so only `tests/test_package.py` would
notice the key go. Not `doit release`, as yet. Before #324 it wrote no version, and its
`cz changelog --incremental`, tried on a copy, replaced `CHANGELOG.md`'s hand-written
`## [Unreleased]` with commit subjects. `--dry-run` showed only the new section, which
hid that. The version #324 synced is meant to bump a static version with
`cz bump --files-only` and to keep a hand-written changelog (pyproject-template#992),
which is GCM's case, but it has not been tried here. `doit release_tag` tags the tip of
`main`, so run it straight after the release PR merges. A person runs it:
`tools/hooks/ai/block-dangerous-commands.py` refuses it from an agent.

## What the installer installs

`install.sh` installs the newest of those tags, so a release reaches every install the
next time it runs, and the script itself reaches new installs as soon as it merges. A
package the `.deb` needs goes in the Makefile's `deb` recipe, which the script reads,
and in `PACKAGES` in `tests/test_install.py`, which checks what it installs. An
optional program goes there as `--deb-suggests`, and in `OPTIONAL`. Alternatives are
one quoted word, `'freerdp3-x11|freerdp2-x11'`, as the script reads the recipe a word
at a time: it counts any one installed as enough, else installs the first, and the
others go in `ALTERNATIVES`. Measured with fpm 1.18.0, dpkg 1.22.6 and apt 2.8.3, fpm
writes one into the control file as given, and dpkg and apt read `a|b` as they read
`a | b`, which is how `dpkg-deb -f` gives it back. A run following
`release` reads the recipe of the release it installs, so a change there reaches it
only with the next release.
