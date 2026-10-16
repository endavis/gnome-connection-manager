---
title: "Running GCM on Windows with WSL"
description: "Setting GCM up on Ubuntu 24.04 under WSL: installing it from a clone, starting it from a Windows shortcut, one SSH agent for consoles, mounts and Nautilus through keychain and D-Bus, SFTP and SSHFS, setting the scale by hand on a high-DPI screen, and the faults that are WSLg's"
audience:
  - gcm-users
tags:
  - gcm
  - gcm-guide
  - wsl
  - windows
  - setup
---

# Running GCM on Windows with WSL

GCM is a Linux program. On Windows it runs in Ubuntu under WSL 2, and WSLg, the part of
WSL that shows Linux windows, puts its window on the Windows desktop beside Windows' own.
This guide sets that up on a new Ubuntu:

- GCM itself, and a shortcut that starts it from Windows.
- One SSH agent that every console, mount and file manager window uses.
- Nautilus and sshfs, for a host's files.
- The scale a high-DPI screen needs when WSLg does not give it.

It was measured on Windows 11 (build 26200) with WSL 2.7.13.0, WSLg 1.0.73.2 and Ubuntu
24.04.4 LTS. A step that would have changed that machine was run with a scratch home, a
settings store of its own or a Windows temp folder instead, and a step that was not run at
all says so.
`wsl --list --online` also offers Ubuntu 26.04. The steps should be the same there, with
the one difference [Installing GCM](#installing-gcm) describes, but GCM has not been tried
on it.

## Before you start

In PowerShell, `wsl --version` lists the parts of WSL and their versions, WSLg among them:

```text
WSL version: 2.7.13.0
Kernel version: 6.18.33.2-2
WSLg version: 1.0.73.2
```

If Ubuntu is not installed yet, `wsl --install -d Ubuntu-24.04` installs it, by the name
`wsl --list --online` gives it. This guide started from one already installed.

The steps for [Nautilus](#opening-a-hosts-files-in-nautilus) need Ubuntu to run systemd,
which Microsoft's documentation says an Ubuntu from `wsl --install` does.
`ps -p 1 -o comm=` prints `systemd` when it does. If it prints anything else, add these
lines to `/etc/wsl.conf` with `sudo`, run `wsl --shutdown` in PowerShell, and open Ubuntu
again, as that documentation describes:

```ini
[boot]
systemd=true
```

The Ubuntu this guide was measured on ran systemd already, so these steps were not run for
it.

Each `apt install` below names every package it needs, including some that the program
using them only recommends. apt leaves a recommended package out when it is set to skip
recommendations, so install them by name even where apt would have added them.

## Installing GCM

```bash
sudo apt update
sudo apt install git curl python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 expect
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The installer puts `uv` in `~/.local/bin`, and adds a line to `~/.profile` and to
`~/.bashrc` that puts that folder on `PATH`. Open a new terminal so that the line takes
effect. Measured with a scratch home: a new terminal found `uv`, and so did a login shell,
which is what a shortcut starts. Then:

```bash
git clone https://github.com/endavis/gnome-connection-manager.git ~/src/gnome-connection-manager
cd ~/src/gnome-connection-manager
export UV_PYTHON=/usr/bin/python3
uv venv --system-site-packages
uv sync
uv run gnome-connection-manager
```

GCM's window opens, and it has made its configuration directory, `~/.config/gcm`, which
the README's [Configuration](../README.md#configuration) describes.

- **Clone into Ubuntu's own files**, as above, not into a Windows folder under `/mnt/c`.
  Microsoft's WSL documentation recommends that for speed.
- **`--system-site-packages`** lets the environment see the GTK and VTE bindings that apt
  installed. They are built for Ubuntu's own `python3` and cannot come from PyPI.
- **`UV_PYTHON=/usr/bin/python3`** keeps `uv` on that interpreter. The repository pins
  Python 3.12.3 in `.python-version`, which is the version Ubuntu 24.04 has, so there it
  changes nothing. On a release whose `python3` is another version, `uv sync` and `uv run`
  would rebuild the environment to match the pin, without the system's packages. GCM would
  then stop at `ModuleNotFoundError: No module named 'gi'`. This was measured by building
  the environment on Python 3.13 and running `uv sync` without the variable. With the
  variable set, the environment stays on the interpreter it names. GCM's own tests run on
  3.12 only.

To update GCM later:

```bash
cd ~/src/gnome-connection-manager
git pull
UV_PYTHON=/usr/bin/python3 uv sync
```

The README's [Installation](../README.md#installation) builds a `.deb` package instead,
which needs Ruby and `fpm`. This guide runs GCM from the clone, and only that route was
measured.

## Starting GCM from Windows

### A launcher

Save this as `~/bin/gcm.sh`:

```bash
#!/bin/bash
# GCM from its clone, on the Python that apt's GTK bindings are built for.
export UV_PYTHON=/usr/bin/python3
cd ~/src/gnome-connection-manager || exit 1
exec uv run gnome-connection-manager
```

Make it executable, and try it from a terminal:

```bash
chmod +x ~/bin/gcm.sh
~/bin/gcm.sh
```

### A shortcut

On the Windows desktop, right-click, choose **New ▸ Shortcut**, and give it this location,
with your Ubuntu user name in place of `<you>`:

```text
"C:\Program Files\WSL\wslg.exe" -d Ubuntu-24.04 /home/<you>/bin/gcm.sh
```

`wslg.exe` is what WSLg's own Start menu entries run. **Files**, the entry Nautilus gets,
is `wslg.exe -d Ubuntu-24.04 --cd "~" -- nautilus --new-window`. It starts a command with
the environment a login shell has, so `uv` is on `PATH` and keychain's agent, below, is
there too. `wsl.exe` does not. Measured with a script that reported both, started each
way: from `wslg.exe`, with or without `--`, it found `uv` and the agent. From `wsl.exe`,
plain, with `--` or with `-e`, it found neither, and the launcher stops at
`exec: uv: not found`.

In the shortcut's **Properties**:

- **Change Icon** takes a Windows `.ico` file. ImageMagick makes one from GCM's icon, and
  can write it straight into a Windows folder:

  ```bash
  sudo apt install imagemagick
  convert ~/src/gnome-connection-manager/data/icon.png \
      -define icon:auto-resize=128,64,48,32,16 /mnt/c/Users/<windows user>/gcm.ico
  ```

- **Shortcut key** starts GCM from anywhere in Windows. Windows keeps that key for itself,
  so GCM never receives it. Choose one that is not in GCM's
  [shortcut table](TERMINAL-USAGE.md#keyboard-shortcuts): `Ctrl+Shift+A`, set on a shortcut
  like this one, never reached GCM.

To have GCM in the Start menu, copy the shortcut into the folder **Win+R** opens for
`shell:programs`. WSLg's entries are there too, in a folder named `Ubuntu-24.04`.

**Each start is a GCM of its own.** Starting GCM again while it runs opens a second window
in a second process, rather than bringing the first one forward. Each writes its
configuration when it closes, the hosts included, so the one closed last writes over
whatever the other changed. Run one at a time.

## One SSH agent for everything: keychain

GCM's consoles run `ssh`, a mount with SSHFS runs `ssh`, and Nautilus runs `ssh` through
GVfs to open an `sftp:` address. Each finds the agent that holds your key through
`SSH_AUTH_SOCK`. keychain starts one `ssh-agent` and gives every shell that same one, so
the key's passphrase is asked for once each time WSL starts.

```bash
sudo apt install keychain
```

Ubuntu's `~/.bashrc` begins with a check that stops it early in a shell that is not
interactive:

```bash
# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac
```

The shell a shortcut starts is not interactive. So the agent must be set up **above** that
check, or GCM starts without it. Add this at the very top of `~/.bashrc`:

```bash
# One ssh-agent for every shell, and for programs started from Windows.
if command -v keychain >/dev/null; then
    eval "$(keychain --eval --quiet --noask)"
    # Programs that D-Bus and systemd start get it too, GVfs among them.
    dbus-update-activation-environment --systemd SSH_AUTH_SOCK
fi
```

Add this at the end, which only an interactive shell reaches. Use your key's file name in
`~/.ssh`:

```bash
# Load the key into the agent, asking for its passphrase only if it is not there yet.
keychain --quiet id_ed25519
```

`--noask` starts the agent, or finds the one already running, without asking for anything,
since a shell started from a shortcut has nobody to answer. The line at the end asks in
the first terminal you open, and not again. Measured with a throwaway key: the first shell
asked for the passphrase, and a second found the same agent with the key loaded and asked
nothing. The `dbus-update-activation-environment` line takes a few milliseconds. What it is
for is in [Nautilus and your key](#nautilus-and-your-key).

Check it in a new terminal. `ssh-add -l` should list your key, and `echo "$SSH_AUTH_SOCK"`
should print the same path in every terminal.

A key kept on the Windows side, in `C:\Users\<windows user>\.ssh`, has to be copied into
Ubuntu and made readable by you alone. `ssh` refuses a key that others can read, with
`WARNING: UNPROTECTED PRIVATE KEY FILE!`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cp /mnt/c/Users/<windows user>/.ssh/id_ed25519 ~/.ssh/
chmod 600 ~/.ssh/id_ed25519
```

Measured with a key placed in a Windows folder by Windows: it was copied in as 0744,
readable by others, and `ssh-keygen` refused it as too open. After `chmod 600` it read
the key.

## Opening a host's files in Nautilus

**Open in File Manager** needs a file manager, and so do **Open Folder** and **Open over
SFTP** in the Mounted tab. [A host's files](HOSTS-AND-FOLDERS.md#a-hosts-files) describes
all three. Nautilus, which Ubuntu calls Files, opens `sftp:` addresses through GVfs. GVfs's
SFTP support is in `gvfs-backends`, a package `nautilus` only recommends, so name both:

```bash
sudo apt install nautilus gvfs-backends
```

With no other file manager installed, Nautilus is then the application that opens folders,
which is where GCM sends an address: `xdg-mime query default inode/directory` prints
`org.gnome.Nautilus.desktop`. WSLg adds **Files (Ubuntu-24.04)** to the Start menu.

### Nautilus and your key

Nautilus does not run `ssh` itself. GVfs's daemon, `gvfsd`, does. `gvfsd` is a systemd user
service, started the first time a program asks for it, and it gets the environment systemd
holds at that moment, not that of the terminal Nautilus was started from. The
`dbus-update-activation-environment` line in
[keychain's setup](#one-ssh-agent-for-everything-keychain) puts `SSH_AUTH_SOCK` there.
Without it, Nautilus asks for a password where your key should have let you in. Measured
with the line in place: `gvfsd-sftp`, and the `ssh` it ran, both had the agent's socket.

To check that systemd has it:

```bash
systemctl --user show-environment | grep SSH_AUTH_SOCK
```

It should print the path `echo "$SSH_AUTH_SOCK"` does.

`gvfsd` keeps the environment it started with. If it was already running when you added
the lines to `~/.bashrc`, or the agent has been restarted since, restart `gvfsd`, then open
the address again:

```bash
systemctl --user restart gvfs-daemon
```

## Mounting a host with SSHFS

```bash
sudo apt install sshfs
```

That is all WSL 2 needs. `/dev/fuse` is open to every user and `fusermount3` is installed
setuid, so a mount needs no `sudo`: a test mount made as an ordinary user worked. **Mount
with SSHFS** then mounts a host at `~/mnt/<host name>`, as
[A host's files](HOSTS-AND-FOLDERS.md#a-hosts-files) describes. It uses keychain's agent,
since GCM runs `sshfs` with its own environment.

Accept a host's key before you mount it. A mount does not ask whether to trust a host key
ssh has never seen. It fails with **Host key verification failed.** instead. Connect to the
host once in a console and answer the question there.

Two things are particular to WSL:

- **A mount ends with WSL.** It lasts until you unmount it or WSL stops, as it does after
  `wsl --shutdown`.
- **Windows cannot open a mount.** Through
  `\\wsl.localhost\Ubuntu-24.04\home\<you>\mnt\<host name>`, PowerShell reported **Access is
  denied**, for a mount that listed in Ubuntu. FUSE keeps a mount to the user who made it.
  Open the files from Ubuntu instead, in Files or a console.

## Setting the scale on a high-DPI screen

WSLg tells Linux programs that every monitor is at scale 1, whatever Windows is set to.
This command prints what GTK is told:

```bash
python3 -c 'import gi; gi.require_version("Gdk", "3.0"); from gi.repository import Gdk
d = Gdk.Display.get_default()
for i in range(d.get_n_monitors()):
    m = d.get_monitor(i); g = m.get_geometry(); print(f"{g.width}x{g.height} scale {m.get_scale_factor()}")'
```

Here, it printed this, with Windows at 225% on a laptop's 2880×1920 screen, and two
1920×1080 monitors beside it:

```text
2880x1920 scale 1
1920x1080 scale 1
1920x1080 scale 1
```

GTK then draws GCM at 100%, less than half the size Windows draws its own windows at on
that screen. When the scale printed for your screen is lower than the one Windows uses,
set it by hand as follows. When it matches, leave it alone.

### GDK_DPI_SCALE, for GCM alone

Under WSLg, GTK draws through Wayland. There `GDK_SCALE`, the setting usually given for this,
does nothing: measured at 2 and at 2.25, a window's scale stayed at 1. `GDK_DPI_SCALE` does
work, and takes a fraction. Set it in the launcher, before the `exec` line:

```bash
export GDK_DPI_SCALE=2.25
```

At 2.25, GTK's resolution went from 96 to 216 dots per inch. A line of the interface's
text went from 21 pixels to 46, and a console's character cell, in Monospace 10, from 8×17
pixels to 18×36. It applies to GTK 3 programs only: Nautilus, which is GTK 4, ignores it.

### text-scaling-factor, for every GTK program

GNOME's text scaling setting does the same for GTK 3 and GTK 4 alike, so for GCM and
Nautilus both. It is kept from one session to the next:

```bash
gsettings set org.gnome.desktop.interface text-scaling-factor 2.25
```

Measured on Wayland, in a settings store of its own so that nothing else changed: for GTK 3
and for GTK 4, it gave the same 216 dots per inch and 46-pixel line as `GDK_DPI_SCALE=2.25`.
Restart GCM and Nautilus after changing it.
`gsettings reset org.gnome.desktop.interface text-scaling-factor` undoes it, and in that
store it brought the factor back to 1.0.

**Use one or the other, not both.** They multiply: with both at 2.25, GTK's resolution went
to 486 dots per inch and a console's cell to 41×79 pixels.

### GDK_SCALE, on X11

GTK can draw through X11 instead, given `GDK_BACKEND=x11`. There `GDK_SCALE` scales
everything, not just the text, but only by a whole number: 2.25 acts as 2.
`GDK_DPI_SCALE` scales GTK 3's text further, on top of that. A line of text 19 pixels tall
at scale 1 measured 38 pixels at `GDK_SCALE=2`, and 44 with `GDK_DPI_SCALE=1.125` as well.
On X11, `text-scaling-factor` is ignored. In the launcher:

```bash
export GDK_BACKEND=x11
export GDK_SCALE=2
export GDK_DPI_SCALE=1.125
```

Under WSLg, X11 looks different from Wayland, since GTK does not read GNOME's settings
there. Here it took the Yaru theme from Ubuntu's `/etc/gtk-3.0/settings.ini`, and the Sans
font. On Wayland it follows GNOME's settings, which
[The window's buttons and font](#the-windows-buttons-and-font) covers.

### Screens at different scales

WSLg reports every monitor at scale 1, so GTK has one scale for all of a program's windows.
With screens at different scales in Windows, make a launcher for each, such as
`~/bin/gcm-hidpi.sh`, and a shortcut for each launcher:

```bash
#!/bin/bash
# GCM for the screen Windows scales to 225%.
export GDK_DPI_SCALE=2.25
exec ~/bin/gcm.sh
```

Start only one GCM at a time, as [A shortcut](#a-shortcut) says.

### The consoles' font

Preferences sets the consoles' font, and `Ctrl+scroll` zooms a single console, as
[Font zoom](TERMINAL-USAGE.md#font-zoom) describes. Neither changes GCM's menus or dialogs.

## The window's buttons and font

On Wayland, GTK takes the title bar's buttons and the interface font from GNOME's settings.
In WSL those keep GNOME's defaults until you change them.

- **Minimize and maximize.** GNOME's default, `appmenu:close`, puts only a close button on
  the title bar. Set all three, once:

  ```bash
  gsettings set org.gnome.desktop.wm.preferences button-layout ":minimize,maximize,close"
  ```

  On X11, GTK shows all three already.

- **The font.** GNOME's default interface font is Cantarell 11, which may not be installed.
  Here it was not, and `fc-match Cantarell` named Noto Sans, the font that stands in for it.
  `sudo apt install fonts-cantarell` installs it. That was measured without installing
  anything: with the package's fonts unpacked into a scratch home, `fc-match Cantarell`
  named Cantarell. To choose another font, use
  `gsettings set org.gnome.desktop.interface font-name '<font> <size>'`. Set to
  `'Noto Sans 12'` in a settings store of its own, it was the font GTK took on Wayland.

## The clipboard and notifications

WSLg shares the clipboard with Windows: text copied in a Windows program pastes into a
console. [Pasting](TERMINAL-USAGE.md#pasting) and
[OSC 52](TERMINAL-USAGE.md#letting-applications-set-the-clipboard-osc-52) cover the rest.

WSLg has no notification service, so **Notify when a console needs attention** shows
nothing. The tab's mark is what you have, as
[When a tab needs your attention](TERMINAL-USAGE.md#when-a-tab-needs-your-attention)
describes.

## When something goes wrong

**GCM's window is blank, and its title starts with `[WARN] COPY MODE`.** WSLg has lost the
shared memory it draws windows through, and marks every Linux window's title that way.
`/mnt/wslg/weston.log` shows `rdp_allocate_shared_memory` errors. Run `wsl --shutdown` in
PowerShell, and start GCM again.

**The pointer never changes shape.** There is no text cursor over a console, and no arrows
at a window's edge or at the server pane's divider, though dragging there still works. The
cause is in WSLg: [microsoft/wslg#1433](https://github.com/microsoft/wslg/issues/1433),
after Windows sleeps, and [microsoft/wslg#1403](https://github.com/microsoft/wslg/issues/1403),
after it is locked. Those issues give `wsl --shutdown` as the fix, or restarting only WSLg's
compositor, with `wsl --system sh -lc "pkill -9 weston"`. Neither was tried for this guide.

**`Gdk-Message: Unable to load dnd-move from the cursor theme`** appears in GCM's output
when you drag something. It is harmless. GTK 3 asks for older names than the cursor theme
in Ubuntu 24.04 has, and falls back to images of its own. Links in your own icon folder
give it those names:

```bash
mkdir -p ~/.local/share/icons/Adwaita/cursors
cd ~/.local/share/icons/Adwaita/cursors
ln -s /usr/share/icons/Adwaita/cursors/move dnd-move
ln -s /usr/share/icons/Adwaita/cursors/copy dnd-copy
ln -s /usr/share/icons/Adwaita/cursors/copy dnd-ask
ln -s /usr/share/icons/Adwaita/cursors/alias dnd-link
ln -s /usr/share/icons/Adwaita/cursors/no-drop dnd-none
cd -
```

**`Gdk-WARNING: Tried to map a popup with a non-top most parent`** appears now and then. It
is harmless: a tooltip asked to show while a menu was open, and Wayland refused it. The
menu works, and the tooltip is not shown.

**Nautilus asks for a password your key should answer.** Restart `gvfsd`, as
[Nautilus and your key](#nautilus-and-your-key) describes.

**"No file manager was found to open …"** Install Nautilus, as
[Opening a host's files in Nautilus](#opening-a-hosts-files-in-nautilus) describes.

**"Mounting a host needs sshfs, which is not installed."** Run `sudo apt install sshfs`.

**A mount fails with "Host key verification failed."** Connect to the host once in a
console and accept its key.

**The shortcut does nothing.** Whatever the launcher prints from a shortcut goes nowhere.
To keep it, end the launcher with this line instead, and read `~/.cache/gcm.log`:

```bash
exec uv run gnome-connection-manager >>~/.cache/gcm.log 2>&1
```

`exec: uv: not found` there means the shortcut runs `wsl.exe` rather than `wslg.exe`: see
[A shortcut](#a-shortcut). Running `~/bin/gcm.sh` in an Ubuntu terminal shows the rest.

**`ModuleNotFoundError: No module named 'gi'`.** The environment was built without the
system's packages, or on another Python. Rebuild it:

```bash
cd ~/src/gnome-connection-manager
rm -rf .venv
export UV_PYTHON=/usr/bin/python3
uv venv --system-site-packages
uv sync
```

**A key does nothing in GCM.** Check whether a Windows shortcut has it: Windows takes a
shortcut's key before any program sees it.

## See also

- The README's [Optional programs](../README.md#optional-programs), for what other kinds of
  host use: FreeRDP, gtk-vnc or a VNC viewer, and `xdg-open` for web hosts and links,
  which needs a browser it can find in Ubuntu.
- [A host's files](HOSTS-AND-FOLDERS.md#a-hosts-files), for Open in File Manager, Mount
  with SSHFS and the Mounted tab.
- [What agent CLIs do](TERMINAL-USAGE.md#what-agent-clis-do), for Claude Code, `codex` and
  the others in a console.
- [When GCM will not start](TERMINAL-USAGE.md#when-gcm-will-not-start).
