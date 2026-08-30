# Gnome Connection Manager

A tabbed SSH and telnet connection manager for GTK 3 desktop environments.

Requires Python 3.12+ and GTK 3, with PyGObject and VTE supplied by the distribution
rather than by pip — see [Developing](DEVELOPING.md) for the package list.

## Where to start

| | |
|---|---|
| [Terminal usage](TERMINAL-USAGE.md) | Selection when an application has taken the mouse, what Copy All copies, pasting, font zoom, and the shortcut table |
| [Developing](DEVELOPING.md) | Setting up an environment, the task runner, and running the tests |
| [Project structure](PROJECT_STRUCTURE.md) | What lives where |
| [Specification](SPEC.md) | Behaviour the implementation is held to |

## Template tooling

This project is built on [pyproject-template](https://github.com/endavis/pyproject-template).
The [Template](template/index.md) section documents the vendored tooling and how to take
updates from upstream.
