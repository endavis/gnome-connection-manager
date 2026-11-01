---
title: "Developing on a Headless Machine"
description: "Coding GCM and running its full test suite on an Ubuntu 26.04 VM or LXC container with no screen, which steps each needs, and what stays on the Windows machine"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - development
---

# Developing on a Headless Machine

This guide sets up a machine with no screen to code GCM on, with agents such as Claude Code,
and to run its full test suite there. It covers two kinds of machine, which differ in what
they need:

- **A VM**: a full virtual machine with its own kernel.
- **An LXC container**: one that shares the host's kernel, as a Proxmox container does.

**What was measured.** The LXC path was set up and run on 2026-11-01, on an unprivileged
Proxmox container running Ubuntu 26.04.1 LTS, with 6 cores and 10 GB of memory. Everything
this guide gives as measured was measured there. **The VM path was not tried.** Where this
guide says what a VM needs, it is what a VM should need for want of the container's limits,
and it says so.

## Which one you have

```bash
systemd-detect-virt -c
```

- `lxc` is an LXC container; follow the steps marked **LXC**.
- `none` is not a container: a VM, or a machine of its own. Skip the steps marked **LXC**.

Each step below is marked **Both**, **LXC** or **VM**.

| Step | Applies to |
|---|---|
| [1. Container features](#1-container-features-lxc) | LXC |
| [2. System packages](#2-system-packages-both) | Both |
| [3. AppArmor](#3-apparmor-lxc) | LXC |
| [4. Tools](#4-tools-both) | Both |
| [5. Keep uv on the system Python](#5-keep-uv-on-the-system-python-both) | Both |
| [6. Clone and build the environment](#6-clone-and-build-the-environment-both) | Both |
| [7. Logins](#7-logins-both) | Both |
| [8. First run](#8-first-run-both) | Both |

## Why it can work

- **CI already runs headless.** CI's `test` job runs every test on GitHub's `ubuntu-24.04`
  runners, which have no display. pytest starts an Xvfb of its own, in `pytest_configure`
  in `tests/conftest.py`.
- **CI's package list is nearly complete.** CI fails a run on any skipped test, so
  `SYSTEM_PACKAGES` in `.github/workflows/ci.yml` lists what the suite needs beyond the
  runner image. The image brings a few more itself, `python3-venv` and `locales` among them,
  which a minimal machine lacks (step 2).
- **No desktop to take.** There is no screen for a window to open on, so an agent's run
  cannot take your keyboard or pointer.

## Ubuntu 26.04 against CI's 24.04

CI runs Ubuntu 24.04, and so does WSL on the Windows machine, where everything in
`AGENTS.md` was measured. The 26.04 column is what was installed on the container; the 24.04
column is what Launchpad lists for `noble`, read on 2026-11-01:

| | 24.04 (CI, WSL) | 26.04 (container) |
|---|---|---|
| Python | 3.12.3 | 3.14.4 |
| VTE | 0.76.0 | 0.84.0 |
| GTK 3 | 3.24.41 | 3.24.52 |
| PyGObject | 3.48.2 | 3.56.2 |
| Xvfb (xorg-server) | 21.1.12 | 21.1.22 |
| OpenSSH | 9.6p1 | 10.2p1 |
| gtk-vnc | 1.3.1 | 1.5.0 |
| TigerVNC | 1.13.1 | 1.15.0 |

What that means:

- **The suite passes on 26.04.** 11 tests failed there at first, with GCM working in each
  case, for five causes: glycin's `bwrap` for SVG icons, uutils coreutils, the wording of
  TigerVNC 1.15 and gtk-vnc 1.5, the title VTE 0.84's shell script sets, and a menu that takes
  a click later on GTK 3.24.52. #427 sets them out, and PR #431 made each test accept both
  versions.
- **CI stays the judge.** A PR merges on CI's result on 24.04. A test that fails only on
  26.04 points to one of two things: a real problem for GCM on 26.04, or another test tied to
  24.04's behaviour, as #427's were.
- **uv needs `UV_PYTHON`** (step 5).

## Setup

### 1. Container features (LXC)

The sshfs tests in `tests/test_host_files.py` mount through `/dev/fuse`, which an LXC
container does not have unless its host gives it one. Measured: before `fuse=1` the
container had no `/dev/fuse`. On the Proxmox host, as root:

```bash
pct config <id>                      # note the features: line
pct set <id> --features nesting=1,fuse=1
pct reboot <id>
```

- `--features` replaces the whole list, so keep what `pct config` already shows there, such
  as `keyctl=1`.
- Keep the container **unprivileged** (`unprivileged: 1`). FUSE in an unprivileged
  container mounts only inside the container's own mount namespace.
- Proxmox warns that a FUSE mount can get in the way of snapshot backups of a container. The
  tests unmount when they finish.

A VM has `/dev/fuse` from its own kernel and needs none of this.

### 2. System packages (Both)

These are CI's `SYSTEM_PACKAGES`, plus `git`, `locales` and `python3-venv`:

```bash
sudo apt install git locales python3-venv \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 xvfb gettext expect \
  gir1.2-gtk-vnc-2.0 tigervnc-standalone-server tigervnc-tools x11-xserver-utils \
  libxtst6 sshfs openssh-server
```

- `python3-venv`: `doit audit` runs pip-audit, which makes a virtual environment of its own
  with `python -m venv`. Measured without it: `The virtual environment was not created
  successfully because ensurepip is not available`, and `doit check` stops at `audit`
  before running a test.
- `locales` holds the sources from which the Spanish catalog test builds its locale with
  `localedef`.

### 3. AppArmor (LXC)

Ubuntu 26.04 ships AppArmor profiles for `ssh-keyscan` and `fusermount3`. In the container
both refused the program's use of a socket, measured:

- `ssh-keyscan` failed every connection with `write (127.0.0.1): Permission denied`, the
  system's own sshd included. `strace` shows its first `write` to the socket refused with
  `EACCES`. The `sshd` fixture in `tests/test_host_files.py` runs it, so every test using
  that fixture errors.
- `sshfs` failed with `fusermount3: file descriptor 3 is not a socket, can't send fuse fd`,
  outside GCM as well as in the tests.

With both profiles in complain mode, both worked and the tests passed. In the container, as
root:

```bash
apparmor_parser -r -C /etc/apparmor.d/ssh-keyscan /etc/apparmor.d/fusermount3
mkdir -p /etc/apparmor.d/force-complain
ln -s /etc/apparmor.d/ssh-keyscan /etc/apparmor.d/fusermount3 /etc/apparmor.d/force-complain/
```

- The first line applies at once and lasts until the container restarts. The links in
  `force-complain` are what AppArmor reads at boot to load a profile in complain mode; that
  they hold across a restart was not measured.
- Complain mode logs what the profile would refuse and refuses nothing, for those two
  programs in this container only.
- Why the profiles refuse there was not found: reading the loaded profiles and the kernel
  log needs the host. That the same profiles work on a VM, or on 26.04 outside a container,
  was not measured. On a VM, run step 8 first, and come back here only if the sshd or sshfs
  tests fail the same way.

### 4. Tools (Both)

- **uv:** run uv's own installer, `curl -LsSf https://astral.sh/uv/install.sh | sh`. CI
  uses the latest uv.
- **gh:** install it from GitHub's own apt repository, as `docs/install_linux.md` in
  `cli/cli` describes, not from Ubuntu. Ubuntu 26.04 packages gh 2.46.0; the container runs
  2.103.3 from `cli.github.com/packages`. The doit tasks use `gh` throughout, and nobody has
  checked them on 2.46.
- **Claude Code**, installed as its setup documentation says.
- **Any other agent CLI** the multi-agent skills use: Codex, Copilot or agy.

### 5. Keep uv on the system Python (Both)

`.python-version` pins 3.12.3, the version Ubuntu 24.04 has. Without `UV_PYTHON`, uv builds
`.venv` on a 3.12.3 of its own, without apt's packages, and GCM stops at
`ModuleNotFoundError: No module named 'gi'`. Measured on the container: the `.venv` a first
`uv sync` had built there was on uv's
`~/.local/share/uv/python/cpython-3.12.3-linux-x86_64-gnu`, with
`include-system-site-packages = false`.

Set the variable where every shell sees it, agents' shells included. Put this near the top of
`~/.bashrc`, **above** the lines that return early for a shell that is not interactive:

```bash
export UV_PYTHON=/usr/bin/python3
```

Measured on the container: a Claude Code session started after that line was added had
`UV_PYTHON` in its shell. The repository's hooks refuse an agent's edit to `~/.bashrc`, so
you make this one yourself. With direnv, `.envrc.local` works too: the repository's `.envrc`
reads it, and git ignores it, but it applies only in shells that direnv has loaded.

### 6. Clone and build the environment (Both)

Build it as CI does. If `.venv` already exists from a `uv sync` without `UV_PYTHON`, remove
it first:

```bash
git clone https://github.com/endavis/gnome-connection-manager.git ~/src/gnome-connection-manager
cd ~/src/gnome-connection-manager
rm -rf .venv
uv venv --system-site-packages --python /usr/bin/python3
uv sync --all-extras --dev
uv run doit pre_commit_install
```

`doit worktree` builds each worktree's `.venv` the same way.

### 7. Logins (Both)

- `gh auth login`, then `gh auth setup-git`, so that git pushes over HTTPS with gh's token.
  An SSH key with a `git@github.com:` remote works as well.
- `git config --global user.name` and `user.email`, as on the Windows machine.
- Claude Code's login, and the other agent CLIs'.

### 8. First run (Both)

```bash
uv run python -c 'import sys, gi; gi.require_version("Vte", "2.91"); from gi.repository import Vte; print(sys.version.split()[0], Vte.get_minor_version())'
uv run doit check
```

- **The first line** printed `3.14.4 84` on the container. If it fails with
  `No module named 'gi'`, `UV_PYTHON` did not reach that shell, or `.venv` predates it
  (step 6).
- **The tests** on the container, after steps 1 to 7, on `main` at 2cc5407 (after #431):
  `uv run pytest -n auto -q --no-cov` gave `4962 passed`, none failed or skipped, in
  2 min 26 s.
  - Before #431, a full `doit check` passed every task but `test`, whose 11 failures were
    #427's.
  - Before step 3, `doit test` alone gave `12 failed, 4857 passed, 1 error`. The extra two
    were the sshd fixture and the sshfs mount.
- **A failure** belongs to one of three kinds:
  - **GCM breaks on 26.04.** A user who upgrades will hit it, so file an issue.
  - **A test tied to 24.04.** What the test asserts changed between versions, and GCM still
    works, as in #427. File an issue for it.
  - **Setup.** A package, a variable or a permission is missing. Fix the machine.

## Working from the machine

- **Agents work as they do now.** They code, test and push there, and open PRs as before. CI
  checks each PR on 24.04.
- **Hand checks stay on the Windows machine.** Fetch the PR's branch there and run it, as for
  PR #423.
- **Plan for two full runs at once.** `implement-issues` runs two issues at a time by
  default. Each runs a full `doit check`, which uses every core (`pytest -n auto`).

## What stays on the Windows machine

- **WSLg's own behaviour:** the clipboard shared with Windows (#393, #412, #413), where
  windows open (#403, #424), and the steps of `docs/WSL-SETUP.md`.
- **Windows Remote Desktop**, `mstsc.exe`, whose real tests run on your work desktop.
- **Probes that must measure the real compositor.** `AGENTS.md` keeps those to `DISPLAY=:0`
  under WSLg.
- **Your own checks by hand.**

## Seeing GCM from the machine

None of these was tried:

- **Screenshots** of an Xvfb, which is how agents look at GCM now (`AGENTS.md`, under
  "Run the app for tracebacks").
- **X11 forwarding** with `ssh -X` from WSL, with WSLg as the X server.
- **xpra, or a VNC desktop** on the machine, for longer sessions.

## Sizing

- **The container:** a full `doit check` took 2 min 25 s on 6 cores, the tests 2 min 15 s of
  it.
- **The Windows machine:** a full `doit check` took 6 min 8 s and 5 min 57 s on 4 cores, for
  the branches of #419 and #403.
- **CI:** the `test` job took 4 min 9 s and 4 min 29 s for the same two PRs.
- **Memory:** the container has 10 GB. What a run and an agent use was not measured.

## A 24.04 container instead

An Ubuntu 24.04 container would match CI's versions exactly, which 26.04 no longer needs
for the suite to pass. It would need no `UV_PYTHON`, since its Python matches the pin. Not tried. As an LXC container it
needs step 1 for FUSE; whether 24.04's AppArmor profiles need step 3 was not measured.

## Open questions

- Whether a VM needs step 3.
- Whether the `force-complain` links hold across a restart.
- Whether the doit tasks work with gh 2.46.
- Whether GitHub offers an `ubuntu-26.04` runner, for a CI job on 26.04 beside the 24.04 one.
- How much memory an agent and a full run need.
