"""A window on a VNC server's display that prints each key it is sent.

Run as a subprocess by tests/test_vnc.py, on the display of the Xtigervnc it starts, to
see which keys reach the remote desktop. It prints "ready" once it has the keyboard, then
a line for each key: its name, and "control" when Ctrl was held.
"""

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402


def on_key(_window, event):
    held = "control" if event.state & Gdk.ModifierType.CONTROL_MASK else ""
    print(Gdk.keyval_name(event.keyval), held, flush=True)
    return True


def on_map(window, _event):
    # There is no window manager on the server's display to give it the keyboard, and
    # without one GDK sets the X input focus itself.
    window.get_window().focus(Gdk.CURRENT_TIME)
    print("ready", flush=True)


window = Gtk.Window()
window.set_default_size(800, 600)
window.connect("key-press-event", on_key)
window.connect("map-event", on_map)
window.connect("destroy", Gtk.main_quit)
window.show_all()
Gtk.main()
