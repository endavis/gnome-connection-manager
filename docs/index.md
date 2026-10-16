---
title: "Gnome Connection Manager"
description: "What GCM is, and where to start reading"
audience:
  - gcm-users
tags:
  - gcm
  - gcm-guide
  - overview
---

# Gnome Connection Manager

A tabbed SSH, telnet and local-shell manager for GTK 3 desktop environments, which keeps
remote desktops, web consoles and any command line as hosts too.

Requires Python 3.12+ and GTK 3, with PyGObject and VTE supplied by the distribution
rather than by pip — see [Developing](DEVELOPING.md) for the package list.

## Where to start

| | |
|---|---|
| [Terminal usage](TERMINAL-USAGE.md) | What happens inside a tab: selection, copy and paste, session recording and transcripts, OSC 52, the buffer viewer, tab titles, consoles in windows of their own, typing into several consoles at once, tabs that need your attention, sessions that end or drop, font zoom, the shortcut table, snippets, and what GCM does with a `gcm.conf` it cannot read |
| [Hosts and folders](HOSTS-AND-FOLDERS.md) | The server tree: making and moving folders, putting it in order, and what export and import carry; the host dialog, commands on this computer, RDP, VNC, web and command hosts, and a host's files over SFTP and SSHFS |
| [Running on WSL](WSL-SETUP.md) | GCM on Windows, in Ubuntu 24.04 under WSL: installing it from a clone, a shortcut that starts it, keychain and D-Bus so that consoles, mounts and Nautilus share one SSH agent, Nautilus and sshfs, setting the scale by hand on a high-DPI screen, and the faults that are WSLg's |
| [Developing](DEVELOPING.md) | Setting up an environment, the task runner, and running the tests |
| [Project structure](PROJECT_STRUCTURE.md) | What lives where |
| [Specification](SPEC.md) | Behaviour the implementation is held to, written as a spec for a Qt 6 port that is **not** being built |

## Template tooling

This project is built on [pyproject-template](https://github.com/endavis/pyproject-template).
The [Template](template/index.md) section documents the vendored tooling and how to take
updates from upstream.
