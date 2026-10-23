"""Tests for `tools/doit/skills.py` and the `doit skills_sync` task.

Shared workflow skills are written once, in `.agents/skills/<name>/SKILL.md`.
Claude Code does not read that directory, so `doit skills_sync` generates a
byte-identical copy at `.claude/skills/<name>/SKILL.md`. These tests cover the
pure sync/drift functions against a disposable `tmp_path` tree, the task
wrapper's `--check` and not-wired behavior, and a handful of repo-level
contract checks against the real `.agents/skills/` and `.claude/skills/`
trees this repo ships.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_roster import agent_is_present

from tools.doit import skills as skills_module
from tools.doit.skills import (
    SHARED_SKILLS,
    claude_is_wired,
    drifted_skills,
    sync_skills,
    task_skills_sync,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_source(root: Path, name: str, content: str) -> Path:
    path = root / ".agents" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _generated_path(root: Path, name: str) -> Path:
    return root / ".claude" / "skills" / name / "SKILL.md"


class TestSyncSkills:
    """`sync_skills` creates missing copies and overwrites stale ones, byte for byte."""

    def test_creates_a_missing_copy(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "---\nname: widget\n---\n\nbody\n")

        written = sync_skills(names=("widget",), root=tmp_path)

        assert written == ["widget"]
        assert _generated_path(tmp_path, "widget").read_text(encoding="utf-8") == (
            "---\nname: widget\n---\n\nbody\n"
        )

    def test_overwrites_a_stale_copy(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "fresh content\n")
        generated = _generated_path(tmp_path, "widget")
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("stale content\n", encoding="utf-8")

        written = sync_skills(names=("widget",), root=tmp_path)

        assert written == ["widget"]
        assert generated.read_text(encoding="utf-8") == "fresh content\n"

    def test_leaves_a_matching_copy_untouched(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "same content\n")
        generated = _generated_path(tmp_path, "widget")
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("same content\n", encoding="utf-8")

        written = sync_skills(names=("widget",), root=tmp_path)

        assert written == []

    def test_syncs_only_the_requested_names(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "widget body\n")
        _write_source(tmp_path, "gadget", "gadget body\n")

        written = sync_skills(names=("widget",), root=tmp_path)

        assert written == ["widget"]
        assert not _generated_path(tmp_path, "gadget").exists()


class TestDriftedSkills:
    """`drifted_skills` reports a missing or stale copy, and nothing else."""

    def test_reports_a_missing_copy(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "content\n")

        assert drifted_skills(names=("widget",), root=tmp_path) == ["widget"]

    def test_reports_a_stale_copy(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "fresh\n")
        generated = _generated_path(tmp_path, "widget")
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text("stale\n", encoding="utf-8")

        assert drifted_skills(names=("widget",), root=tmp_path) == ["widget"]

    def test_reports_nothing_when_every_copy_matches(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "content\n")
        sync_skills(names=("widget",), root=tmp_path)

        assert drifted_skills(names=("widget",), root=tmp_path) == []

    def test_scopes_to_the_requested_names(self, tmp_path: Path) -> None:
        _write_source(tmp_path, "widget", "content\n")
        sync_skills(names=("widget",), root=tmp_path)
        _write_source(tmp_path, "gadget", "content\n")  # never synced -> missing

        assert drifted_skills(names=("widget",), root=tmp_path) == []
        assert drifted_skills(names=("gadget",), root=tmp_path) == ["gadget"]


class TestClaudeIsWired:
    """`claude_is_wired` mirrors `agent_roster`'s Claude presence marker."""

    def test_true_when_the_marker_directory_exists(self, tmp_path: Path) -> None:
        marker = tmp_path / ".claude" / "commands" / "claude"
        marker.mkdir(parents=True)

        assert claude_is_wired(root=tmp_path) is True

    def test_false_when_the_marker_directory_is_absent(self, tmp_path: Path) -> None:
        assert claude_is_wired(root=tmp_path) is False

    def test_false_when_the_marker_path_is_a_file_not_a_directory(self, tmp_path: Path) -> None:
        marker = tmp_path / ".claude" / "commands" / "claude"
        marker.parent.mkdir(parents=True)
        marker.write_text("not a directory", encoding="utf-8")

        assert claude_is_wired(root=tmp_path) is False


class TestSkillsSyncTask:
    """`task_skills_sync`'s action: not-wired no-op, `--check` drift report, and sync."""

    def test_does_nothing_when_claude_is_not_wired(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(skills_module, "claude_is_wired", lambda: False)
        monkeypatch.setattr(
            skills_module,
            "drifted_skills",
            lambda: pytest.fail("drifted_skills must not run when Claude is not wired"),
        )
        monkeypatch.setattr(
            skills_module,
            "sync_skills",
            lambda: pytest.fail("sync_skills must not run when Claude is not wired"),
        )
        run = task_skills_sync()["actions"][0]

        run(check=False)

        assert "not wired" in capsys.readouterr().out

    def test_check_exits_nonzero_and_names_the_drifted_skill(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(skills_module, "claude_is_wired", lambda: True)
        monkeypatch.setattr(skills_module, "drifted_skills", lambda: ["widget"])
        run = task_skills_sync()["actions"][0]

        with pytest.raises(SystemExit) as excinfo:
            run(check=True)

        assert excinfo.value.code != 0
        assert "widget" in capsys.readouterr().out

    def test_check_exits_zero_when_nothing_is_drifted(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(skills_module, "claude_is_wired", lambda: True)
        monkeypatch.setattr(skills_module, "drifted_skills", lambda: [])
        run = task_skills_sync()["actions"][0]

        run(check=True)  # must not raise

        assert "matches" in capsys.readouterr().out

    def test_sync_reports_what_it_wrote(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(skills_module, "claude_is_wired", lambda: True)
        monkeypatch.setattr(skills_module, "sync_skills", lambda: ["widget", "gadget"])
        run = task_skills_sync()["actions"][0]

        run(check=False)

        out = capsys.readouterr().out
        assert "widget" in out
        assert "gadget" in out


# --- Repo-level contracts, scoped to this repo's own wired agents (#690) ---


@pytest.mark.skipif(not agent_is_present("claude"), reason="Claude is not wired in this project")
class TestRepoSkillsStayInSync:
    """Each shared skill's `.claude/skills/` copy must match its `.agents/skills/` source."""

    def test_every_generated_copy_is_byte_identical_to_its_source(self) -> None:
        assert drifted_skills(names=SHARED_SKILLS, root=REPO_ROOT) == []

    def test_no_shared_skill_leaves_a_stale_claude_commands_file(self) -> None:
        stale = [
            name
            for name in SHARED_SKILLS
            if (REPO_ROOT / ".claude" / "commands" / f"{name}.md").is_file()
        ]
        assert stale == [], (
            f"{stale} still have a `.claude/commands/<name>.md` file, which would shadow "
            "the generated skill"
        )

    def test_every_shared_source_declares_its_own_name_in_frontmatter(self) -> None:
        missing = []
        for name in SHARED_SKILLS:
            source = REPO_ROOT / ".agents" / "skills" / name / "SKILL.md"
            if not source.is_file():
                missing.append(f"{name}: source file missing")
                continue
            text = source.read_text(encoding="utf-8")
            if f"name: {name}" not in text:
                missing.append(f"{name}: frontmatter does not declare `name: {name}`")

        assert missing == [], "\n".join(missing)
