"""Contract tests for `.github/actionlint.yaml`.

actionlint v1.7.12 (pinned in `.pre-commit-config.yaml`) does not know the
`ubuntu-26.04` GitHub-hosted runner label and rejects it as unknown. This repo
declares the label via `self-hosted-runner.labels` -- the escape hatch
actionlint's own error message names -- rather than disabling the check.

These tests guard the file's contract: the label is present, and the comment
that explains why the file exists and when to delete it survives future edits
(#929).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIONLINT_CONFIG = REPO_ROOT / ".github" / "actionlint.yaml"


def test_actionlint_config_exists_and_parses() -> None:
    """The config file exists and is valid YAML."""
    assert ACTIONLINT_CONFIG.is_file()
    data = yaml.safe_load(ACTIONLINT_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_ubuntu_26_04_label_declared() -> None:
    """ubuntu-26.04 is declared as a self-hosted-runner label."""
    data = yaml.safe_load(ACTIONLINT_CONFIG.read_text(encoding="utf-8"))
    labels = data["self-hosted-runner"]["labels"]
    assert "ubuntu-26.04" in labels


def test_config_references_upstream_issue_and_delete_guidance() -> None:
    """The file cites the upstream issue and says when to delete it.

    Keeps the removal trigger from being lost in a later edit.
    """
    text = ACTIONLINT_CONFIG.read_text(encoding="utf-8")
    assert "rhysd/actionlint/issues/682" in text
    assert "Delete this file" in text
