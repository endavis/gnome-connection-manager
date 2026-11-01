"""A window GCM opens has a transient parent, and the right one (#403).

Under Wayland GTK cannot place a window: the compositor does, over its transient parent if
it has one, and wherever it likes if not. The host dialog, the buffer viewer, Preferences
and the messages mounting shows were reported to open at random places on WSLg.

Three kinds of test:

- the rule reads the package's source with `ast`, and fails naming each window built
  without asking `dialog_parent` for its parent, and the line. It is a function of a source,
  and is itself held to the sources it must and must not flag;
- the real-GTK scenarios open the windows, in processes of their own on the suite's
  display, and read what each is transient for: the modal window on top when there is one,
  and else the window in use;
- the order `dialog_parent` decides in is held in `tests/test_dialog_parent_order.py`.

Where WSLg puts a window that has a parent is not measured by any of them. They run on
an X server with no window manager, so they hold what GCM asks for, which is the half of
the fix that is GCM's, and not where a Wayland compositor puts a window.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.test_connections import glib_complaints

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "gnome_connection_manager"
APP = PACKAGE / "app.py"

# The windows left with no parent, each with why it is not a window over another. The test
# below holds this list exact: an entry that no longer matches anything must go.
EXEMPT = {
    "require_expect": "run from main() before any window exists: there is nothing to be over",
    "require_config_dir": "run from main() before any window exists: there is nothing to be over",
    "require_readable_config": (
        "run from main() before any window exists: there is nothing to be over"
    ),
    "Wmain": "the main window, the root every other window is transient for or opened from",
    "ConsoleWindow": (
        "a peer of the main window (#255): it holds consoles as the main window does, joins "
        "the application and is moved to another monitor on purpose. A transient window is "
        "kept above its parent and goes with it when the parent is minimized, which a window "
        "of its own must not"
    ),
    "TranscriptReplayer.start": "a Gtk.OffscreenWindow, which is never on a screen",
}

# What counts as a window of its own: `Gtk.X` for any X ending in these, bar the names below
# that are not, and the two that do not end so. test_the_classes_the_rule_takes... below
# holds this to GTK.
WINDOW_ENDINGS = ("Window", "Dialog")
ALSO_WINDOWS = {"Assistant", "FileChooserNative"}
NOT_WINDOWS = {"ScrolledWindow"}


class Finding(NamedTuple):
    where: str
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.where} (line {self.line}): {self.what}"


def is_window_class(name: str) -> bool:
    """Whether `Gtk.<name>` is a window or a dialog of its own."""
    if name in NOT_WINDOWS:
        return False
    return name in ALSO_WINDOWS or name.endswith(WINDOW_ENDINGS)


def gtk_attribute(node: ast.AST) -> str | None:
    """`X` for the expression `Gtk.X`, else None."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Gtk"
    ):
        return node.attr
    return None


def asks_dialog_parent(node: ast.AST | None) -> bool:
    """Whether `node` is a call of `dialog_parent`, whatever it is given."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dialog_parent"
    )


def given_parent(call: ast.Call) -> ast.expr | None:
    """The value of the `parent=` or `transient_for=` a call is given."""
    for keyword in call.keywords:
        if keyword.arg in ("parent", "transient_for"):
            return keyword.value
    return None


def window_built_by(call: ast.Call) -> str | None:
    """The Gtk window class a call builds, as `Gtk.X(...)` or `Gtk.X.new...(...)`.

    `Gtk.Window.__init__(...)` and `Gtk.Window.fullscreen(...)` build nothing: the first
    starts a window a class has already made, which the class is held to.
    """
    name = gtk_attribute(call.func)
    if name is None and isinstance(call.func, ast.Attribute) and call.func.attr.startswith("new"):
        name = gtk_attribute(call.func.value)
    return name if name is not None and is_window_class(name) else None


def derives_from_window(base: ast.expr, known: dict[str, ast.ClassDef]) -> bool:
    name = gtk_attribute(base)
    if name is not None:
        return is_window_class(name)
    return isinstance(base, ast.Name) and (base.id == "GladeComponent" or base.id in known)


def window_classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    """The classes that are windows: derived from a Gtk window or dialog, from
    GladeComponent, or from another class of the module that is, however far down."""
    classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    found: dict[str, ast.ClassDef] = {}
    grew = True
    while grew:
        grew = False
        for name, node in classes.items():
            if name not in found and any(derives_from_window(base, found) for base in node.bases):
                found[name] = node
                grew = True
    return found


def how_a_class_is_parented(node: ast.ClassDef) -> str | None:
    """How the class gets its parent: "asks" when an `__init__` of its own asks
    `dialog_parent`, "takes" when it forwards one its caller gives, None when neither."""
    init = next(
        (
            each
            for each in node.body
            if isinstance(each, ast.FunctionDef) and each.name == "__init__"
        ),
        None,
    )
    if init is None:
        return None
    arguments = init.args
    parameters = {
        each.arg for each in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    }
    how = None
    for call in (each for each in ast.walk(init) if isinstance(each, ast.Call)):
        if not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr == "set_transient_for" and call.args and asks_dialog_parent(call.args[0]):
            return "asks"
        if call.func.attr == "__init__":
            value = given_parent(call)
            if asks_dialog_parent(value):
                return "asks"
            if isinstance(value, ast.Name) and value.id in parameters:
                how = "takes"
    return how


class Calls(ast.NodeVisitor):
    """Every call in a source, with where it stands: the function, or the class and method."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ast.Call]] = []
        self._scope: list[tuple[str, str]] = []

    def where(self) -> str:
        names = []
        for kind, name in self._scope:
            names.append(name)
            if kind == "def":
                break
        return ".".join(names) or "<module>"

    def _inside(
        self, kind: str, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self._scope.append((kind, node.name))
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._inside("class", node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._inside("def", node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._inside("def", node)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append((self.where(), node))
        self.generic_visit(node)


def windows_without_a_parent(source: str) -> list[Finding]:
    """Each window `source` builds, or defines, that is not given a parent from
    `dialog_parent`: a window built with no `parent=` or `transient_for=` that is a call of
    it, a class of windows with no `__init__` of its own that sets one, and a build of a
    class that takes its parent from its caller with none."""
    tree = ast.parse(source)
    classes = window_classes(tree)
    how = {name: how_a_class_is_parented(node) for name, node in classes.items()}
    takes = {name for name, each in how.items() if each == "takes"}
    walker = Calls()
    walker.visit(tree)
    findings = []
    for where, call in walker.calls:
        parented = asks_dialog_parent(given_parent(call))
        built = window_built_by(call)
        if built is not None and not parented:
            findings.append(Finding(where, call.lineno, f"Gtk.{built} is built with no parent"))
        elif isinstance(call.func, ast.Name) and call.func.id in takes and not parented:
            findings.append(Finding(where, call.lineno, f"{call.func.id} is built with no parent"))
    for name, node in classes.items():
        if how[name] is None:
            findings.append(
                Finding(name, node.lineno, f"class {name} sets no transient parent in its __init__")
            )
    return sorted(findings, key=lambda each: each.line)


# -- the rule ----------------------------------------------------------------------------


def test_every_window_app_builds_asks_dialog_parent_for_its_parent():
    found = windows_without_a_parent(APP.read_text(encoding="utf-8"))

    unexpected = [each for each in found if each.where not in EXEMPT]
    assert not unexpected, (
        "these windows have no transient parent from dialog_parent, so a Wayland compositor "
        "places them wherever it likes (#403):\n  " + "\n  ".join(map(str, unexpected))
    )


def test_each_exemption_still_matches_a_window_with_no_parent():
    """A fixed or a removed window must come off the list, or the list outlives its reasons
    and hides the next window built in its place."""
    found = {each.where for each in windows_without_a_parent(APP.read_text(encoding="utf-8"))}

    stale = sorted(set(EXEMPT) - found)
    assert not stale, f"these exemptions match no window now: {stale}"


def test_no_other_module_of_the_package_builds_a_window():
    """Only app.py holds `dialog_parent`, so a window built in another module has no way to
    ask for its parent, and is flagged without an exemption."""
    others = sorted(path for path in PACKAGE.rglob("*.py") if path != APP)
    assert others, "module discovery looks broken"

    found = {}
    for path in others:
        windows = windows_without_a_parent(path.read_text(encoding="utf-8"))
        if windows:
            found[path.relative_to(REPO).as_posix()] = [str(each) for each in windows]

    assert not found, f"these modules build a window: {found}"


# -- the rule is held to what it must and must not flag -----------------------------------

FLAGGED = {
    "a message with no parent": (
        "def f():\n    Gtk.MessageDialog(text='x')\n",
        ["f"],
    ),
    "a parent of None": (
        "def f():\n    Gtk.MessageDialog(parent=None)\n",
        ["f"],
    ),
    "a parent that is a window of the module": (
        "def f(self):\n    Gtk.MessageDialog(parent=self.wMain)\n",
        ["f"],
    ),
    "a transient_for that is a parameter": (
        "def f(parent):\n    Gtk.ColorChooserDialog(transient_for=parent)\n",
        ["f"],
    ),
    "a constructor": (
        "def f():\n    Gtk.Window.new(Gtk.WindowType.TOPLEVEL)\n",
        ["f"],
    ),
    "a constructor with buttons": (
        "def f():\n    Gtk.Dialog.new_with_buttons('x')\n",
        ["f"],
    ),
    "a native chooser": (
        "def f():\n    Gtk.FileChooserNative(title='x')\n",
        ["f"],
    ),
    "an assistant": (
        "def f():\n    Gtk.Assistant()\n",
        ["f"],
    ),
    "a method's window": (
        "class C:\n    def m(self):\n        Gtk.FileChooserDialog(title='x')\n",
        ["C.m"],
    ),
    "a window in a nested function": (
        "def f():\n    def g():\n        Gtk.Dialog()\n",
        ["f"],
    ),
    "a dialog class with no parent": (
        "class D(Gtk.Dialog):\n    def __init__(self):\n        Gtk.Dialog.__init__(self)\n",
        ["D"],
    ),
    "a window class with no __init__": (
        "class W(Gtk.Window):\n    pass\n",
        ["W"],
    ),
    "a glade component with no __init__": (
        "class G(GladeComponent):\n    pass\n",
        ["G"],
    ),
    "a glade component that passes no parent": (
        "class G(GladeComponent):\n    def __init__(self):\n        super().__init__('p', 'r')\n",
        ["G"],
    ),
    "a glade component that passes its own window": (
        "class G(GladeComponent):\n"
        "    def __init__(self):\n"
        "        super().__init__('p', 'r', parent=wMain.window)\n",
        ["G"],
    ),
    "a subclass of a window class": (
        "class V(Gtk.Window):\n"
        "    def __init__(self):\n"
        "        Gtk.Window.__init__(self)\n"
        "        self.set_transient_for(dialog_parent())\n"
        "class W(V):\n"
        "    pass\n",
        ["W"],
    ),
    "a subclass two removes down": (
        "class A(Gtk.Window):\n    pass\nclass B(A):\n    pass\nclass C(B):\n    pass\n",
        ["A", "B", "C"],
    ),
    "a window set transient for something else": (
        "class W(Gtk.Window):\n"
        "    def __init__(self, controller):\n"
        "        Gtk.Window.__init__(self)\n"
        "        self.set_transient_for(controller.wMain)\n",
        ["W"],
    ),
    "a class that takes its parent, built with none": (
        "class E(Gtk.Dialog):\n"
        "    def __init__(self, parent=None):\n"
        "        Gtk.Dialog.__init__(self, transient_for=parent)\n"
        "def f():\n"
        "    E()\n",
        ["f"],
    ),
    "a class that takes its parent, built with another": (
        "class E(Gtk.Dialog):\n"
        "    def __init__(self, parent=None):\n"
        "        Gtk.Dialog.__init__(self, transient_for=parent)\n"
        "def f(window):\n"
        "    E(parent=window)\n",
        ["f"],
    ),
}

CLEAN = {
    "a message with a parent": "def f(p):\n    Gtk.MessageDialog(parent=dialog_parent(p))\n",
    "a chooser with a transient_for": (
        "def f():\n    Gtk.ColorChooserDialog(transient_for=dialog_parent())\n"
    ),
    "a window class that sets it": (
        "class W(Gtk.Window):\n"
        "    def __init__(self):\n"
        "        Gtk.Window.__init__(self)\n"
        "        self.set_transient_for(dialog_parent())\n"
    ),
    "a glade component that passes it": (
        "class G(GladeComponent):\n"
        "    def __init__(self):\n"
        "        super().__init__('p', 'r', parent=dialog_parent())\n"
    ),
    "a class that takes its parent, built with one": (
        "class E(Gtk.Dialog):\n"
        "    def __init__(self, parent=None):\n"
        "        Gtk.Dialog.__init__(self, transient_for=parent)\n"
        "def f(p):\n"
        "    E(parent=dialog_parent(p))\n"
    ),
    "the start of a window a class made": (
        "class W(Gtk.Window):\n"
        "    def __init__(self):\n"
        "        Gtk.Window.__init__(self)\n"
        "        self.set_transient_for(dialog_parent())\n"
    ),
    "a method of Gtk.Window": "def f(w):\n    Gtk.Window.fullscreen(w)\n    Gtk.Window.unfullscreen(w)\n",
    "a scrolled window": "def f():\n    return Gtk.ScrolledWindow(vexpand=True)\n",
    "a check for a window": "def f(x):\n    return isinstance(x, (Gtk.Window, Gtk.Dialog))\n",
    "a class that holds a window": (
        "class Holder:\n    def __init__(self, window):\n        self.window = window\n"
    ),
    "a widget that is no window": "def f():\n    return Gtk.Box()\n",
    "a window type, which is no window": "def f():\n    return Gtk.WindowType.TOPLEVEL\n",
}


@pytest.mark.parametrize(("source", "where"), list(FLAGGED.values()), ids=list(FLAGGED))
def test_the_rule_flags_a_window_with_no_parent_from_dialog_parent(source, where):
    assert [each.where for each in windows_without_a_parent(source)] == where


@pytest.mark.parametrize("source", list(CLEAN.values()), ids=list(CLEAN))
def test_the_rule_leaves_a_window_with_one_alone(source):
    assert windows_without_a_parent(source) == []


def test_the_rule_names_the_line():
    source = "x = 1\n\n\ndef f():\n    y = 2\n    Gtk.MessageDialog(text='x')\n"

    [found] = windows_without_a_parent(source)

    assert (found.where, found.line) == ("f", 6)
    assert "Gtk.MessageDialog" in found.what


# -- the classes the rule takes for windows are GTK's ---------------------------------------

_CLASSES_SCRIPT = r"""
import json
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

names = sorted(name for name in dir(Gtk) if name.endswith(("Window", "Dialog")))
classes = {name: getattr(Gtk, name) for name in names}
print(json.dumps({
    "windows": [name for name, each in classes.items()
                if isinstance(each, type) and issubclass(each, (Gtk.Window, Gtk.NativeDialog))],
    "names": names,
    "also": {name: issubclass(getattr(Gtk, name), (Gtk.Window, Gtk.NativeDialog))
             for name in ("Assistant", "FileChooserNative")},
}))
"""

_NEEDS_DISPLAY = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="needs a display for a real terminal",
)


@_NEEDS_DISPLAY
def test_the_classes_the_rule_takes_for_windows_are_the_windows_gtk_has_against_real_gtk():
    """The names the rule leaves out are the ones that are no window, and no class ending in
    Window or Dialog that GTK has is left out by mistake."""
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _CLASSES_SCRIPT],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    gtk = json.loads(result.stdout)

    not_windows = set(gtk["names"]) - set(gtk["windows"])
    assert not_windows == NOT_WINDOWS, not_windows
    assert all(gtk["also"].values()), gtk["also"]
    assert {name for name in gtk["names"] if is_window_class(name)} == set(gtk["windows"])


# -- real GTK ---------------------------------------------------------------------------------

_SCRIPT = r'''
import faulthandler, os, sys, tempfile, time, traceback
faulthandler.dump_traceback_later(100, exit=True)
scenario = sys.argv[1]
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["SHELL"] = "/bin/sh"; sys.argv = ["gcm"]
os.environ.pop("XDG_CONFIG_HOME", None)
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0"); gi.require_version("Vte", "2.91")
from gi.repository import GLib, Gtk
from gnome_connection_manager import app

app.conf.CONFIRM_ON_CLOSE_TAB = 0
app.conf.STARTUP_LOCAL = False  # only the tabs each scenario opens
app.conf.CHECK_UPDATES = False
app.wMain = w = app.Wmain(application=None)
main = w.wMain
failures = []

# A callback that raises is printed by PyGObject and the script goes on, and a dialog
# nobody answers holds run() until the watchdog above ends the process. So a look is
# recorded and every dialog answered in a finally, and what was seen is judged once the
# call has returned.

def pump(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        Gtk.main_iteration_do(False)
        time.sleep(0.005)

def shown():
    """The toplevels up: not a menu or a tooltip, whose windows are of a kind of their own."""
    return [each for each in Gtk.Window.list_toplevels()
            if each.get_visible() and each.get_window_type() == Gtk.WindowType.TOPLEVEL]

def unparented():
    """What is up with no parent: only the main window and a console window may be."""
    return [type(each).__name__ for each in shown()
            if each is not main and each not in w.console_windows and each.get_transient_for() is None]

def name_of(window):
    if window is None:
        return "nothing"
    if window is main:
        return "the main window"
    if window in w.console_windows:
        return "a console window"
    return "%s %r" % (type(window).__name__, window.get_title())

def check(case, parent, expected):
    print("%s: over %s" % (case, name_of(parent)))
    if parent is not expected:
        failures.append("%s: over %s, not %s" % (case, name_of(parent), name_of(expected)))

def at(window, call):
    """`call`, made with `window` the window in use: another window's activation can move it."""
    def run():
        w.window_in_use = window
        assert w.window_in_use is window
        return call()
    return run

def ask(case, kind, call, expected, keep=()):
    """`call` opens a dialog of `kind` and waits in it. A moment on, the dialog is read and
    answered with Cancel, whatever goes wrong; what it was over is judged after."""
    seen = {}

    def look():
        seen["looked"] = True
        found = []
        try:
            found = [each for each in shown() if isinstance(each, kind)]
            seen["parents"] = [each.get_transient_for() for each in found]
            seen["unparented"] = unparented()
        except BaseException:
            seen["error"] = traceback.format_exc()
        finally:
            others = [each for each in shown() if isinstance(each, Gtk.Dialog) and each not in keep]
            for each in found or others:
                each.response(Gtk.ResponseType.CANCEL)
        return False

    source = GLib.timeout_add(100, look)
    try:
        call()
    finally:
        if "looked" not in seen:
            GLib.source_remove(source)
    if "error" in seen:
        raise AssertionError(case + ": " + seen["error"])
    count = len(seen.get("parents", ()))
    if count != 1:
        raise AssertionError("%s: %d dialogs of %s were up" % (case, count, kind.__name__))
    check(case, seen["parents"][0], expected)
    if seen["unparented"]:
        failures.append("%s: also up with no parent: %s" % (case, seen["unparented"]))

def is_kind(window, kind):
    if isinstance(kind, str):
        return Gtk.Buildable.get_name(window) == kind
    return isinstance(window, kind)

def open_window(case, make, kind):
    """`make` leaves one window up, of `kind`: a class, or the name glade gave it."""
    before = shown()
    make()
    pump(0.3)
    new = [each for each in shown() if each not in before]
    if len(new) != 1 or not is_kind(new[0], kind):
        raise AssertionError("%s: opened %s" % (case, [type(each).__name__ for each in new]))
    return new[0]

def opened(case, make, kind, expected):
    window = open_window(case, make, kind)
    check(case, window.get_transient_for(), expected)
    if unparented():
        failures.append("%s: also up with no parent: %s" % (case, unparented()))
    window.destroy()
    pump(0.1)

def open_tabs(*names):
    for name in names:
        w.addTab(w.nbConsole, app.Host("", name))
    pump(0.5)
    return [w.nbConsole.get_nth_page(each) for each in range(len(names))]

def terminal_of(page):
    return app.page_terminal(page)

def battery(in_use, expected, terminal):
    """Everything GCM opens from a window, with `in_use` the window in use: each over
    `expected`, bar the two that name the main window, as the update notice and the server
    tree's Import do."""
    snippet = app.snippetlib.Snippet("00000001", "greet", "echo {?Word}\r")
    for case, kind, call, parent in (
        ("msgbox", Gtk.MessageDialog, lambda: app.msgbox("An error"), expected),
        ("msginfo", Gtk.MessageDialog, lambda: app.msginfo("A notice"), expected),
        ("msgconfirm", Gtk.MessageDialog, lambda: app.msgconfirm("A question"), expected),
        ("inputbox", app.EntryDialog, lambda: app.inputbox("Title", "Text"), expected),
        ("choose_tab_color", Gtk.ColorChooserDialog, lambda: app.choose_tab_color(""), expected),
        ("Save Buffer", Gtk.FileChooserDialog, lambda: w.show_save_buffer(terminal), expected),
        ("a {?Label} prompt", app.EntryDialog, lambda: w.send_snippet(snippet, terminal), expected),
        ("a message naming the main window", Gtk.MessageDialog,
         lambda: app.msginfo("A notice", main), main),
        ("the server tree's chooser", Gtk.FileChooserDialog,
         lambda: app.show_open_dialog(main, "Open", Gtk.FileChooserAction.OPEN), main),
    ):
        ask(case, kind, at(in_use, call), parent)
    for case, kind, make in (
        ("the host dialog", "wHost", lambda: w.on_btnAdd_clicked(None)),
        ("Preferences", "wConfig", lambda: w.on_btnConfig_clicked(None)),
        ("About", "wAbout", lambda: w.on_acerca_de1_activate(None)),
        ("the cluster window", "wCluster", lambda: w.on_btnCluster_clicked(None)),
        ("the buffer viewer", app.BufferViewer, lambda: w.show_buffer_viewer(terminal)),
        ("the snippet picker", app.SnippetPicker, lambda: w.show_snippet_picker(terminal)),
    ):
        opened(case, at(in_use, make), kind, expected)

if scenario == "the-main-window-in-use":
    # As at the start, when no window has been active yet, and no console window is open.
    [page] = open_tabs("A")
    assert not w.console_windows
    battery(None, main, terminal_of(page))

elif scenario == "the-main-window-in-use-beside-a-console-window":
    page, other = open_tabs("A", "B")
    console = w.move_to_new_window(other)
    pump(0.5)
    assert w.console_windows == (console,) and console.get_visible()
    battery(main, main, terminal_of(page))

elif scenario == "a-console-window-in-use":
    page, other = open_tabs("A", "B")
    console = w.move_to_new_window(other)
    pump(0.5)
    assert w.console_windows == (console,) and console.get_visible()
    battery(console, console, terminal_of(other))

elif scenario == "over-another-dialog":
    # A window opened from a modal one is over it, a chain down to the main window.
    w.window_in_use = None
    host = app.Whost()
    host.init("")
    window = host.get_widget("wHost")
    pump(0.3)
    check("the host dialog", window.get_transient_for(), main)
    if app.modal_window() is not window:
        failures.append("the host dialog is not the modal window on top")
    ask("a message of the host dialog's own", Gtk.MessageDialog,
        lambda: host.on_okbutton1_clicked(None), window, keep=[window])
    if app.modal_window() is not window:
        failures.append("the host dialog does not hold the grab again after the message")
    ask("the Browse chooser", Gtk.FileChooserDialog,
        lambda: host.on_btnBrowse_clicked(None), window, keep=[window])
    ask("a prompt over the host dialog", app.EntryDialog,
        lambda: app.inputbox("Title", "Text"), window, keep=[window])
    ask("a question over the host dialog", Gtk.MessageDialog,
        lambda: app.msgconfirm("A question"), window, keep=[window])
    host.on_cancelbutton1_clicked(None)
    pump(0.2)
    if app.modal_window() is not None:
        failures.append("a window is modal after the host dialog closed")

    config = app.Wconfig()
    window = config.get_widget("wConfig")
    pump(0.3)
    check("Preferences", window.get_transient_for(), main)
    ask("a message over Preferences", Gtk.MessageDialog,
        lambda: app.msgbox("An error"), window, keep=[window])
    ask("the font chooser over Preferences", Gtk.FontChooserDialog,
        lambda: config.on_btnFont_clicked(None), window, keep=[window])
    ask("a message naming the main window, over Preferences", Gtk.MessageDialog,
        lambda: app.msgbox("An error", main), window, keep=[window])
    window.destroy()
    pump(0.2)

else:
    raise SystemExit("no scenario " + scenario)

if failures:
    print("\n".join(failures))
    sys.exit(1)
print("OK")
'''


def _run(scenario):
    pytest.importorskip("gi", reason="PyGObject not available")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, scenario],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=120,
    )
    report = result.stdout[-3000:] + result.stderr[-3000:]

    assert result.returncode == 0, report
    assert "OK" in result.stdout, report
    # A callback that raises is printed, and the scenario goes on to exit 0.
    assert "Traceback" not in result.stderr, result.stderr[-3000:]
    assert glib_complaints(result.stderr) == [], result.stderr[-3000:]


@_NEEDS_DISPLAY
@pytest.mark.parametrize(
    "scenario",
    [
        "the-main-window-in-use",
        "the-main-window-in-use-beside-a-console-window",
        "a-console-window-in-use",
    ],
)
def test_every_window_opens_over_the_window_in_use_against_real_gtk(scenario):
    _run(scenario)


@_NEEDS_DISPLAY
def test_a_window_opened_from_a_dialog_is_over_it_against_real_gtk():
    _run("over-another-dialog")
