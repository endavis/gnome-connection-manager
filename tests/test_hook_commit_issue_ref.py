"""Tests for the branch/commit issue-reference hook (#741).

Derived from a real failure: during the template review backlog, work for #695
was committed onto `feat/694-download-integrity-verification` — the branch left
over from the previous issue. `no-commit-to-main` passed (not `main`), the
branch-naming hook passed (well-formed), and every quality gate passed (the code
was fine). Only its location was wrong.

The replay of that exact case is `test_the_incident_that_motivated_this_hook`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.hooks.check_commit_issue_ref import (
    OVERRIDE_ENV,
    branch_issue,
    check,
    main,
    message_issues,
    should_skip,
    strip_comments,
)


class TestBranchIssue:
    @pytest.mark.parametrize(
        ("branch", "expected"),
        [
            ("feat/694-download-integrity-verification", 694),
            ("chore/695-workflow-hardening", 695),
            ("fix/1-x", 1),
            ("refactor/12345-long-number", 12345),
            ("main", None),
            ("develop", None),
            ("release/1.2.3", None),
            ("hotfix/urgent-thing", None),
            ("", None),
        ],
    )
    def test_extraction(self, branch: str, expected: int | None) -> None:
        assert branch_issue(branch) == expected


class TestMessageIssues:
    def test_finds_every_reference(self) -> None:
        assert message_issues("fix: thing (#12)\n\nAlso relates to #34 and #56.") == {12, 34, 56}

    def test_ignores_git_comment_lines(self) -> None:
        """The commit template and verbose diff must not count as references.

        Without this, `# On branch feat/694-...` or a diff quoting `#695` would
        be read as the author citing an issue.
        """
        message = "chore: something\n\n# Please enter the commit message for #999\n"
        assert message_issues(message) == set()

    def test_ignores_everything_below_the_scissors_line(self) -> None:
        message = (
            "fix: real subject (#12)\n"
            "\n"
            "# ------------------------ >8 ------------------------\n"
            "diff --git a/x b/x\n"
            "+# fixes #888\n"
        )
        assert message_issues(message) == {12}

    @pytest.mark.parametrize(
        "text",
        [
            "colour #1234ab is fine",  # hex colour, not an issue
            "channel abc#12 is a mention, not a reference",
            "no references at all",
        ],
    )
    def test_does_not_match_non_references(self, text: str) -> None:
        assert message_issues(text) == set()


class TestSkipping:
    @pytest.mark.parametrize(
        "subject",
        [
            "Merge branch 'main' into feat/1-x",
            'Revert "feat: a thing (#12)"',
            "fixup! feat: a thing (#12)",
            "squash! feat: a thing (#12)",
        ],
    )
    def test_generated_and_targeted_messages_are_skipped(self, subject: str) -> None:
        """These reference another commit's issue, not the work being committed."""
        assert should_skip(subject) is True
        assert check("feat/999-unrelated", subject) is None

    def test_empty_message_is_skipped(self) -> None:
        assert should_skip("# just a comment\n") is True


class TestCheck:
    def test_matching_issue_passes(self) -> None:
        assert check("chore/695-workflow-hardening", "chore: thing\n\nAddresses #695") is None

    def test_branch_issue_among_several_passes(self) -> None:
        """Citing related issues alongside the branch's own is normal."""
        message = "fix: thing\n\nAddresses #731. Same lesson as #736."
        assert check("fix/731-x", message) is None

    def test_message_with_no_references_passes(self) -> None:
        """Requiring a reference would be a different, more intrusive policy."""
        assert check("feat/694-x", "chore: tidy up whitespace") is None

    def test_branch_without_an_issue_passes(self) -> None:
        for branch in ("main", "release/1.0.0", "hotfix/thing"):
            assert check(branch, "fix: thing (#12)") is None

    def test_mismatch_is_reported(self) -> None:
        error = check("feat/694-download-integrity", "chore: pin actions\n\nAddresses #695")
        assert error is not None
        assert "#695" in error
        assert "694" in error

    def test_the_incident_that_motivated_this_hook(self) -> None:
        """Replay of the real commit that prompted #741.

        The #695 work, committed onto the #694 branch. Everything else passed;
        this must not.
        """
        branch = "feat/694-download-integrity-verification"
        message = (
            "chore: pin actions to commit SHAs and scope benchmark write permissions\n"
            "\n"
            "benchmark.yml declared `contents: write` at workflow scope (#695).\n"
            "fail-on-alert was rejected as a flake source, per #736.\n"
        )

        error = check(branch, message)

        assert error is not None, "the hook must reject the commit that motivated it"
        assert "#695" in error and "#736" in error
        assert "694" in error

    @pytest.mark.parametrize(
        ("branch", "message"),
        [
            ("fix/731-configure-sheds-coverage-tests", "fix: keep tests (#731)"),
            ("refactor/691-template-owned", "refactor: rule explicit (#691)"),
            ("refactor/690-tests-adapt", "refactor: size tests (#690)"),
            ("fix/736-hypothesis-ci-deadline", "fix: drop deadline (#736)"),
            ("refactor/710-hermetic-gh", "refactor: hermetic suite (#710)"),
        ],
    )
    def test_real_commits_from_that_session_still_pass(self, branch: str, message: str) -> None:
        """The rule must not be so strict it would have blocked correct work.

        A guard that fires on legitimate commits gets switched off, which leaves
        the repository worse than no guard.
        """
        assert check(branch, message) is None


class TestMain:
    def test_returns_zero_on_a_matching_commit(self, tmp_path: Path) -> None:
        msg = tmp_path / "COMMIT_EDITMSG"
        msg.write_text("chore: thing\n", encoding="utf-8")
        assert main([str(msg)]) == 0

    def test_usage_error_without_arguments(self) -> None:
        assert main([]) == 2

    def test_override_env_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The documented escape hatch, since AGENTS.md forbids --no-verify."""
        msg = tmp_path / "COMMIT_EDITMSG"
        msg.write_text("chore: thing (#999)\n", encoding="utf-8")
        monkeypatch.setenv(OVERRIDE_ENV, "1")
        monkeypatch.setattr("tools.hooks.check_commit_issue_ref.current_branch", lambda: "feat/1-x")
        assert main([str(msg)]) == 0

    def test_rejects_a_mismatch_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        msg = tmp_path / "COMMIT_EDITMSG"
        msg.write_text("chore: pin actions (#695)\n", encoding="utf-8")
        monkeypatch.setattr(
            "tools.hooks.check_commit_issue_ref.current_branch",
            lambda: "feat/694-download-integrity-verification",
        )

        assert main([str(msg)]) == 1
        assert "#695" in capsys.readouterr().err


class TestStripComments:
    def test_keeps_body_text(self) -> None:
        assert strip_comments("subject\n\nbody\n# comment\n") == "subject\n\nbody"
