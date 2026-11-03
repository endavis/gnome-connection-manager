"""WSLg's log shows it cannot draw windows, and GCM says so (#414)."""

from pathlib import Path

from gnome_connection_manager.utils import wslg

FAILED = (
    "[08:51:50.188] rdp_allocate_shared_memory: Failed to open "
    '"/mnt/shared_memory/{ced5c01b}" with error: Input/output error\n'
    "[08:51:50.188] RDP backend: enable_copy_warning_title = 1\n"
)
HEALTHY = "Date: 2026-10-30\n[08:51:49.000] RDP backend: started\n"


def test_failure_gives_notice():
    notice = wslg.copy_mode_notice(HEALTHY + FAILED)
    assert notice is not None
    assert "wsl --shutdown" in notice
    assert "WSL-SETUP.md" in notice


def test_healthy_log_gives_nothing():
    assert wslg.copy_mode_notice(HEALTHY) is None
    assert wslg.copy_mode_notice("") is None


def test_healthy_log_with_the_copy_warning_setting_gives_nothing():
    # Measured on a working session: it logs this line too, so it is no sign of the failure.
    healthy = HEALTHY + "[10:23:51.878] RDP backend: enable_copy_warning_title = 1\n"
    assert wslg.copy_mode_notice(healthy) is None


def test_startup_notice_reads_the_file(tmp_path: Path):
    log = tmp_path / "weston.log"
    log.write_text(FAILED)
    assert wslg.startup_notice(log) == wslg.NOTICE


def test_no_log_or_unreadable_log_gives_nothing(tmp_path: Path):
    assert wslg.startup_notice(tmp_path / "missing.log") is None
    assert wslg.startup_notice(tmp_path) is None  # a directory


def test_failure_past_the_read_limit_is_not_seen(tmp_path: Path):
    log = tmp_path / "weston.log"
    log.write_text("x" * wslg.READ_LIMIT + FAILED)
    assert wslg.startup_notice(log) is None


def test_invalid_bytes_do_not_raise(tmp_path: Path):
    log = tmp_path / "weston.log"
    log.write_bytes(b"\xff\xfe" + FAILED.encode())
    assert wslg.startup_notice(log) == wslg.NOTICE


def test_main_prints_notice(app_module, monkeypatch, capsys):
    monkeypatch.setattr(app_module, "require_expect", lambda: None)
    monkeypatch.setattr(app_module, "require_config_dir", lambda: None)
    monkeypatch.setattr(app_module, "require_readable_config", lambda: None)
    monkeypatch.setattr(app_module.wslg, "startup_notice", lambda: wslg.NOTICE)

    class App:
        def run(self, argv):
            return 0

    monkeypatch.setattr(app_module, "GcmApplication", App)
    assert app_module.main(["gcm"]) == 0
    assert wslg.NOTICE in capsys.readouterr().err
