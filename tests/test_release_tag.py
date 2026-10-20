"""`doit release_tag` tells a developer what follows a release, and nothing that does not (#306).

The task is the template's, vendored in `tools/doit/release.py`. It ended every release with
three steps: watch GitHub Actions build and publish, then check TestPyPI and PyPI. GCM has no
release workflow, so no build runs, and it publishes nowhere: both sites answer 404 for its
name. The steps now print only where the workflow they describe exists. A sync from the
template must keep that, and these fail if one brings the old ending back.

The task's action runs here as `doit release_tag` runs it, in a project folder of its own,
with `git` and `gh` faked.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tools.doit.release import task_release_tag

# Answers what the task asks of git, and refuses anything else.
FAKE_GIT = """\
#!/bin/sh
case "$*" in
    "branch --show-current") echo main ;;
    "pull" | "tag -l v9.9.9" | "tag v9.9.9" | "push origin v9.9.9") ;;
    *) echo "unexpected: git $*" >&2; exit 1 ;;
esac
"""

# A merged release PR, as `gh pr list --json` gives it.
FAKE_GH = """\
#!/bin/sh
[ "$1 $2" = "pr list" ] || { echo "unexpected: gh $*" >&2; exit 1; }
echo '[{"title": "release: v9.9.9", "mergedAt": "2026-10-20T00:00:00Z", "headRefName": "release/v9.9.9"}]'
"""


@pytest.fixture
def tag_release(tmp_path, monkeypatch, capsys):
    """Runs the task's action in an empty project, and gives back what it printed."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, text in (("git", FAKE_GIT), ("gh", FAKE_GH)):
        (fakebin / name).write_text(text, encoding="utf-8")
        (fakebin / name).chmod(0o755)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ['PATH']}")
    # Either makes rich colour its output, which would split the phrases looked for.
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("TTY_COMPATIBLE", raising=False)

    def run() -> str:
        (action,) = task_release_tag()["actions"]
        action()
        # rich wraps lines at its width, which is 80 where output is not a terminal.
        return " ".join(capsys.readouterr().out.split())

    return run


def test_without_a_release_workflow_it_names_no_build_and_no_package(tag_release):
    printed = tag_release()

    assert "Release v9.9.9 tagged!" in printed
    assert "PyPI" not in printed
    assert "GitHub Actions" not in printed
    assert "nothing is built or published: the tag is the release." in printed


def test_with_a_release_workflow_it_gives_the_publishing_steps(tag_release):
    """Where the workflow the steps describe exists, they still apply."""
    workflows = Path(".github", "workflows")
    workflows.mkdir(parents=True)
    (workflows / "release.yml").write_text("name: release\n", encoding="utf-8")

    printed = tag_release()

    assert "1. Monitor GitHub Actions for build and publish." in printed
    assert "Check TestPyPI:" in printed
    assert "Check PyPI:" in printed
    assert "the tag is the release" not in printed
