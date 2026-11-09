"""install.sh, the one-line installer (#294): what it installs, and what an update keeps.

Each scenario installs from a repository of its own, a few commits tagged as releases,
into a home of its own whose path holds a space, with git real and sudo, apt-get and
dpkg-query faked. The script is piped to bash, as `curl ... | bash` runs it, so a command
in it that read its input would eat the rest of the script. `awk` is mawk where it is
installed, as on a new Ubuntu. A version's package is a fake that reports what it was
started with, so the launcher is tested without GTK; the real GCM it installs was started
by hand on Xvfb.

The Python the script checks (#564) is the real /usr/bin/python3 unless a scenario swaps
the script's `PYTHON=` line for a fake interpreter, which answers with a version of the
scenario's choosing. The upstream holds the real pyproject.toml, so every scenario that
does not swap it checks the real floor against the real Python.

The script asks on the terminal whether to install GCM's optional programs, so it runs in
a session of its own, with no terminal to ask on, unless a scenario gives it one and
answers there: run from a developer's terminal, it would ask there.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pty
import re
import select
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "install.sh"

# What the .deb depends on and recommends, from the Makefile, and git.
PACKAGES = [
    "python3",
    "python3-gi",
    "python3-gi-cairo",
    "gir1.2-gtk-3.0",
    "gir1.2-vte-2.91",
    "expect",
    "python3-pyaes",
    "gir1.2-gtk-vnc-2.0",
    "git",
]

# What it suggests, from the Makefile: GCM's optional programs, installed when asked for.
# An alternative is named as its first, the one installed.
OPTIONAL = ["freerdp3-x11", "xdg-utils", "sshfs", "nautilus", "gvfs-backends"]

# The rest of each alternative, any of which is enough: FreeRDP 2's client, for FreeRDP 3's.
ALTERNATIVES = ["freerdp2-x11"]

# How the question ends, on the terminal.
QUESTION_END = b"[y/N] "

# The line of install.sh that names the Python the launcher runs and the check asks (#564),
# and the line that runs `main`, which a test of one function runs its calls in place of.
PYTHON_LINE = "PYTHON=/usr/bin/python3"
LAST_LINE = '{ main "$@"; }'

# What `Rig.release` is given to leave a file as it is: None removes the file.
KEEP: Any = object()

# Run in a session of its own, it opens the terminal named first, which so becomes its
# controlling terminal, the one /dev/tty opens, and runs the rest.
TAKE_TERMINAL = (
    "import os, sys; os.close(os.open(sys.argv[1], os.O_RDWR)); "
    "os.execvp(sys.argv[2], sys.argv[2:])"
)

# A version's gnome_connection_manager.__main__: it reports what the launcher gave it,
# after waiting, while GCM_TEST_WAIT names a file that is not there yet.
FAKE_MAIN = """\
import json
import os
import sys
import time


def inheritable_descriptors():
    found = []
    for name in os.listdir("/proc/self/fd"):
        try:
            if os.get_inheritable(int(name)):
                found.append(int(name))
        except OSError:
            pass
    return sorted(found)


def main():
    wait = os.environ.get("GCM_TEST_WAIT")
    if wait:
        open(wait + ".started", "w").close()
        deadline = time.monotonic() + 60
        while not os.path.exists(wait) and time.monotonic() < deadline:
            time.sleep(0.05)
    report = {
        "file": __file__,
        "file_exists": os.path.exists(__file__),
        "environ": dict(os.environ),
        "inheritable": inheritable_descriptors(),
    }
    path = os.environ["GCM_TEST_REPORT"]
    with open(path + ".tmp", "w") as out:
        json.dump(report, out)
    os.replace(path + ".tmp", path)
    return 0
"""

FAKE_SUDO = """\
#!/bin/sh
echo "sudo $*" >> "$FAKE_LOG"
exec "$@"
"""

# Installs nothing, except git when asked to and FAKE_GIT_TO names where it goes, and
# python3 when asked to: FAKE_PYTHON_TO names where it goes, and FAKE_PYTHON_FROM the
# interpreter that appears there. python3 is matched as a word of its own, not as the start
# of python3-gi. It fails to install what FAKE_APT_FAIL names. It reads all of its input
# first: piped, the script must not be there to read.
FAKE_APT_GET = """\
#!/bin/sh
cat > /dev/null
echo "apt-get $*" >> "$FAKE_LOG"
case " $* " in
    *" install "*" git "*) [ -n "$FAKE_GIT_TO" ] && ln -s /usr/bin/git "$FAKE_GIT_TO/git" ;;
esac
case " $* " in
    *" install "*" python3 "*) [ -n "$FAKE_PYTHON_TO" ] && cp "$FAKE_PYTHON_FROM" "$FAKE_PYTHON_TO" ;;
esac
if [ -n "$FAKE_APT_FAIL" ]; then
    case " $* " in
        *" install "*" $FAKE_APT_FAIL "*)
            echo "E: Unable to locate package $FAKE_APT_FAIL" >&2
            exit 100 ;;
    esac
fi
exit 0
"""

# Every package is installed, but those FAKE_MISSING names.
FAKE_DPKG_QUERY = """\
#!/bin/sh
for package; do :; done
case " $FAKE_MISSING " in
    *" $package "*)
        echo "dpkg-query: no packages found matching $package" >&2
        exit 1 ;;
esac
printf 'install ok installed'
"""


def git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    done = subprocess.run(
        ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def tree_digest(folder: Path) -> dict[str, str]:
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def script_text(python: Path | None = None) -> str:
    """install.sh as it is piped, with its `PYTHON=` line naming `python` if one is given."""
    text = SCRIPT.read_text(encoding="utf-8")
    if python is None:
        return text
    line = re.compile(rf"^{re.escape(PYTHON_LINE)}$", re.MULTILINE)
    assert len(line.findall(text)) == 1, f"install.sh must have one line, {PYTHON_LINE}"
    return line.sub(lambda _: f"PYTHON={shlex.quote(str(python))}", text)


def fake_python(path: Path, reply: str | None) -> Path:
    """An interpreter that answers whatever it is asked with `reply`, or fails if that is None.

    It goes in a folder of the test's own and never in the home, whose path holds a space on
    purpose: the launcher's first line names it, and a shebang cannot hold a space.
    """
    body = "exit 1" if reply is None else f"echo {shlex.quote(reply)}"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def pyproject_requiring(floor: str) -> str:
    """A pyproject.toml that asks for Python `floor` or newer, in the form install.sh reads."""
    return f'[project]\nname = "fake"\nrequires-python = ">={floor}"\n'


@dataclass
class Rig:
    root: Path
    home: Path
    upstream: Path
    fakebin: Path
    log: Path

    @property
    def gcm_home(self) -> Path:
        return self.home / ".local" / "share" / "gnome-connection-manager"

    @property
    def versions(self) -> Path:
        return self.gcm_home / "versions"

    @property
    def launcher(self) -> Path:
        return self.home / ".local" / "bin" / "gnome-connection-manager"

    @property
    def desktop_entry(self) -> Path:
        return self.home / ".local" / "share" / "applications" / "gnome-connection-manager.desktop"

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "PATH": f"{self.fakebin}:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "GCM_REPO_URL": str(self.upstream),
            "FAKE_LOG": str(self.log),
            "FAKE_MISSING": "",
            "FAKE_GIT_TO": "",
            "FAKE_PYTHON_FROM": "",
            "FAKE_PYTHON_TO": "",
            "FAKE_APT_FAIL": "",
            **extra,
        }

    def install(
        self,
        *args: str,
        ok: bool = True,
        cwd: Path | None = None,
        python: Path | None = None,
        **env: str,
    ) -> subprocess.CompletedProcess[str]:
        """Pipes the script to bash. Given `python`, the script checks and runs that one."""
        done = subprocess.run(
            ["bash", "-s", "--", *args],
            input=script_text(python),
            env=self.env(**env),
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,
        )
        if ok:
            assert done.returncode == 0, done.stdout + done.stderr
        return done

    def run_functions(
        self, calls: str, python: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Runs `calls` in place of the script's last line, which would run `main`.

        Piped to bash as an install pipes it, so `set -euo pipefail` holds for the functions
        run, and nothing is cut out of the text.
        """
        text = script_text(python)
        assert text.endswith(f"{LAST_LINE}\n"), "install.sh no longer ends by running main"
        return subprocess.run(
            ["bash", "-s", "--"],
            input=text.removesuffix(f"{LAST_LINE}\n") + calls + "\n",
            env=self.env(),
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,
        )

    def install_on_terminal(
        self, answer: str | None, *args: str, **env: str
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        """Runs the script as `install` does, but with a terminal of its own to ask on.

        `answer` is typed at the question, and the scenario fails if the question is asked
        while it is None. Returns the run, and what the terminal showed.
        """
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                [sys.executable, "-c", TAKE_TERMINAL, os.ttyname(slave), "bash", "-s", "--", *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env(**env),
                cwd=self.root,
                text=True,
                start_new_session=True,
            )
            assert process.stdin is not None
            # bash reads all of it before it runs anything: its last line runs the rest.
            process.stdin.write(SCRIPT.read_text(encoding="utf-8"))
            process.stdin.close()
            shown = b""
            deadline = time.monotonic() + 60
            while QUESTION_END not in shown and process.poll() is None:
                assert time.monotonic() < deadline, shown
                if select.select([master], [], [], 0.1)[0]:
                    shown += os.read(master, 4096)
            if QUESTION_END in shown:
                if answer is None:
                    process.kill()
                    pytest.fail(f"asked, with nothing to ask about: {shown!r}")
                os.write(master, answer.encode() + b"\n")
            # Its output is a few lines, which the pipes hold until they are read.
            process.wait(timeout=60)
            while select.select([master], [], [], 0.1)[0]:
                shown += os.read(master, 4096)
        finally:
            os.close(master)
            os.close(slave)
        assert process.stdout is not None and process.stderr is not None
        done = subprocess.CompletedProcess(
            process.args, process.returncode, process.stdout.read(), process.stderr.read()
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done, shown.decode().replace("\r\n", "\n")

    def release(self, tag: str, makefile: str | None = None, pyproject: str | None = KEEP) -> str:
        """Commits and tags the upstream as `tag`. A `makefile` or `pyproject` replaces that
        file first, and `pyproject=None` removes it."""
        if makefile is not None:
            (self.upstream / "Makefile").write_text(makefile, encoding="utf-8")
        if pyproject is None:
            (self.upstream / "pyproject.toml").unlink()
        elif pyproject is not KEEP:
            (self.upstream / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        (self.upstream / "RELEASE").write_text(tag, encoding="utf-8")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-q", "-m", tag)
        git(self.upstream, "tag", tag)
        return git(self.upstream, "rev-parse", "HEAD")

    def commit(self) -> str:
        count = len(git(self.upstream, "log", "--oneline").splitlines())
        (self.upstream / "RELEASE").write_text(f"main {count}", encoding="utf-8")
        git(self.upstream, "commit", "-q", "-am", f"main {count}")
        return git(self.upstream, "rev-parse", "HEAD")

    def link(self, name: str) -> str | None:
        path = self.gcm_home / name
        return str(path.readlink()) if path.is_symlink() else None

    def installed(self) -> list[str]:
        return sorted(p.name for p in self.versions.iterdir()) if self.versions.is_dir() else []

    def launch(self, **env: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [str(self.launcher)],
            env={
                "HOME": str(self.home),
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "SHELL": "/bin/sh",
                "GCM_TEST_REPORT": str(self.root / "report.json"),
                **env,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def report(self) -> dict[str, Any]:
        report: dict[str, Any] = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        return report


class RunningGcm:
    """A GCM started from the launcher, holding its version until `finish`."""

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.wait = rig.root / "go-on"
        self.process = rig.launch(GCM_TEST_WAIT=str(self.wait))
        started = Path(f"{self.wait}.started")
        deadline = time.monotonic() + 30
        while not started.exists():
            assert self.process.poll() is None, self.process.communicate()
            assert time.monotonic() < deadline, "the launcher never started its version"
            time.sleep(0.05)

    def finish(self) -> dict[str, Any]:
        self.wait.touch()
        out, err = self.process.communicate(timeout=30)
        assert self.process.returncode == 0, out + err
        return self.rig.report()


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    upstream = tmp_path / "upstream"
    package = upstream / "src" / "gnome_connection_manager"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(FAKE_MAIN, encoding="utf-8")
    (upstream / "data").mkdir()
    shutil.copy(REPO_ROOT / "data" / "icon.png", upstream / "data")
    shutil.copy(REPO_ROOT / "Makefile", upstream)
    # The real pyproject.toml, so that every scenario runs the Python check against the real
    # floor and the real /usr/bin/python3 (#564). Each therefore needs that Python to meet
    # requires-python: a later raise of the floor fails every one of them where it is older.
    shutil.copy(REPO_ROOT / "pyproject.toml", upstream)
    shutil.copy(REPO_ROOT / "gnome-connection-manager.desktop", upstream)
    subprocess.run(["git", "init", "-q", "-b", "main", str(upstream)], check=True)

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for name, text in (
        ("sudo", FAKE_SUDO),
        ("apt-get", FAKE_APT_GET),
        ("dpkg-query", FAKE_DPKG_QUERY),
    ):
        (fakebin / name).write_text(text, encoding="utf-8")
        (fakebin / name).chmod(0o755)
    if Path("/usr/bin/mawk").exists():
        (fakebin / "awk").symlink_to("/usr/bin/mawk")

    home = tmp_path / "a home"
    home.mkdir()
    return Rig(root=tmp_path, home=home, upstream=upstream, fakebin=fakebin, log=tmp_path / "log")


def programs_without(tmp_path: Path, *names: str) -> Path:
    """A folder of links to every program in /usr/bin and /bin but those named."""
    folder = tmp_path / "programs"
    folder.mkdir()
    for directory in (Path("/usr/bin"), Path("/bin")):
        for program in directory.iterdir():
            link = folder / program.name
            if program.name not in names and not link.is_symlink():
                link.symlink_to(program)
    return folder


# -- what it installs ------------------------------------------------------------------


def test_installs_the_newest_release(rig: Rig) -> None:
    """Numbers compared as numbers, and a tag that is not vX.Y.Z is no release."""
    for tag in ("v1.0.0", "v1.10.0", "v1.2.0", "v2.0.0-rc1", "vnext"):
        rig.release(tag)

    done = rig.install()

    assert rig.link("current") == "versions/v1.10.0"
    assert rig.installed() == ["v1.10.0"]
    assert "GCM v1.10.0 is installed." in done.stdout
    assert os.access(rig.launcher, os.X_OK)


def test_the_launcher_starts_the_version_current_names_resolved(rig: Rig) -> None:
    """Through `current` itself, an update would hand a running GCM another's files."""
    rig.release("v1.0.0")
    rig.install()

    process = rig.launch()
    out, err = process.communicate(timeout=30)

    assert process.returncode == 0, out + err
    assert rig.report()["file"] == str(
        rig.versions / "v1.0.0" / "src" / "gnome_connection_manager" / "__main__.py"
    )


def test_a_shell_in_a_tab_inherits_nothing_from_the_launcher(rig: Rig) -> None:
    """Its environment is the one it was given, and its lock is not inherited.

    Given the GCM_*_DIR a console of another GCM passes on, as when GCM is started from
    one of its own tabs, it drops them: the version's main() keeps any it finds.
    """
    rig.release("v1.0.0")
    rig.install()
    inherited = {
        "GCM_DATA_DIR": "/elsewhere/data",
        "GCM_GLADE_DIR": "/elsewhere/data/ui",
        "GCM_SCRIPTS_DIR": "/elsewhere/data/scripts",
    }

    process = rig.launch(**inherited)
    out, err = process.communicate(timeout=30)

    assert process.returncode == 0, out + err
    report = rig.report()
    assert report["environ"] == {
        "HOME": str(rig.home),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "SHELL": "/bin/sh",
        "GCM_TEST_REPORT": str(rig.root / "report.json"),
    }
    assert report["inheritable"] == [0, 1, 2]


@pytest.mark.parametrize(("home_name", "exec_value"), [("home", "{}"), ("a home", '"{}"')])
def test_the_desktop_entry_starts_the_launcher(rig: Rig, home_name: str, exec_value: str) -> None:
    """The version's own entry with Exec and Icon replaced, launched as a menu does.

    Exec is quoted only for a path that needs it: GLib launches a quoted one correctly,
    but its get_executable gives the text up to the first space, quote and all, measured.
    """
    rig = replace(rig, home=rig.root / home_name)
    rig.home.mkdir(exist_ok=True)
    rig.release("v1.0.0")
    rig.install()

    written = rig.desktop_entry.read_text(encoding="utf-8").splitlines()
    source = (rig.upstream / "gnome-connection-manager.desktop").read_text().splitlines()
    assert written[0].startswith("# Written by GCM's install.sh")
    assert f"Exec={exec_value.format(rig.launcher)}" in written
    assert f"Icon={rig.gcm_home}/current/data/icon.png" in written
    kept = [line for line in source if not line.startswith(("Exec=", "Icon="))]
    assert [line for line in written[1:] if not line.startswith(("Exec=", "Icon="))] == kept
    if shutil.which("desktop-file-validate"):
        checked = subprocess.run(
            ["desktop-file-validate", str(rig.desktop_entry)], capture_output=True, text=True
        )
        assert checked.returncode == 0, checked.stdout

    gio = "import sys, gi; gi.require_version('Gio', '2.0'); from gi.repository import Gio"
    if subprocess.run(["/usr/bin/python3", "-c", gio], capture_output=True).returncode:
        pytest.skip("no GLib to launch the entry with")
    launch = f"{gio}; sys.exit(not Gio.DesktopAppInfo.new_from_filename(sys.argv[1]).launch([]))"
    launched = subprocess.run(
        ["/usr/bin/python3", "-c", launch, str(rig.desktop_entry)],
        env={
            "HOME": str(rig.home),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "SHELL": "/bin/sh",
            "GCM_TEST_REPORT": str(rig.root / "report.json"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert launched.returncode == 0, launched.stderr
    deadline = time.monotonic() + 30
    while not (rig.root / "report.json").exists():
        assert time.monotonic() < deadline, "the entry never started the launcher"
        time.sleep(0.05)
    assert rig.report()["file"].startswith(str(rig.versions / "v1.0.0"))


def test_installs_main_and_follows_it(rig: Rig) -> None:
    """`main` is remembered: a run given nothing then installs main's new tip."""
    rig.release("v1.0.0")
    first = rig.commit()
    rig.install("main")
    assert rig.link("current") == f"versions/main-{first[:12]}"

    second = rig.commit()
    done = rig.install()

    assert rig.link("current") == f"versions/main-{second[:12]}"
    assert rig.link("previous") == f"versions/main-{first[:12]}"
    assert f"in place of main-{first[:12]}" in done.stdout


def test_installs_the_release_asked_for_once(rig: Rig) -> None:
    """A vX.Y.Z is not remembered: the next run given nothing follows release or main,
    whichever was given last."""
    rig.release("v1.0.0")
    rig.release("v1.1.0")

    rig.install("v1.0.0")
    assert rig.link("current") == "versions/v1.0.0"
    rig.install()
    assert rig.link("current") == "versions/v1.1.0"

    tip = rig.commit()
    rig.install("main")
    rig.install("v1.0.0")
    rig.install()
    assert rig.link("current") == f"versions/main-{tip[:12]}"


def test_a_release_that_does_not_exist_changes_nothing(rig: Rig) -> None:
    rig.release("v1.0.0")
    rig.install()

    done = rig.install("v9.9.9", ok=False)

    assert done.returncode == 1
    assert "has no release v9.9.9" in done.stderr
    assert rig.link("current") == "versions/v1.0.0"


def test_refuses_an_unknown_argument_before_doing_anything(rig: Rig) -> None:
    rig.release("v1.0.0")

    done = rig.install("--update", ok=False)

    assert done.returncode == 1
    assert "unknown argument: --update" in done.stderr
    assert not rig.gcm_home.exists()


def test_help_installs_nothing(rig: Rig) -> None:
    done = rig.install("--help")

    assert "install.sh --uninstall" in done.stdout
    assert not rig.gcm_home.exists()


def test_runs_again_with_nothing_new(rig: Rig) -> None:
    rig.release("v1.0.0")
    rig.install()

    done = rig.install()

    assert "GCM v1.0.0 is installed already." in done.stdout
    assert rig.link("previous") is None


@pytest.mark.parametrize("relative", [False, True])
def test_xdg_data_home_is_used_when_absolute(rig: Rig, relative: bool) -> None:
    """A relative one is ignored, as the XDG spec has it."""
    rig.release("v1.0.0")
    data_home = "data" if relative else str(rig.root / "data")

    rig.install(XDG_DATA_HOME=data_home)

    expected = rig.gcm_home if relative else rig.root / "data" / "gnome-connection-manager"
    assert (expected / "current").is_symlink()
    assert f'"{expected}/current"' in rig.launcher.read_text(encoding="utf-8")


def test_says_when_its_folder_is_not_on_path(rig: Rig) -> None:
    rig.release("v1.0.0")

    away = rig.install()
    on_path = rig.install(PATH=f"{rig.fakebin}:{rig.launcher.parent}:/usr/bin:/bin")

    assert f"{rig.launcher.parent} is not on your PATH yet" in away.stdout
    assert "PATH" not in on_path.stdout


@pytest.mark.parametrize("character", ['"', "%", "$"])
def test_refuses_a_home_it_cannot_write_into_the_launcher(rig: Rig, character: str) -> None:
    """The path goes into a Python string and a desktop entry's Exec, unescaped."""
    rig.release("v1.0.0")
    home = rig.root / f"odd{character}home"
    home.mkdir()

    done = rig.install(HOME=str(home), ok=False)

    assert done.returncode == 1
    assert "cannot install under" in done.stderr
    assert list(home.iterdir()) == []


# -- packages ----------------------------------------------------------------------------


def test_installs_the_packages_the_deb_names(rig: Rig) -> None:
    """Told what apt will install, then apt's lists brought up to date first."""
    rig.release("v1.0.0")

    done = rig.install(FAKE_MISSING=" ".join(PACKAGES))

    assert f"apt will install what GCM needs: {' '.join(PACKAGES)}" in done.stdout
    assert rig.log.read_text().splitlines() == [
        "sudo apt-get update",
        "apt-get update",
        f"sudo apt-get install -y {' '.join(PACKAGES)}",
        f"apt-get install -y {' '.join(PACKAGES)}",
    ]


def test_installs_what_a_new_version_needs(rig: Rig) -> None:
    """Read from the version installed, not held by the script."""
    rig.release("v1.0.0")
    rig.install()
    makefile = (rig.upstream / "Makefile").read_text(encoding="utf-8")
    needing_more = makefile.replace(
        "\t\t-d expect \\\n", "\t\t-d expect \\\n\t\t-d new-package \\\n"
    )
    assert needing_more != makefile
    rig.release("v1.1.0", makefile=needing_more)

    rig.install(FAKE_MISSING="new-package")

    assert "sudo apt-get install -y new-package" in rig.log.read_text().splitlines()


def test_asks_for_nothing_when_everything_is_installed(rig: Rig) -> None:
    rig.release("v1.0.0")

    rig.install()

    assert not rig.log.exists()


def test_without_apt_says_what_is_needed(rig: Rig) -> None:
    rig.release("v1.0.0")
    programs = programs_without(rig.root, "apt-get", "dpkg-query", "sudo")
    (rig.fakebin / "apt-get").unlink()
    (rig.fakebin / "dpkg-query").unlink()

    done = rig.install(PATH=f"{rig.fakebin}:{programs}")

    assert (
        f"There is no apt here to install what GCM needs. In Debian's names: {' '.join(PACKAGES)}"
        in done.stdout
    )
    assert f"Its optional programs, if you want them: {' '.join(OPTIONAL)}" in done.stdout
    assert rig.link("current") == "versions/v1.0.0"


def test_without_git_installs_it_first(rig: Rig) -> None:
    rig.release("v1.0.0")
    programs = programs_without(rig.root, "git")

    rig.install(PATH=f"{rig.fakebin}:{programs}", FAKE_MISSING="git", FAKE_GIT_TO=str(programs))

    assert rig.log.read_text().splitlines()[:4] == [
        "sudo apt-get update",
        "apt-get update",
        "sudo apt-get install -y git",
        "apt-get install -y git",
    ]
    assert rig.link("current") == "versions/v1.0.0"


# -- the Python a version needs (#564) ---------------------------------------------------


def test_refuses_a_python_older_than_the_version_needs_before_apt_installs_its_packages(
    rig: Rig,
) -> None:
    """python3 is installed and too old: nothing of GCM's goes in, not by apt and not in the
    home. A package is missing, so that apt would run were it not for the check."""
    rig.release("v1.0.0", pyproject=pyproject_requiring("3.12"))
    python = fake_python(rig.root / "python3", "3.10")

    done = rig.install(python=python, FAKE_MISSING="python3-pyaes", ok=False)

    assert done.returncode == 1
    assert (
        f"install.sh: GCM v1.0.0 needs Python 3.12 or newer, and {python} is Python 3.10, "
        "so GCM was not installed. install.sh --uninstall removes what this run fetched.\n"
    ) in done.stderr
    assert rig.link("current") is None
    assert not rig.launcher.exists()
    assert not rig.desktop_entry.exists()
    assert not rig.log.exists()


def test_an_update_to_a_version_needing_a_newer_python_keeps_the_one_in_use(rig: Rig) -> None:
    """Refused before `use_version`, so `current`, `previous`, `channel` and the launcher stay
    as they were. The refused version's worktree stays too, as after a run cut short."""
    rig.release("v1.0.0")
    rig.install()
    launcher = rig.launcher.read_bytes()
    rig.release("v1.1.0", pyproject=pyproject_requiring("3.99"))

    done = rig.install("release", ok=False)

    assert done.returncode == 1
    assert "GCM v1.1.0 needs Python 3.99 or newer, and /usr/bin/python3 is Python " in done.stderr
    assert done.stderr.endswith(". v1.0.0 stays in use.\n")
    assert rig.link("current") == "versions/v1.0.0"
    assert rig.link("previous") is None
    assert not (rig.gcm_home / "channel").exists()
    assert rig.launcher.read_bytes() == launcher
    assert rig.installed() == ["v1.0.0", "v1.1.0"]


def test_checks_the_python_apt_installs(rig: Rig) -> None:
    """With no python3 until apt installs one, the check before apt has nothing to ask. The
    one after it asks the Python apt put there, and refuses before anything is made current."""
    rig.release("v1.0.0", pyproject=pyproject_requiring("3.12"))
    installed = rig.root / "python3"
    staged = fake_python(rig.root / "staged-python3", "3.10")

    done = rig.install(
        python=installed,
        FAKE_MISSING="python3",
        FAKE_PYTHON_FROM=str(staged),
        FAKE_PYTHON_TO=str(installed),
        ok=False,
    )

    assert done.returncode == 1
    assert f"GCM v1.0.0 needs Python 3.12 or newer, and {installed} is Python 3.10" in done.stderr
    assert "apt-get install -y python3" in rig.log.read_text().splitlines()
    assert rig.link("current") is None
    assert not rig.launcher.exists()
    assert not rig.desktop_entry.exists()


def test_a_missing_python_without_apt_installs_as_before(rig: Rig) -> None:
    """There is nothing to ask and no apt to install it, which the run has said: it goes on."""
    rig.release("v1.0.0")
    programs = programs_without(rig.root, "apt-get", "dpkg-query", "sudo")
    (rig.fakebin / "apt-get").unlink()
    (rig.fakebin / "dpkg-query").unlink()
    missing = rig.root / "no-python3"

    done = rig.install(python=missing, PATH=f"{rig.fakebin}:{programs}")

    assert "There is no apt here to install what GCM needs. In Debian's names: python3 " in (
        done.stdout
    )
    assert not missing.exists()
    assert rig.link("current") == "versions/v1.0.0"


@pytest.mark.parametrize(
    "pyproject",
    ['[project]\nname = "fake"\n', None],
    ids=["names no Python", "has no pyproject.toml"],
)
def test_a_version_stating_no_floor_installs_whatever_the_python(
    rig: Rig, pyproject: str | None
) -> None:
    """Nothing to check against, and a missing file does not end the script. The launcher's
    first line names the Python that would have been checked."""
    rig.release("v1.0.0", pyproject=pyproject)
    python = fake_python(rig.root / "python3", "3.10")

    done = rig.install(python=python)

    assert done.stderr == ""
    assert rig.link("current") == "versions/v1.0.0"
    assert rig.launcher.read_text(encoding="utf-8").splitlines()[0] == f"#!{python}"


def test_the_launcher_runs_the_python_the_script_checks(rig: Rig) -> None:
    """Its first line is still `#!/usr/bin/python3`: one name, for the check and the launcher."""
    rig.release("v1.0.0")

    rig.install()

    assert rig.launcher.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/python3"


@pytest.mark.parametrize(
    "reply",
    [None, "", "3.x", "Python 3.12.3"],
    ids=["fails", "prints nothing", "prints 3.x", "prints a sentence"],
)
def test_refuses_a_python_that_gives_no_version_before_apt_installs_its_packages(
    rig: Rig, reply: str | None
) -> None:
    """An answer that is not X.Y cannot be compared, and is not taken as good enough."""
    rig.release("v1.0.0", pyproject=pyproject_requiring("3.12"))
    python = fake_python(rig.root / "python3", reply)

    done = rig.install(python=python, FAKE_MISSING="python3-pyaes", ok=False)

    assert done.returncode == 1
    assert f"GCM v1.0.0 needs Python 3.12 or newer, and {python} gave no version number" in (
        done.stderr
    )
    assert rig.link("current") is None
    assert not rig.log.exists()


@pytest.mark.parametrize(
    ("floor", "version", "enough"),
    [
        ("3.12", "2.99", False),
        ("3.12", "3.9", False),
        ("3.12", "3.11", False),
        ("3.12", "3.12", True),
        ("3.12", "3.13", True),
        ("3.12", "4.0", True),
        # A floor written with a leading zero is a number, not an octal one.
        ("3.08", "3.7", False),
        ("3.08", "3.9", True),
    ],
)
def test_compares_the_python_as_numbers(rig: Rig, floor: str, version: str, enough: bool) -> None:
    """Major, then minor: 3.9 is older than 3.12, which a string would put the other way, and
    4.0 is newer. Run as the install runs it, through the script's own functions."""
    versions = rig.root / "versions-of-its-own"
    (versions / "v1.0.0").mkdir(parents=True)
    (versions / "v1.0.0" / "pyproject.toml").write_text(pyproject_requiring(floor), "utf-8")
    python = fake_python(rig.root / "python3", version)

    done = rig.run_functions(
        f"set_paths; VERSIONS={shlex.quote(str(versions))}; VERSION_NAME=v1.0.0; check_python",
        python=python,
    )

    if enough:
        assert (done.returncode, done.stderr) == (0, "")
    else:
        assert done.returncode == 1
        assert f"needs Python {floor} or newer, and {python} is Python {version}" in done.stderr


def test_reads_the_floor_pyproject_states_as_tomllib_does(rig: Rig) -> None:
    """The script reads the line with sed, since the Python it checks may be older than
    tomllib. This holds that reading to tomllib's, in the form test_docs.py takes a floor in."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requires = pyproject["project"]["requires-python"]
    floor = re.fullmatch(r">=\s*(\d+\.\d+)", requires)
    assert floor, f"requires-python is {requires!r}, not a floor install.sh can read"

    done = rig.run_functions(f"python_floor {shlex.quote(str(REPO_ROOT))}")

    assert done.returncode == 0, done.stderr
    assert done.stdout == f"{floor.group(1)}\n"


@pytest.mark.parametrize(
    ("pyproject", "floor"),
    [
        ('[project]\nrequires-python = ">=3.12"\n', "3.12"),
        ('[project]\nname = "fake"\nrequires-python = ">=3.9"\nreadme = "README.md"\n', "3.9"),
        ('requires-python=">=3.12"\n', "3.12"),
        ('requires-python = ">= 3.12"  # the floor\n', "3.12"),
        ('requires-python = ">=3.12"\r\n', "3.12"),
        ('requires-python = ">=3.12.1"\n', ""),
        ('requires-python = ">=3.12,<4"\n', ""),
        ('requires-python = ">3.12"\n', ""),
        ('requires-python = "~=3.12"\n', ""),
        ("requires-python = '>=3.12'\n", ""),
        ('# requires-python = ">=3.12"\n', ""),
        ('[project]\nname = "fake"\n', ""),
        ("", ""),
        (None, ""),
    ],
    ids=[
        "the usual line",
        "among others",
        "no spaces",
        "a space after >= and a comment",
        "a Windows line end",
        "a patch version",
        "an upper bound",
        "a bare >",
        "a compatible release",
        "single quotes",
        "commented out",
        "no such line",
        "an empty file",
        "no file",
    ],
)
def test_reads_a_floor_only_in_the_form_it_checks(
    rig: Rig, pyproject: str | None, floor: str
) -> None:
    """Anything else gives no floor, which checks nothing, and never ends the script."""
    folder = rig.root / "a-version"
    folder.mkdir()
    if pyproject is not None:
        (folder / "pyproject.toml").write_bytes(pyproject.encode())

    done = rig.run_functions(
        f'floor=$(python_floor {shlex.quote(str(folder))}); printf "%s" "$floor"'
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout == floor


# -- the optional programs ---------------------------------------------------------------


def test_offers_the_optional_programs_the_deb_suggests(rig: Rig) -> None:
    """Named on the terminal, and installed on a yes after what GCM needs, on their own."""
    rig.release("v1.0.0")

    done, shown = rig.install_on_terminal(
        "y", FAKE_MISSING=" ".join(["python3-pyaes", *OPTIONAL, *ALTERNATIVES])
    )

    assert shown == (
        "GCM can also use these optional programs, which are not installed:\n"
        f"  {' '.join(OPTIONAL)}\n"
        "Have apt install them too? [y/N] y\n"
    )
    assert "apt will install what GCM needs: python3-pyaes" in done.stdout
    assert f"apt will install GCM's optional programs: {' '.join(OPTIONAL)}" in done.stdout
    assert rig.log.read_text().splitlines() == [
        "sudo apt-get update",
        "apt-get update",
        "sudo apt-get install -y python3-pyaes",
        "apt-get install -y python3-pyaes",
        f"sudo apt-get install -y {' '.join(OPTIONAL)}",
        f"apt-get install -y {' '.join(OPTIONAL)}",
    ]
    assert rig.link("current") == "versions/v1.0.0"


def test_names_only_those_not_installed(rig: Rig) -> None:
    rig.release("v1.0.0")

    _, shown = rig.install_on_terminal("y", FAKE_MISSING="sshfs freerdp3-x11 freerdp2-x11")

    assert "\n  freerdp3-x11 sshfs\n" in shown
    assert rig.log.read_text().splitlines()[-1] == "apt-get install -y freerdp3-x11 sshfs"


def test_an_alternative_installed_is_enough(rig: Rig) -> None:
    """The .deb suggests `freerdp3-x11 | freerdp2-x11`, and GCM runs either one's client,
    so FreeRDP 2's installed leaves FreeRDP 3's unoffered (#273)."""
    rig.release("v1.0.0")

    _, shown = rig.install_on_terminal("y", FAKE_MISSING="sshfs freerdp3-x11")

    assert "\n  sshfs\n" in shown
    assert rig.log.read_text().splitlines()[-1] == "apt-get install -y sshfs"


@pytest.mark.parametrize(
    ("answer", "installs"),
    [("y", True), ("YES", True), ("", False), ("n", False), ("yep", False)],
)
def test_installs_them_only_on_a_yes(rig: Rig, answer: str, installs: bool) -> None:
    """Enter alone is a no, as `[y/N]` says."""
    rig.release("v1.0.0")

    done, _ = rig.install_on_terminal(answer, FAKE_MISSING="sshfs")

    if installs:
        assert rig.log.read_text().splitlines()[-1] == "apt-get install -y sshfs"
    else:
        assert "Left out GCM's optional programs." in done.stdout
        assert not rig.log.exists()
    assert rig.link("current") == "versions/v1.0.0"


def test_offers_what_a_new_version_suggests(rig: Rig) -> None:
    """Read from the version installed, as what it needs is."""
    rig.release("v1.0.0")
    rig.install()
    makefile = (rig.upstream / "Makefile").read_text(encoding="utf-8")
    suggesting_more = makefile.replace(
        "\t\t--deb-suggests sshfs \\\n",
        "\t\t--deb-suggests sshfs \\\n\t\t--deb-suggests new-program \\\n",
    )
    assert suggesting_more != makefile
    rig.release("v1.1.0", makefile=suggesting_more)

    _, shown = rig.install_on_terminal("y", FAKE_MISSING="new-program")

    assert "\n  new-program\n" in shown
    assert rig.log.read_text().splitlines()[-1] == "apt-get install -y new-program"


def test_with_no_terminal_installs_none_of_them(rig: Rig) -> None:
    """As over ssh without one: there is nothing to ask on, and piped, its input is itself."""
    rig.release("v1.0.0")

    done = rig.install(FAKE_MISSING=" ".join([*OPTIONAL, *ALTERNATIVES]))

    assert (
        f"Left out GCM's optional programs, with no terminal to ask on: {' '.join(OPTIONAL)}"
        in done.stdout
    )
    assert not rig.log.exists()
    assert rig.link("current") == "versions/v1.0.0"


def test_asks_nothing_when_all_of_them_are_installed(rig: Rig) -> None:
    """Though apt installs what GCM needs."""
    rig.release("v1.0.0")

    done, shown = rig.install_on_terminal(None, FAKE_MISSING="python3-pyaes")

    assert shown == ""
    assert "optional" not in done.stdout
    assert rig.log.read_text().splitlines()[-1] == "apt-get install -y python3-pyaes"


def test_apt_failing_on_them_leaves_gcm_installed(rig: Rig) -> None:
    rig.release("v1.0.0")

    done, _ = rig.install_on_terminal(
        "y", FAKE_MISSING="python3-pyaes sshfs", FAKE_APT_FAIL="sshfs"
    )

    assert "apt could not install GCM's optional programs, so GCM is installed without them." in (
        done.stdout
    )
    assert "apt-get install -y python3-pyaes" in rig.log.read_text().splitlines()
    assert "GCM v1.0.0 is installed." in done.stdout
    assert rig.link("current") == "versions/v1.0.0"


def test_without_sudo_says_how_to_install_them(rig: Rig) -> None:
    """And asks nothing, as it could not install them."""
    rig.release("v1.0.0")
    programs = programs_without(rig.root, "sudo")
    (rig.fakebin / "sudo").unlink()

    done, shown = rig.install_on_terminal(
        None, PATH=f"{rig.fakebin}:{programs}", FAKE_MISSING="sshfs"
    )

    assert shown == ""
    assert (
        "sudo was not found. For GCM's optional programs, as root, run: apt-get install sshfs"
        in done.stdout
    )
    assert not rig.log.exists()
    assert rig.link("current") == "versions/v1.0.0"


# -- updates ------------------------------------------------------------------------------


def test_an_update_installs_beside_the_version_it_replaces(rig: Rig) -> None:
    """And changes nothing of it, which a GCM running from it reads."""
    rig.release("v1.0.0")
    rig.install()
    before = tree_digest(rig.versions / "v1.0.0")
    rig.release("v1.1.0")

    done = rig.install()

    assert rig.link("current") == "versions/v1.1.0"
    assert rig.link("previous") == "versions/v1.0.0"
    assert rig.installed() == ["v1.0.0", "v1.1.0"]
    assert tree_digest(rig.versions / "v1.0.0") == before
    assert "GCM v1.1.0 is installed, in place of v1.0.0." in done.stdout
    assert "goes on with" not in done.stdout


def test_an_update_keeps_one_previous_version(rig: Rig) -> None:
    for tag in ("v1.0.0", "v1.1.0", "v1.2.0"):
        rig.release(tag)
        rig.install()

    assert rig.installed() == ["v1.1.0", "v1.2.0"]
    assert rig.link("previous") == "versions/v1.1.0"
    worktrees = git(rig.gcm_home / "repo", "worktree", "list", "--porcelain")
    assert str(rig.versions / "v1.0.0") not in worktrees


def test_a_running_gcm_keeps_its_version(rig: Rig) -> None:
    """Started before two updates, its version outlives them, and goes once it ends."""
    rig.release("v1.0.0")
    rig.install()
    gcm = RunningGcm(rig)

    rig.release("v1.1.0")
    first = rig.install()
    rig.release("v1.2.0")
    second = rig.install()

    assert "A GCM already running goes on with v1.0.0 until it is closed." in first.stdout
    assert "Kept v1.0.0, which a GCM still running was started from." in second.stdout
    assert rig.installed() == ["v1.0.0", "v1.1.0", "v1.2.0"]
    report = gcm.finish()
    assert report["file_exists"]
    assert report["file"].startswith(str(rig.versions / "v1.0.0"))

    rig.release("v1.3.0")
    third = rig.install()

    assert rig.installed() == ["v1.2.0", "v1.3.0"]
    assert "Removed v1.0.0." in third.stdout
    assert "Removed v1.1.0." in third.stdout


def test_runs_from_inside_a_version_it_removes(rig: Rig) -> None:
    """git refuses to start in a folder that is gone, and two versions go here."""
    rig.release("v1.0.0")
    rig.install()
    gcm = RunningGcm(rig)
    for tag in ("v1.1.0", "v1.2.0"):
        rig.release(tag)
        rig.install()
    gcm.finish()
    rig.release("v1.3.0")

    rig.install(cwd=rig.versions / "v1.0.0")

    assert rig.installed() == ["v1.2.0", "v1.3.0"]


def test_a_tag_moved_upstream_does_not_stop_an_update(rig: Rig) -> None:
    """A plain fetch refuses to move a tag it has, and exits 1; the installed one stays.

    A version installed under the moved tag is not the one the tag names any longer, and
    asking for it again says so rather than mixing the two.
    """
    rig.release("v1.0.0")
    rig.install()
    moved = rig.commit()
    git(rig.upstream, "tag", "-f", "v1.0.0", moved)
    rig.release("v1.1.0")

    rig.install()
    again = rig.install("v1.0.0", ok=False)

    assert rig.link("current") == "versions/v1.1.0"
    assert again.returncode == 1
    assert "is not v1.0.0 as" in again.stderr


def test_a_run_cut_short_is_picked_up(rig: Rig) -> None:
    """A clone or a worktree left half made under its working name is made again."""
    rig.release("v1.0.0")
    (rig.gcm_home / "repo.new").mkdir(parents=True)
    (rig.gcm_home / "repo.new" / "junk").write_text("x")
    rig.install()
    (rig.versions / ".new").mkdir()
    (rig.versions / ".new" / "junk").write_text("x")
    rig.release("v1.1.0")

    rig.install()

    assert rig.installed() == ["v1.0.0", "v1.1.0"]
    assert not (rig.gcm_home / "repo.new").exists()
    assert not (rig.versions / ".new").exists()


def test_one_run_at_a_time(rig: Rig) -> None:
    rig.release("v1.0.0")
    rig.gcm_home.mkdir(parents=True)
    with (rig.gcm_home / "install.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done = rig.install(ok=False)

    assert done.returncode == 1
    assert "another run of install.sh is installing GCM" in done.stderr
    assert not (rig.gcm_home / "current").exists()


def test_a_download_cut_short_runs_nothing(rig: Rig) -> None:
    """Cut at each line, and at each character of the last, where `main` alone would run."""
    rig.release("v1.0.0")
    text = SCRIPT.read_text(encoding="utf-8")
    last = text.rstrip("\n").rfind("\n") + 1
    cuts = {i + 1 for i, char in enumerate(text) if char == "\n"} | set(range(last, len(text) - 1))
    cuts.discard(len(text))

    for cut in sorted(cuts):
        subprocess.run(
            ["bash", "-s", "--", "--uninstall"],
            input=text[:cut],
            env=rig.env(),
            cwd=rig.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert not rig.home.joinpath(".local").exists(), f"cut at {cut} ran"
    assert not rig.log.exists()


# -- files it did not write, and uninstalling --------------------------------------------


def test_leaves_a_launcher_it_did_not_write(rig: Rig) -> None:
    rig.release("v1.0.0")
    rig.launcher.parent.mkdir(parents=True)
    rig.launcher.write_text("#!/bin/sh\necho mine\n")

    done = rig.install(ok=False)

    assert done.returncode == 1
    assert "was not written by this script" in done.stderr
    assert rig.launcher.read_text() == "#!/bin/sh\necho mine\n"
    assert not rig.gcm_home.exists()


def test_uninstall_removes_what_it_installed(rig: Rig) -> None:
    """And keeps the configuration, with the hosts and their key, and the packages."""
    rig.release("v1.0.0")
    rig.install()
    config = rig.home / ".config" / "gcm" / "gcm.conf"
    config.parent.mkdir(parents=True)
    config.write_text("[options]\n")

    done = rig.install("--uninstall")

    assert not rig.gcm_home.exists()
    assert not rig.launcher.exists()
    assert not rig.desktop_entry.exists()
    assert config.read_text() == "[options]\n"
    assert "Kept GCM's configuration" in done.stdout
    assert not rig.log.exists()


def test_uninstall_leaves_a_desktop_entry_it_did_not_write(rig: Rig) -> None:
    rig.release("v1.0.0")
    rig.install()
    rig.desktop_entry.write_text("[Desktop Entry]\nName=Mine\n")

    done = rig.install("--uninstall")

    assert f"Left {rig.desktop_entry}, which this script did not write." in done.stdout
    assert rig.desktop_entry.read_text() == "[Desktop Entry]\nName=Mine\n"
    assert not rig.gcm_home.exists()


def test_uninstall_waits_for_gcm_to_close(rig: Rig) -> None:
    rig.release("v1.0.0")
    rig.install()
    gcm = RunningGcm(rig)

    done = rig.install("--uninstall", ok=False)
    gcm.finish()

    assert done.returncode == 1
    assert "GCM is running, started from v1.0.0" in done.stderr
    assert rig.launcher.exists()
    assert (rig.versions / "v1.0.0").is_dir()


def test_uninstall_with_nothing_installed(rig: Rig) -> None:
    done = rig.install("--uninstall")

    assert "nothing to remove" in done.stdout
    assert not rig.home.joinpath(".local").exists()
