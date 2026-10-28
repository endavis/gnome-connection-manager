"""Unit tests for ``tests/doc_scan.py``."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from doc_scan import committed_markdown_files, is_excluded, load_sync_excludes


def _write_exclude_file(project_root: Path, patterns: list[str]) -> None:
    settings_dir = project_root / ".config" / "pyproject_template"
    settings_dir.mkdir(parents=True, exist_ok=True)
    body = "exclude = [\n" + "".join(f'    "{p}",\n' for p in patterns) + "]\n"
    (settings_dir / "sync-exclude.toml").write_text(body, encoding="utf-8")


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(  # nosec B603 B607 - fixed argv, no shell, test fixture only
        ["git", *args], cwd=cwd, check=True, capture_output=True
    )


def _init_repo(root: Path) -> None:
    _git(["init", "--quiet"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)


class TestLoadSyncExcludes:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_sync_excludes(tmp_path) == []

    def test_valid_file_returns_patterns(self, tmp_path: Path) -> None:
        _write_exclude_file(tmp_path, ["docs/template/**", "tests/test_core.py"])
        assert load_sync_excludes(tmp_path) == ["docs/template/**", "tests/test_core.py"]

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".config" / "pyproject_template"
        settings_dir.mkdir(parents=True)
        (settings_dir / "sync-exclude.toml").write_text("not = valid toml [[\n", encoding="utf-8")
        assert load_sync_excludes(tmp_path) == []

    def test_non_list_exclude_returns_empty(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".config" / "pyproject_template"
        settings_dir.mkdir(parents=True)
        (settings_dir / "sync-exclude.toml").write_text('exclude = "oops"\n', encoding="utf-8")
        assert load_sync_excludes(tmp_path) == []

    def test_non_string_entries_dropped(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".config" / "pyproject_template"
        settings_dir.mkdir(parents=True)
        (settings_dir / "sync-exclude.toml").write_text(
            'exclude = ["keep.md", 42, "also.md"]\n', encoding="utf-8"
        )
        assert load_sync_excludes(tmp_path) == ["keep.md", "also.md"]


class TestIsExcluded:
    def test_exact_match(self) -> None:
        assert is_excluded("docs/template/manage.md", ["docs/template/manage.md"])

    def test_wildcard_match(self) -> None:
        assert is_excluded("docs/template/manage.md", ["docs/template/**"])

    def test_no_match(self) -> None:
        assert not is_excluded("docs/template/manage.md", ["src/package_name/**"])

    def test_no_patterns(self) -> None:
        assert not is_excluded("docs/template/manage.md", [])


class TestCommittedMarkdownFiles:
    def test_tracked_file_is_included(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "tracked.md").write_text("# Tracked\n", encoding="utf-8")
        _git(["add", "tracked.md"], tmp_path)
        _git(["commit", "--quiet", "-m", "add tracked"], tmp_path)

        assert committed_markdown_files(tmp_path) == [tmp_path / "tracked.md"]

    def test_untracked_not_ignored_file_is_included(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "untracked.md").write_text("# Untracked\n", encoding="utf-8")

        assert committed_markdown_files(tmp_path) == [tmp_path / "untracked.md"]

    def test_ignored_file_is_excluded(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (tmp_path / "ignored").mkdir()
        (tmp_path / "ignored" / "notes.md").write_text("# Ignored\n", encoding="utf-8")
        (tmp_path / "kept.md").write_text("# Kept\n", encoding="utf-8")

        assert committed_markdown_files(tmp_path) == [tmp_path / "kept.md"]

    def test_outside_a_git_repo_raises(self, tmp_path: Path) -> None:
        with pytest.raises(subprocess.CalledProcessError):
            committed_markdown_files(tmp_path)
