---
title: "Probing GCM Outside the Test Suite"
description: "Recipes for measuring GCM against real GTK, VTE, Wayland and packages without installing anything, from an Xvfb of a probe's own to a fresh Ubuntu, sshd, TigerVNC, headless sway and WSLg, with the traps each one hides"
audience:
  - contributors
tags:
  - gcm
  - gcm-dev
  - development
---

# Probing GCM Outside the Test Suite

`AGENTS.md` says to measure rather than assume, and the test suite sets itself up
(`tests/conftest.py`, `tests/xdisplay.py`). This page is for a probe outside the suite: a
throwaway script that measures GTK, VTE, a compositor or a package before there is a test
or a fix to hold it (#494). Nothing here installs a package or needs root.

Each recipe was run again on 2026-11-08, on main at 0967c64, in Ubuntu 24.04 under WSL
2.7.13, with GTK 3.24.41 and VTE 0.76.0. A version, a count or a size given here is that
run's, and each recipe says which of its steps were not run.

Keep a probe's scripts, downloads and logs in the main checkout's
`tmp/agents/<agent>/<issue>/`. Not in a worktree's `tmp/`: a file there keeps
`doit pr_merge` from removing the worktree (#332). Not in `/tmp`: a restart of WSL empties
it.

## A display of the probe's own

- **Start an Xvfb with `tests/xdisplay.py`.** `start()` returns the server's process and
  its display, `":N"`, or None, and `stop(process)` ends it. `doit sandbox --xvfb` uses
  them (#509). It waits for the server's abstract socket, the only one an Xvfb gets under
  WSLg, which mounts `/tmp/.X11-unix` read-only, and counts the display as its own only
  once the lock file names its process.
- **Keep the probe off the desktop.** Give it `DISPLAY=:N` and `GDK_BACKEND=x11`, and unset
  `WAYLAND_DISPLAY`, `GDK_SCALE` and `GDK_DPI_SCALE`: GTK prefers Wayland whenever
  `WAYLAND_DISPLAY` is set. A probe that maps a window on the real desktop takes the
  developer's keyboard focus, so say so before running one.
- **Give it a HOME of its own**, and unset what `UNSET` and `AGENT` in `tools/sandbox.py`
  name: `XDG_CONFIG_HOME` and the `GCM_*_DIR` variables, which point GCM at another
  configuration or checkout, and `SSH_AUTH_SOCK` and `SSH_AGENT_PID`. A shell in a GCM tab
  carries the `GCM_*_DIR` variables `main()` set for that GCM. Here they named an installed
  GCM's data, and `doit check` run with them failed 37 tests that passed once they were
  unset. The suite clears them itself since #547 (`tests/conftest.py`), but a probe runs
  outside pytest, so it still unsets them.
- **Start GCM as `main()` does**, so that its shortcuts are accelerators:
  `app.GcmApplication()`, then `run(["gcm"])`, reaching the window through
  `application._controller` from `GLib.timeout_add` callbacks while `run` owns the main
  loop. Set `app.conf.CHECK_UPDATES = False` first (#316). GCM registers as `NON_UNIQUE`,
  so a probe's GCM never hands itself over to one the developer has open.
- **Real input under X11 comes through XTest.** Load `libXtst.so.6` through ctypes, as
  `tests/test_console_window.py` does, send `XTestFakeMotionEvent` and
  `XTestFakeButtonEvent`, then `XFlush`. Aim at a widget by
  `get_window().get_root_coords(allocation.x, allocation.y)` plus half its allocation.
  Xvfb answers for X11 alone, and WSLg takes no synthetic input, so Wayland is measured on
  [headless sway](#headless-sway-with-a-virtual-pointer) and WSLg
  [by a person](#a-hand-check-by-a-person).

## Traps a probe meets

Each was measured on an Xvfb of the probe's own, and on another display where it says so.

- **A probe ended by `timeout` loses what it printed.** Its standard output is
  block-buffered: `timeout 2 python3 -c 'print("started"); ...'` into a file left it
  empty, and `python3 -u` left `started`. For a probe that may hang, run `python3 -u` and
  call `faulthandler.dump_traceback_later(N, exit=True)`, which prints every thread's
  stack after N seconds and exits.
- **A hand-built `Host` is not what gcm.conf gives.** `Host(group, name, description, host,
  user)` holds `port` 22 and `keep_alive` 0 as ints, and `password` and `commands` as None.
  Read back through gcm.conf's text, they are `'22'`, `'0'`, `''` and `''`.
  - The SSH type puts `host.port` in the command as it is (`command` in
    `src/gnome_connection_manager/utils/connections.py`), and VTE's `spawn_async` refuses an
    int there: `TypeError: Must be bytes, not int`.
  - By that code, only a password of `""` runs ssh itself. Any other goes through
    `ssh.expect`, which waited for a password in #308's probe.
  - `HostUtils.save_host_to_ini` fails on it as well, on the None `commands`.
  - Build a probe's hosts as `write_config` in `tools/sandbox.py` does, every field a
    string, or set those four to `"22"`, `"0"`, `""` and `""`.
- **A scratch `XDG_DATA_DIRS` aborts a whole GCM.** gdk-pixbuf finds image types through
  the MIME database there. With an empty `share`, GCM stopped at start with
  `Gtk:ERROR:../../../gtk/gtkiconhelper.c:495:ensure_surface_for_gicon: assertion failed`
  on `image-missing.png` (`Unrecognized image file format`), killed by SIGABRT. With
  `mime`, `icons`, `glib-2.0` and `themes` linked from `/usr/share`, it ran. Leave
  `applications` out where the probe must not find a real program to open a file or a URL
  with (#232); that part was not run again.
- **GTK names Yaru and draws Adwaita.** `/etc/gtk-3.0/settings.ini` sets
  `gtk-theme-name = Yaru`, and with a scratch HOME GTK reported Yaru. But only Adwaita,
  Adwaita-dark, Default and Emacs have a GTK 3 theme under `/usr/share/themes`, and the CSS
  GTK gave for the name Yaru was Adwaita's, character for character. Say which theme a
  measurement was drawn with, and unpack `yaru-theme-gtk` into a scratch folder to measure
  Yaru, as #350 did (`docs/design/tabs.md`).
- **With no session bus, libdbus starts one on the probe's display.** With
  `DBUS_SESSION_BUS_ADDRESS` unset and `XDG_RUNTIME_DIR` an empty folder, GCM run for 20 s
  autolaunched a bus through `dbus-launch`.
  - That bus started, on the probe's display: `dbus-daemon`, `at-spi-bus-launcher`,
    `at-spi2-registryd`, `xdg-desktop-portal`, `xdg-document-portal`,
    `xdg-permission-store` and `gvfsd`.
  - Once the Xvfb stopped, only `dbus-launch` was left, and SIGTERM ended it. During #316
    an `at-spi-bus-launcher` was left that ignored SIGTERM; that did not happen again.
  - Either way, find what a run left by its display: a process whose
    `/proc/<pid>/environ` holds `DISPLAY=:N` and that started after the run did. Stop
    only those.
- **A `GtkToolButton` has no `clicked()`, and `emit("clicked")` runs no action.** Measured
  on Find Next. A real click at its allocation through XTest reached its `GtkButton` and
  ran `app.search-next`, the window 1000 px wide and 1800 px alike. #498's probe had seen
  the click at 1000 px reach the toolbar instead. That did not happen again: the button
  had the same allocation at both widths.
- **Sans is Noto Sans here, and the menu scenarios were sized for DejaVu Sans**
  (`docs/design/menus-and-windows.md`). Where `fonts-noto-core` is installed,
  `fc-match Sans` and Pango both gave Noto Sans. Which font CI has is #503. With
  `FONTCONFIG_FILE` naming the file below, both gave DejaVu Sans:

  ```xml
  <?xml version="1.0"?>
  <!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
  <fontconfig>
    <match target="pattern">
      <test qual="any" name="family"><string>Sans</string></test>
      <edit name="family" mode="assign" binding="strong"><string>DejaVu Sans</string></edit>
    </match>
    <include ignore_missing="no">/etc/fonts/fonts.conf</include>
  </fontconfig>
  ```

- **Xvfb has no window manager.** A window there has no frame, `move()` lands at once,
  and before the window is placed `get_position()` read (0, 0), never the sentinel a
  window manager gives. Measure a window's place or size under a window manager instead:
  WSLg's X11, with `DISPLAY=:0` and `GDK_BACKEND=x11`, which opens windows on the
  desktop, or sway, where `swaymsg -t get_tree` gives where sway put a window.
  [A window's geometry](design/menus-and-windows.md#a-windows-geometry) has what each
  one gave (#550).
- **Under `Gtk.main()`, a failed assertion in a callback does not end the probe.** An
  `assert` that failed in a `GLib.idle_add` callback printed its traceback, and the probe
  ran on until the runner killed it 5 s later. PyGObject prints a callback's exception
  and carries on, as AGENTS.md says of a signal handler's. Instead, run the loop in the
  probe's own code: call `Gtk.main_iteration_do(False)` until a condition holds or a
  deadline passes, as `pump` in `tests/test_wmain.py` does, and assert there. The same
  assertion at the top level ended the probe with status 1.
- **A menu popped up with no event warns, and under WSLg's Wayland it did not open.**
  `popup_at_rect` and `popup_at_widget` given `None` for the event print
  `no trigger event for menu popup`. Both opened the menu all the same on Xvfb, and
  `popup_at_rect` did on sway, at the place asked for. That warning is the probe's own:
  `popup_menu_at` passes on the event that opened a GCM menu.
  - `popup_at_pointer(None)` opened nothing on Xvfb, and GTK printed
    `gtk_menu_popup_at_rect: assertion 'GDK_IS_WINDOW (rect_window)' failed`.
  - Under WSLg's Wayland, `popup_at_rect` with no event opened nothing: `get_visible()`
    was False a second later.
  - Whether a real click's event opens it there was not measured, as WSLg takes no
    synthetic input.

## Packages without installing them

`apt-get download` fetches a package as a user, and `dpkg-deb -x` unpacks it into a
folder. To fetch only what the machine lacks, ask apt what it would install:

```bash
apt-get -s install --no-install-recommends <packages> | awk '/^Inst/ {print $2}'
```

The simulation needs no root. A list built from `apt-cache depends --recurse` instead
names every alternative of a dependency, even where one already installed meets it:
less what dpkg had installed, it held 36 packages for sway, against the 21 apt would
install.

## A fresh Ubuntu, without Docker or root

For what a package or `install.sh` needs on a machine that has nothing (#294, #273, #302).
Docker's socket refuses this user, and without `newuidmap` a user namespace maps uid 0
alone, so the root filesystem runs under proot, and installs in a chroot.

1. **proot.** `apt-get download proot`, and `dpkg -x` it: proot 5.1.0.
2. **The base image.** `ubuntu-base-24.04.5-base-amd64.tar.gz` from
   `https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/`, checked with
   `sha256sum --ignore-missing -c SHA256SUMS`. That `SHA256SUMS` lists 24.04.3, .4 and .5:
   take the newest. Unpack it with `tar -xzf <image> -C rootfs --exclude='./dev/*'`, copy
   the host's `/etc/resolv.conf` in, and write `APT::Sandbox::User "root";` to
   `rootfs/etc/apt/apt.conf.d/01sandbox`.
3. **Run in it as root**, with an environment of its own:

   ```bash
   proot -0 -r rootfs -b /dev -b /proc -b /sys -w /root \
     /usr/bin/env -i HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
     DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 apt-get update
   ```

   The PATH needs `/usr/local/bin`, where `gem` puts `fpm`: without it, `make deb` stopped
   at `fpm: not found`.
4. **`make deb` builds there**, after `apt-get install -y --no-install-recommends ruby
   gettext python3-pip make binutils` and `gem install --no-document fpm` (fpm 1.18.0).
   With the tree copied in by `git archive HEAD | tar -x -C rootfs/root/gcm`, it built
   `gnome-connection-manager_2.2.1_all.deb`, which `dpkg-deb -f` and `apt-get install -s`
   read.
5. **proot 5.1.0 breaks `statx`.** Under it, `stat` and `ls -l` failed with
   `Permission denied` on the files under `/root`, the `.deb` among them, while
   `/etc/hostname` read. #273 saw `apt-get install` of the `.deb` fail there for that
   reason. This time it finished under proot, with GCM's dependencies, and put
   `/usr/bin/gnome-connection-manager` and `/usr/bin/gcm` in place. A chroot through a user
   namespace has no such trouble, as the root filesystem belongs to this user: there
   `stat` read the Makefile proot had refused, and apt installed `xvfb` and `x11-utils`,
   48 packages, leaving `dpkg --audit` empty:

   ```bash
   unshare -r -m bash -c 'mount --rbind /proc rootfs/proc && mount --rbind /dev rootfs/dev &&
     exec chroot rootfs /usr/bin/env -i HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
       DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 \
       apt-get install -y /root/gcm/gnome-connection-manager_2.2.1_all.deb xvfb x11-utils'
   ```
6. **systemd's postinst aborts under proot.** GTK installed by name under proot, with its
   recommends, pulled systemd in. Its postinst stopped with
   `Assertion 'path_is_absolute(p)' failed at src/basic/chase.c:648`, exit status 134,
   leaving it half configured. In the chroot, where only uid 0 is mapped,
   `dpkg --configure -a` then configured it. Its postinst reported
   `fchownat() of /var/log/btmp failed: Invalid argument`, and the same of
   `/var/log/lastlog` and `/var/log/journal`, and finished, leaving `dpkg --audit` empty.
   Stubbing `/var/lib/dpkg/info/systemd.postinst` with `exit 0` (#294) was not needed, and
   not run.
7. **Run GCM in it, on an Xvfb inside, and read that Xvfb from outside.** The chroot shares
   the network namespace, so its Xvfb's abstract socket is the host's:
   `xwininfo -display :91 -root -tree` outside listed GCM's window. A GCM from before #544,
   release 2.2.1 among them, needs `SHELL` in its environment: under `env -i` without it, it
   stopped at import with `KeyError: 'SHELL'`. Since #544 a GCM started without `SHELL` runs
   the shell of the user's passwd entry; that was not re-run in this chroot.
8. **Size.** The image is 30 MB, and the root filesystem was 1.2 GB with GTK in it.

## sshd as the user, for probes that open shell sessions

`tests/test_host_files.py` runs one for SFTP (#267). For a probe that opens shell sessions
(#312):

1. **Unpack it.** `apt-get download openssh-server openssh-sftp-server libnss-wrapper`, the
   three apt would install here, and `dpkg -x` each into one folder: OpenSSH 9.6p1.
2. **Configure it.** It needs a `Port`, `ListenAddress 127.0.0.1`, and a `HostKey`,
   `PidFile` and `AuthorizedKeysFile` of its own, with `UsePAM no`, `StrictModes no` and
   `PasswordAuthentication no`. Run it as `<folder>/usr/sbin/sshd -D -e -f <config>`, by its
   absolute path. As the user, it needed no privilege separation user.
3. **Trap: a session runs the user's login shell.** Debian's bash reads `~/.bashrc` even
   for `ssh <host> <command>`. With bash for the login shell and a scratch home whose
   `.bashrc` echoed a marker, the command's output began with the marker. A developer's
   `.bashrc` can start keychain or update the session bus above its interactive check
   (`docs/WSL-SETUP.md`), and every probe login would run that. So run sshd under
   nss_wrapper, with a user of its own:

   ```bash
   echo "$(id -un):x:$(id -u):$(id -g):probe:$PWD/home:/bin/sh" >passwd
   echo "$(id -gn):x:$(id -g):" >group
   LD_PRELOAD=$PWD/root/usr/lib/x86_64-linux-gnu/libnss_wrapper.so \
     NSS_WRAPPER_PASSWD=$PWD/passwd NSS_WRAPPER_GROUP=$PWD/group \
     "$PWD/root/usr/sbin/sshd" -D -e -f "$PWD/sshd_config"
   ```

   With `/bin/sh`, the marker was not printed. An sshd without nss_wrapper was not run, as
   it would read the developer's own `.bashrc`.
4. **The client.** `ssh -F <config>` with an `IdentityFile` and `IdentitiesOnly yes`,
   `IdentityAgent none`, a `UserKnownHostsFile` of its own and
   `GlobalKnownHostsFile /dev/null`, run under `env -u SSH_AUTH_SOCK -u SSH_AGENT_PID`:
   the session had no agent. Write the config with Python or a quoted heredoc. `printf`
   takes `%h` and `%p` as formats, and stopped with `invalid format character`.
5. **Stop it** by the process you started, once `/proc/<pid>/cmdline` names your config
   (`grep -aqF <config> /proc/<pid>/cmdline`).

## tests/test_vnc.py without installing

`tests/test_vnc.py`, for a VNC host drawn in its tab (#234), needs gtk-vnc's typelib and
TigerVNC, and skips without them. CI installs both. Here gtk-vnc has been installed since
2026-10-30, and TigerVNC is not.

1. **Unpack what is missing.** For `gir1.2-gtk-vnc-2.0 libgtk-vnc-2.0-0 libgvnc-1.0-0
   tigervnc-standalone-server tigervnc-common tigervnc-tools tigervnc-viewer`, apt named
   37 packages here: TigerVNC 1.13.1 and what it needs, most of it the viewer's FLTK and
   FFmpeg libraries. Fetch them and `dpkg-deb -x` each into one root.
2. **Run with the root on the paths:**

   ```bash
   LD_LIBRARY_PATH=<root>/usr/lib/x86_64-linux-gnu \
     GI_TYPELIB_PATH=<root>/usr/lib/x86_64-linux-gnu/girepository-1.0 \
     PATH=<root>/usr/bin:$PATH uv run pytest tests/test_vnc.py
   ```

   11 passed. Without the root, all 11 skipped: `needs TigerVNC's server and tools, and
   xsetroot`.
3. **The fallback**, a VNC viewer in a terminal tab, is `tests/test_connections.py`'s. To
   see it in GCM by hand, GCM must not find GtkVnc. Leaving `GI_TYPELIB_PATH` unset does
   that only where gtk-vnc is not installed. Not run here, where it is.

## Headless sway, with a virtual pointer

Under Wayland, GTK behaves in ways X11 does not show (#255). WSLg takes no synthetic input,
so Wayland is measured on sway, headless, moved by a small client of the
`zwlr_virtual_pointer_manager_v1` protocol. Measured with sway 1.9, Ubuntu 24.04's.
`docs/design/` also records measurements on sway 1.11 (#490, #493), whose PRs give their
setup only in outline.

1. **Unpack it.** apt named 21 packages for `sway libwayland-bin libwayland-dev`. Unpack
   them into one root, and run with `LD_LIBRARY_PATH=<root>/usr/lib/x86_64-linux-gnu`.
2. **Keep `XDG_RUNTIME_DIR` short**, mode 700: a socket's path holds 108 bytes. With
   144 bytes to `wayland-1`, sway exited 1 with `Unable to open wayland socket`. With 83, it
   made `wayland-1` and `sway-ipc.<uid>.<pid>.sock` there.
3. **Run it** with this config, its windows floating so that bare output is left to drop
   a tab on:

   ```text
   xwayland disable
   output HEADLESS-1 resolution 1920x1080
   for_window [title=".*"] floating enable
   ```

   ```bash
   env -u WAYLAND_DISPLAY -u DISPLAY XDG_RUNTIME_DIR=<short> WLR_BACKENDS=headless \
     WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman <root>/usr/bin/sway -d -c <config>
   ```

4. **Build the pointer client.** Take `wlr-virtual-pointer-unstable-v1.xml` from
   `https://gitlab.freedesktop.org/wlroots/wlr-protocols/-/raw/master/unstable/wlr-virtual-pointer-unstable-v1.xml`.
   Use `wayland-scanner` from the unpacked `libwayland-bin`, and the headers from the
   unpacked `libwayland-dev`:

   ```bash
   <root>/usr/bin/wayland-scanner client-header wlr-virtual-pointer-unstable-v1.xml vp.h
   <root>/usr/bin/wayland-scanner private-code wlr-virtual-pointer-unstable-v1.xml vp.c
   gcc -I. -I<root>/usr/include -o vptr vptr.c vp.c /usr/lib/x86_64-linux-gnu/libwayland-client.so.0
   ```

   `vptr.c` reads `abs X Y`, `press B` and `release B` on its standard input. B is 272 for
   the left button and 273 for the right. It answers `ok` after each:

   ```c
   #include <stdio.h>
   #include <string.h>
   #include <wayland-client.h>
   #include "vp.h"

   static struct zwlr_virtual_pointer_manager_v1 *manager;
   static struct wl_seat *seat;

   static void global(void *data, struct wl_registry *registry, uint32_t name,
                      const char *interface, uint32_t version) {
       if (strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name) == 0)
           manager = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
       else if (strcmp(interface, wl_seat_interface.name) == 0)
           seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
   }

   static void global_remove(void *data, struct wl_registry *registry, uint32_t name) {}

   static const struct wl_registry_listener listener = {global, global_remove};

   int main(void) {
       struct wl_display *display = wl_display_connect(NULL);
       if (!display) {
           fprintf(stderr, "no Wayland display\n");
           return 1;
       }
       struct wl_registry *registry = wl_display_get_registry(display);
       wl_registry_add_listener(registry, &listener, NULL);
       wl_display_roundtrip(display);
       if (!manager) {
           fprintf(stderr, "the compositor has no virtual pointer manager\n");
           return 1;
       }
       struct zwlr_virtual_pointer_v1 *pointer =
           zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, seat);
       char line[128];
       uint32_t time = 0;
       unsigned x, y, button;
       setvbuf(stdout, NULL, _IOLBF, 0);
       while (fgets(line, sizeof line, stdin)) {
           time += 10;
           if (sscanf(line, "abs %u %u", &x, &y) == 2)
               zwlr_virtual_pointer_v1_motion_absolute(pointer, time, x, y, 1920, 1080);
           else if (sscanf(line, "press %u", &button) == 1)
               zwlr_virtual_pointer_v1_button(pointer, time, button, WL_POINTER_BUTTON_STATE_PRESSED);
           else if (sscanf(line, "release %u", &button) == 1)
               zwlr_virtual_pointer_v1_button(pointer, time, button, WL_POINTER_BUTTON_STATE_RELEASED);
           else
               continue;
           zwlr_virtual_pointer_v1_frame(pointer);
           wl_display_roundtrip(display);
           printf("ok\n");
       }
       return 0;
   }
   ```

5. **Find a window.** Wayland tells a client nothing of where its windows are. Run the
   client with `GDK_BACKEND=wayland`, the short `XDG_RUNTIME_DIR` and
   `WAYLAND_DISPLAY=wayland-1`. Take its window's rectangle from
   `SWAYSOCK=<short>/sway-ipc.<uid>.<pid>.sock swaymsg -t get_tree`, put the pointer inside,
   and read `get_device_position` in the client for the offset.
   - Measured: a GTK window's rectangle was 758,390, 404x302.
   - The pointer sent to its centre clicked its button.
   - GTK put the pointer at 200,151 in the window, 2 px from the centre the rectangle gave.

   What sway does with a drag that was cancelled is in `AGENTS.md`; it was not measured
   again.

## WSLg

### The protocol, with WAYLAND_DEBUG

`doit sandbox --wayland-debug` writes `WAYLAND_DEBUG=client`'s lines into the sandbox's log,
beside GCM's trace (`docs/DEVELOPING.md`). Not run for this page.

For a probe of its own, set `WAYLAND_DEBUG=client` and `GDK_BACKEND=wayland`.

- The `XDG_RUNTIME_DIR` of the shell used here, `/run/user/1000`, holds `wayland-0` as a link to
  `/mnt/wslg/runtime-dir/wayland-0`. So `WAYLAND_DISPLAY=wayland-0` and the full path both
  connected, and the registry listed 22 globals.
- Where a shell's runtime folder lacks that link, give the full path.
- With `XDG_RUNTIME_DIR` unset, GTK found no display, even with the full path.
- A connection that maps no window shows nothing on the desktop.

### WSLg's windows

`doit wslg_windows` lists the windows of WSLg's own `msrdc.exe` (#510), as
[the development guide](DEVELOPING.md#listing-wslgs-windows) says. Run with GCM open, it
listed 21 windows, one visible: GCM's.

- That window measured 2880x1812, and PowerShell's default DPI awareness read it as
  1280x805, at DPI 216.
- Windows reads a size so, divided by 2.25 here, unless the reader is per-monitor aware,
  and the tool shows both.
- It runs `powershell.exe`, which can take the keyboard focus.

### A hand check by a person

WSLg takes no synthetic input, so a person makes the drags or the clicks while GCM's trace
records them. This is how #504, #515, #535, #536, #539, #540 and #542 were checked
(2026-11-05 to 11-07). The drags were not run for this page, but the trace's part was, on an
Xvfb.

- Detached, `doit sandbox --fresh --local 2 --trace=drag` printed
  `GCM runs as PID <pid>, its output in <checkout>/tmp/sandbox_cache/logs/gcm-<time>.log`.
- After a mark, that log held the `environment` line and `=== MARK try 1 ===`, each as
  `<stamp> drag: <message>`.

From the checks themselves:

- #505's check ran `doit sandbox --fresh --local 4 --scale=2 --trace=drag --wait`.
- With `--wait`, the trace goes to the terminal, and it is kept only if redirected.
  - #541's check passed but kept no trace.
  - #534's kept none either, so which of its two code paths kept a flicked tab is unknown.
- Without `--wait`, the trace goes to the log the task prints,
  `tmp/sandbox_cache/logs/gcm-<time>.log`.
- A mark between tries, `trace-mark` and `kill -USR1` (`docs/DEVELOPING.md`), can tie each
  try to its lines.
- Copy the trace to the main checkout's `tmp/agents/<agent>/<issue>/` before `doit pr_merge`
  removes the worktree's sandbox and its logs. #505's, #533's and #538's traces were kept
  so.
- Programs GCM starts write their standard error into the same log: a browser's did, in
  #538's run. To watch the log, filter it to the trace's own lines,
  `<stamp> drag: <message>`.

## The README screenshot

`docs/images/screenshot.png` is a real window, not a mock-up (#271). Run again with the
script below, it gave a 1180x700 shot whose layout matched the committed one: the tree,
four tabs, the pane, the prompt and the font. The two differed only in today's toolbar,
the log the console showed, and the cursor, which the committed one shows.

- **An Xvfb of its own**, `1920x1080x24`, with no window manager, so the window has no
  title bar. Unset `WAYLAND_DISPLAY`, `XDG_CONFIG_HOME`, `GDK_SCALE`, `GDK_DPI_SCALE` and the
  `GCM_*` variables, and set `GDK_BACKEND=x11`.
- **A scratch HOME with no GTK `settings.ini`**, so that the font is GTK's default.
  `touch $HOME/.sudo_as_admin_successful`, or `/etc/bash.bashrc` prints its hint about
  sudo in the console, for a user in the sudo group.
- **`SHELL` a wrapper** running `bash --rcfile demo.rc -i`, where `demo.rc` sets the prompt
  and shows the checkout. Commit first, so that `git status -sb` is clean:

  ```bash
  cd <checkout>
  PS1='\[\e[01;32m\]you@workstation\[\e[00m\]:\[\e[01;34m\]~/src/gcm\[\e[00m\]\$ '
  git --no-pager log --oneline --decorate --color=always -6; echo; git -c color.status=always status -sb; echo
  ```

- **The window**, run as `python -u readme_shot.py <out.png>` with that HOME and SHELL, on
  that Xvfb. GCM opens one local tab at start, so the script opens three more:

  ```python
  import configparser
  import os
  import sys
  from pathlib import Path

  import gi

  gi.require_version("Gtk", "3.0")
  gi.require_version("Gdk", "3.0")
  from gi.repository import Gdk, GLib

  from gnome_connection_manager import app
  from gnome_connection_manager.utils.folders import FolderTree
  from gnome_connection_manager.utils.hosts import ERASE_BINDING_AUTO, Host, HostUtils

  TREE = (
      ("Home lab/Edge", ("opnsense", "switch-01")),
      ("Home lab", ("nas",)),
      ("Projects/gnome-connection-manager", ("build", "docs")),
      ("Projects/pyproject-template", ("ci-runner",)),
  )


  def write_config(path):
      cp = configparser.RawConfigParser()
      cp.add_section("options")
      cp.set("options", "check-updates", "False")
      tree = FolderTree()
      number = 0
      for group, names in TREE:
          folder = tree.ensure_path(group)
          for name in names:
              number += 1
              host = Host(
                  group, name, "", f"{name}.invalid", "you", "", "", "22", "", "ssh", "",
                  "0", "", "", "False", "False", "False", "", "", "False",
                  ERASE_BINDING_AUTO, ERASE_BINDING_AUTO, "", "False", "", folder,
              )
              section = f"host {number}"
              cp.add_section(section)
              HostUtils.save_host_to_ini(cp, section, host, "")
              cp.set(section, "pass", "")
      tree.save(cp)
      path.parent.mkdir(parents=True, exist_ok=True)
      with path.open("w", encoding="utf-8") as stream:
          cp.write(stream)


  write_config(Path(os.environ["HOME"]) / ".config" / "gcm" / "gcm.conf")
  app.conf.CHECK_UPDATES = False
  application = app.GcmApplication()


  def start():
      w = application._controller
      w.treeServers.expand_all()
      w.wMain.resize(1180, 700)
      w.hpMain.set_position(250)
      for _ in range(4 - w.nbConsole.get_n_pages()):
          application.activate_action("new-local", None)
      GLib.timeout_add(3000, capture)
      return False


  def capture():
      w = application._controller
      width, height = w.wMain.get_allocated_width(), w.wMain.get_allocated_height()
      pixbuf = Gdk.pixbuf_get_from_window(w.wMain.get_window(), 0, 0, width, height)
      pixbuf.savev(sys.argv[1], "png", [], [])
      application.quit()
      return False


  GLib.timeout_add(1500, start)
  sys.exit(application.run(["gcm"]))
  ```
