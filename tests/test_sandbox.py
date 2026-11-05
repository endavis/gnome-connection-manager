"""`doit sandbox` (#506): a throwaway configuration to run the checkout's GCM against.

The configuration is read back through GCM's own readers, the environment is held to never
reach the real ~/.config/gcm, and GCM is started once against a prepared sandbox on real GTK.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gnome_connection_manager.utils import configfile, configpaths, crypto
from gnome_connection_manager.utils.folders import FolderTree
from gnome_connection_manager.utils.hosts import HostUtils
from tests.test_connections import glib_complaints
from tools import sandbox
from tools.doit import gcm

REPO = Path(__file__).resolve().parents[1]


def hosts_of(path: Path) -> tuple[list, FolderTree, list[str]]:
    """The hosts and folders of `path`, read as GCM reads them."""
    cp = configfile.load(path).config
    hosts = [
        HostUtils.load_host_from_ini(cp, section, "", legacy=False)
        for section in cp.sections()
        if section.startswith(configfile.HOST_PREFIX)
    ]
    tree, fixes = FolderTree.load(cp)
    tree.bind(hosts)
    return hosts, tree, fixes


def test_the_generated_config_loads_through_gcms_own_reader(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 30, 3)

    hosts, tree, fixes = hosts_of(path)

    assert fixes == []
    assert len(hosts) == 33
    by_group: dict[str, list] = {}
    for host in hosts:
        by_group.setdefault(host.group, []).append(host)
        assert host.password == ""
        assert host.host == f"{host.name}.invalid"
        assert tree.path_for(host.folder) == host.group
    assert {group: len(found) for group, found in by_group.items()} == {
        "Many hosts": 30,
        "Few hosts": 3,
    }
    assert len({host.name for host in hosts}) == 33
    assert len({host.id for host in hosts}) == 33


@pytest.mark.parametrize(
    ("many", "few", "groups"),
    [(0, 1, {"Few hosts"}), (5, 0, {"Many hosts"}), (2, 7, {"Many hosts", "Few hosts"})],
)
def test_a_count_of_zero_writes_no_folder(
    tmp_path: Path, many: int, few: int, groups: set[str]
) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, many, few)

    hosts, tree, _ = hosts_of(path)

    assert len(hosts) == many + few
    assert {folder.name for folder in tree.folders.values()} == groups


def test_a_negative_count_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="negative"):
        sandbox.write_config(tmp_path / "gcm.conf", -1, 3)
    with pytest.raises(ValueError, match="negative"):
        sandbox.write_config(tmp_path / "gcm.conf", 3, -1)


def test_the_update_check_is_off(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 1, 1)

    cp = configfile.load(path).config
    assert cp.getboolean("options", "check-updates") is False


def test_the_password_is_stored_empty_whatever_the_writer_encrypts(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 1, 0)

    assert "pass = \n" in path.read_text()
    assert crypto.encrypt("", "") != ""


def test_the_environment_never_reaches_the_real_home(tmp_path: Path) -> None:
    home = sandbox.sandbox_home(tmp_path)
    base = {
        "HOME": "/home/someone",
        "XDG_CONFIG_HOME": "/home/someone/.config",
        "GCM_DATA_DIR": "/elsewhere/data",
        "GCM_GLADE_DIR": "/elsewhere/glade",
        "GCM_SCRIPTS_DIR": "/elsewhere/scripts",
        "GDK_SCALE": "2",
        "PATH": "/usr/bin",
    }

    env = sandbox.environment(base, home, None)

    assert env["HOME"] == str(home)
    assert home == tmp_path / "tmp" / "sandbox_cache"
    assert not set(sandbox.UNSET) & set(env)
    assert env["PATH"] == "/usr/bin"
    assert configpaths.resolve(Path(env["HOME"]), env).path == home / ".config" / "gcm"
    assert base["HOME"] == "/home/someone", "the caller's own mapping is left alone"


def test_the_scale_passes_through_as_typed_and_none_leaves_the_callers(tmp_path: Path) -> None:
    base = {
        "DISPLAY": ":7",
        "WAYLAND_DISPLAY": "wayland-0",
        "GDK_BACKEND": "wayland",
        "GDK_DPI_SCALE": "3",
    }

    scaled = sandbox.environment(base, tmp_path, "2.25")
    kept = sandbox.environment(base, tmp_path, None)

    assert scaled["GDK_DPI_SCALE"] == "2.25"
    assert kept["GDK_DPI_SCALE"] == "3"
    for env in (scaled, kept):
        assert (env["DISPLAY"], env["WAYLAND_DISPLAY"], env["GDK_BACKEND"]) == (
            ":7",
            "wayland-0",
            "wayland",
        )


@pytest.mark.parametrize("scale", ["0", "-1", "x", "nan", "inf"])
def test_a_scale_that_is_not_a_positive_number_raises(tmp_path: Path, scale: str) -> None:
    with pytest.raises(ValueError, match="--scale"):
        sandbox.environment({}, tmp_path, scale)


def test_prepare_writes_once_and_keeps_what_it_finds(tmp_path: Path) -> None:
    home = tmp_path / "tmp" / "sandbox_cache"

    assert sandbox.prepare(home, fresh=False, many=2, few=1) is True
    marker = home / "marker"
    marker.write_text("mine")
    assert sandbox.prepare(home, fresh=False, many=9, few=9) is False

    assert marker.read_text() == "mine"
    assert len(hosts_of(sandbox.config_file(home))[0]) == 3


def test_fresh_rebuilds(tmp_path: Path) -> None:
    home = tmp_path / "tmp" / "sandbox_cache"
    sandbox.prepare(home, fresh=False, many=2, few=1)
    marker = home / "marker"
    marker.write_text("mine")

    assert sandbox.prepare(home, fresh=True, many=4, few=0) is True

    assert not marker.exists()
    assert len(hosts_of(sandbox.config_file(home))[0]) == 4


@pytest.mark.parametrize("parts", [("elsewhere",), ("tmp", "other"), ("sandbox_cache",)])
def test_fresh_on_a_foreign_path_raises_and_removes_nothing(
    tmp_path: Path, parts: tuple[str, ...]
) -> None:
    home = tmp_path.joinpath(*parts)
    home.mkdir(parents=True)
    keep = home / "keep"
    keep.write_text("x")

    with pytest.raises(ValueError, match="refusing"):
        sandbox.prepare(home, fresh=True, many=1, few=1)

    assert keep.read_text() == "x"


def test_fresh_will_not_follow_a_link(tmp_path: Path) -> None:
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep").write_text("x")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "sandbox_cache").symlink_to(target)

    with pytest.raises(ValueError, match="refusing"):
        sandbox.prepare(tmp_path / "tmp" / "sandbox_cache", fresh=True, many=1, few=1)

    assert (target / "keep").exists()


def test_the_command_is_the_checkouts_own_python(tmp_path: Path) -> None:
    assert sandbox.command(tmp_path) == [
        str(tmp_path / ".venv" / "bin" / "python"),
        "-m",
        "gnome_connection_manager",
    ]


def test_the_task_takes_its_options() -> None:
    task = gcm.task_sandbox()

    params = {param["name"]: param for param in task["params"]}
    assert set(params) == {
        "fresh",
        "many",
        "few",
        "scale",
        "local",
        "wait",
        "trace",
        "wayland_debug",
    }
    assert (params["many"]["default"], params["few"]["default"]) == (30, 3)
    assert params["fresh"]["default"] is False
    assert not params["scale"]["default"]
    assert (params["local"]["default"], params["wait"]["default"]) == (0, False)
    assert (params["trace"]["default"], params["wayland_debug"]["default"]) == ("", False)
    assert task["actions"] == [gcm._run_sandbox]


def test_trace_and_wayland_debug_reach_gcm_and_otherwise_pass_through(tmp_path: Path) -> None:
    traced = sandbox.environment({}, tmp_path, None, trace="drag,menu", wayland_debug=True)
    assert (traced["GCM_TRACE"], traced["WAYLAND_DEBUG"]) == ("drag,menu", "client")

    plain = sandbox.environment({}, tmp_path, None)
    assert "GCM_TRACE" not in plain
    assert "WAYLAND_DEBUG" not in plain
    theirs = sandbox.environment({"GCM_TRACE": "menu", "WAYLAND_DEBUG": "1"}, tmp_path, None)
    assert (theirs["GCM_TRACE"], theirs["WAYLAND_DEBUG"]) == ("menu", "1")


def test_the_task_gives_gcm_the_trace_one_stream_with_the_protocol(checkout: Path) -> None:
    head = MagicMock(stdout="abc\n")
    with (
        patch.object(gcm.subprocess, "run", return_value=head),
        patch.object(gcm.subprocess, "Popen", return_value=MagicMock(pid=7)) as popen,
    ):
        assert gcm._run_sandbox(False, 1, 1, "", 0, False, "drag", True) is True

    kwargs = popen.call_args.kwargs
    assert kwargs["env"]["GCM_TRACE"] == "drag"
    assert kwargs["env"]["WAYLAND_DEBUG"] == "client"
    assert kwargs["stderr"] == gcm.subprocess.STDOUT


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout with a venv's python, and gcm.REPO pointing at it."""
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(gcm, "REPO", tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/real/config")
    return tmp_path


def test_the_task_runs_gcm_in_the_sandbox(checkout: Path) -> None:
    with patch.object(gcm.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
        assert gcm._run_sandbox(False, 2, 1, "1.5", 0, True) is True

    args, kwargs = run.call_args
    assert args[0] == sandbox.command(checkout)
    assert kwargs["cwd"] == checkout
    assert kwargs["env"]["HOME"] == str(checkout / "tmp" / "sandbox_cache")
    assert kwargs["env"]["GDK_DPI_SCALE"] == "1.5"
    assert "XDG_CONFIG_HOME" not in kwargs["env"]
    assert sandbox.config_file(checkout / "tmp" / "sandbox_cache").is_file()


def test_the_task_fails_when_gcm_does(checkout: Path) -> None:
    with patch.object(gcm.subprocess, "run", return_value=MagicMock(returncode=3)):
        assert gcm._run_sandbox(False, 1, 1, "", 0, True) is False


def test_the_task_says_when_there_is_no_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gcm, "REPO", tmp_path)
    with patch.object(gcm.subprocess, "run") as run:
        assert gcm._run_sandbox(False, 1, 1, "") is False

    run.assert_not_called()
    assert "doit setup" in capsys.readouterr().out
    assert not (tmp_path / "tmp").exists()


def test_the_task_fails_on_a_bad_scale(checkout: Path) -> None:
    with patch.object(gcm.subprocess, "run") as run:
        assert gcm._run_sandbox(False, 1, 1, "zero") is False

    run.assert_not_called()


def test_the_task_says_when_it_kept_the_sandbox(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch.object(gcm.subprocess, "Popen", return_value=MagicMock(pid=1)),
        patch.object(gcm.subprocess, "run"),
    ):
        gcm._run_sandbox(False, 1, 1, "")
        capsys.readouterr()
        gcm._run_sandbox(False, 1, 1, "")

    assert "--fresh rebuilds it" in capsys.readouterr().out


def test_the_task_detaches_gcm_and_logs_its_output(
    checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch.object(gcm.subprocess, "Popen", return_value=MagicMock(pid=4242)) as popen,
        patch.object(gcm.subprocess, "run") as run,
    ):
        assert gcm._run_sandbox(False, 1, 1, "", 2) is True

    run_calls = [call for call in run.call_args_list if call.args[0][0] != "git"]
    assert run_calls == []
    args, kwargs = popen.call_args
    assert args[0] == sandbox.command(checkout)
    assert kwargs["start_new_session"] is True
    assert kwargs["env"]["HOME"] == str(checkout / "tmp" / "sandbox_cache")
    assert kwargs["stderr"] == subprocess.STDOUT
    stream = kwargs["stdout"]
    assert stream.closed
    log = Path(stream.name)
    assert log.parent == checkout / "tmp" / "sandbox_cache" / "logs"
    assert log.is_file()
    out = capsys.readouterr().out
    assert "4242" in out
    assert str(log) in out


def test_wait_keeps_gcm_in_the_foreground(checkout: Path) -> None:
    with (
        patch.object(gcm.subprocess, "Popen") as popen,
        patch.object(gcm.subprocess, "run", return_value=MagicMock(returncode=0)),
    ):
        assert gcm._run_sandbox(False, 1, 1, "", 0, True) is True

    popen.assert_not_called()


def test_every_remote_host_has_an_address_that_cannot_resolve(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 4, 2)

    for host in hosts_of(path)[0]:
        assert host.host.endswith(".invalid")
        assert host.host != "127.0.0.1"


def test_the_ssh_agent_is_removed_and_a_crash_prints_its_stack(tmp_path: Path) -> None:
    base = {"SSH_AUTH_SOCK": "/run/agent", "SSH_AGENT_PID": "7", "PATH": "/bin"}

    env = sandbox.environment(base, tmp_path, None)

    assert "SSH_AUTH_SOCK" not in env
    assert "SSH_AGENT_PID" not in env
    assert env["PYTHONFAULTHANDLER"] == "1"
    assert env["PATH"] == "/bin"


def test_local_hosts_open_a_local_shell_and_are_not_the_local_console(tmp_path: Path) -> None:
    from gnome_connection_manager.app import is_local_console
    from gnome_connection_manager.utils import connections

    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 0, 0, 3)

    hosts = hosts_of(path)[0]

    assert [host.name for host in hosts] == ["alpha", "bravo", "charlie"]
    for host in hosts:
        assert host.host == ""
        assert host.group == "Local hosts"
        assert connections.for_host(host) is connections.LOCAL
        assert not is_local_console(host, hosts)


def test_no_local_hosts_write_no_folder(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 1, 1, 0)

    assert "Local hosts" not in {host.group for host in hosts_of(path)[0]}


def test_more_local_hosts_than_the_alphabet_holds_stay_unique(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 0, 0, 60)

    names = [host.name for host in hosts_of(path)[0]]

    assert len(set(names)) == 60
    assert "alpha-2" in names


def test_the_sandbox_titles_its_window(tmp_path: Path) -> None:
    path = tmp_path / "gcm.conf"
    sandbox.write_config(path, 1, 0)

    options = configfile.load(path).config["options"]

    assert options["app-title"] == "GCM sandbox"
    assert options["update-title"] == "True"


MOUNTINFO = (
    "30 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
    "31 30 0:30 / {parent} rw - tmpfs tmpfs rw\n"
    "32 30 0:31 / {home}/mnt/web rw - fuse.sshfs me@web: rw\n"
    "33 30 0:32 / {home} rw - tmpfs tmpfs rw\n"
    "34 30 0:33 / {home}2/mnt rw - fuse.sshfs me@web: rw\n"
)


def mountinfo_for(home: Path) -> str:
    return MOUNTINFO.format(parent=home.parent, home=home).replace("\\n", "\n")


def test_mounts_below_finds_the_home_and_below_but_not_a_sibling_or_parent(
    tmp_path: Path,
) -> None:
    home = tmp_path / "tmp" / "sandbox_cache"

    found = sandbox.mounts_below(home, mountinfo_for(home))

    assert found == [home / "mnt" / "web", home]


def test_fresh_with_a_mount_below_raises_and_removes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "tmp" / "sandbox_cache"
    sandbox.prepare(home, fresh=False, many=1, few=0)
    marker = home / "keep"
    marker.write_text("x")

    with pytest.raises(ValueError, match="fusermount -u"):
        sandbox.prepare(home, fresh=True, many=1, few=0, mountinfo=mountinfo_for(home))

    assert marker.is_file()


def test_fresh_with_no_mount_below_goes_ahead(tmp_path: Path) -> None:
    home = tmp_path / "tmp" / "sandbox_cache"
    sandbox.prepare(home, fresh=False, many=1, few=0)
    (home / "keep").write_text("x")

    sandbox.prepare(
        home, fresh=True, many=1, few=0, mountinfo="30 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
    )

    assert not (home / "keep").exists()


def test_gcm_stays_up_against_a_prepared_sandbox(tmp_path: Path) -> None:
    pytest.importorskip("gi", reason="PyGObject not available")
    home = tmp_path / "tmp" / "sandbox_cache"
    sandbox.prepare(home, fresh=False, many=30, few=3)
    env = sandbox.environment(dict(os.environ, GDK_BACKEND="x11"), home, None)
    env.pop("WAYLAND_DISPLAY", None)
    before = {path.name for path in (home / ".config" / "gcm").iterdir()}

    process = subprocess.Popen(
        [sys.executable, "-m", "gnome_connection_manager"],
        env=env,
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(8)
    still_running = process.poll() is None
    process.terminate()
    try:
        _, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate()

    assert still_running, stderr[-3000:]
    assert "Traceback" not in stderr, stderr[-3000:]
    assert glib_complaints(stderr) == []
    # Whatever startup writes lands in the sandbox, and the real configuration is not it.
    after = {path.name for path in (home / ".config" / "gcm").iterdir()}
    assert before <= after
    assert {path.name for path in home.iterdir()} <= {".config", ".cache", ".local"}
