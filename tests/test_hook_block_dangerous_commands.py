"""Tests for the ``block-dangerous-commands`` PreToolUse hook.

The hook script lives at ``tools/hooks/ai/block-dangerous-commands.py``. Its
filename contains hyphens, so it isn't directly importable as a module — we
load it via ``importlib`` and invoke ``main()`` directly with a stubbed stdin.

Pattern mirrors ``tests/test_bash_ban_raw_tools.py``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "hooks" / "ai" / "block-dangerous-commands.py"
)


def _load_hook() -> types.ModuleType:
    """Load the hook script as a fresh module instance."""
    spec = importlib.util.spec_from_file_location("block_dangerous_commands", HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load hook from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> Iterator[types.ModuleType]:
    """Load a fresh copy of the hook module for each test."""
    module = _load_hook()
    sys.modules["block_dangerous_commands"] = module
    try:
        yield module
    finally:
        sys.modules.pop("block_dangerous_commands", None)


def _set_stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    """Replace ``sys.stdin`` with a StringIO containing *payload*."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


def _bash_payload(command: str) -> str:
    """Build a Claude/Gemini/Codex Bash tool payload."""
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _run(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    *,
    branch: str = "feature/test",
) -> int:
    """Run the hook for *command* and return its exit code.

    ``get_current_branch`` is monkeypatched to return *branch* so tests are
    deterministic regardless of the actual checkout state (TRAP 2 from the plan).
    """
    monkeypatch.setattr(hook, "get_current_branch", lambda: branch)
    _set_stdin(monkeypatch, _bash_payload(command))
    # ``main()`` returns its exit code rather than calling ``sys.exit()``, so
    # call it directly. ``int()`` narrows the module attribute's ``Any`` type
    # for mypy's ``warn_return_any``.
    return int(hook.main())


# ---------------------------------------------------------------------------
# Must-block cases — all currently ALLOWED before this fix
# ---------------------------------------------------------------------------


def test_block_push_force_refspec_head_main(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push --force origin HEAD:main`` is blocked."""
    assert _run(hook, monkeypatch, "git push --force origin HEAD:main") == 2


def test_block_push_plus_main(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push origin +main`` is blocked ('+' prefix is force-push marker)."""
    assert _run(hook, monkeypatch, "git push origin +main") == 2


def test_block_push_with_git_global_dir_option(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git -C . push --force origin main`` is blocked despite global -C option."""
    assert _run(hook, monkeypatch, "git -C . push --force origin main") == 2


def test_block_push_with_git_global_dash_c(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git -c core.pager=cat push --force origin main`` is blocked."""
    assert _run(hook, monkeypatch, "git -c core.pager=cat push --force origin main") == 2


def test_block_push_with_git_global_git_dir(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git --git-dir=.git push --force origin main`` is blocked."""
    assert _run(hook, monkeypatch, "git --git-dir=.git push --force origin main") == 2


def test_block_push_force_with_lease_eq_form(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push --force-with-lease=main origin HEAD:main`` is blocked.

    The ``=<ref>`` form of ``--force-with-lease`` must be recognised as a
    force flag (prefix-aware matching).
    """
    assert _run(hook, monkeypatch, "git push --force-with-lease=main origin HEAD:main") == 2


def test_block_bash_c_push_force(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bash -c "git push --force origin main"`` is blocked via payload unwrap."""
    assert _run(hook, monkeypatch, 'bash -c "git push --force origin main"') == 2


def test_block_sh_c_push_force(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sh -c "git push --force origin main"`` is blocked via payload unwrap."""
    assert _run(hook, monkeypatch, 'sh -c "git push --force origin main"') == 2


def test_block_eval_push_force(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``eval "git push --force origin main"`` is blocked via eval unwrap."""
    assert _run(hook, monkeypatch, 'eval "git push --force origin main"') == 2


def test_block_branch_delete_with_git_global_dir(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git -C . branch -D main`` is blocked despite global -C option."""
    assert _run(hook, monkeypatch, "git -C . branch -D main") == 2


def test_block_bash_c_branch_delete(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bash -c "git branch -D main"`` is blocked via payload unwrap."""
    assert _run(hook, monkeypatch, 'bash -c "git branch -D main"') == 2


def test_block_bash_c_gh_pr_merge_admin(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bash -c "gh pr merge 1 --admin"`` is blocked — proves unwrap reaches non-git checks."""
    assert _run(hook, monkeypatch, 'bash -c "gh pr merge 1 --admin"') == 2


# ---------------------------------------------------------------------------
# Must-stay-ALLOWED guards
# ---------------------------------------------------------------------------


def test_allow_push_refspec_main_to_feature(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push origin main:feature`` is allowed (destination is 'feature')."""
    assert _run(hook, monkeypatch, "git push origin main:feature") == 0


def test_allow_push_refspec_head_to_refs_feature(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push origin HEAD:refs/heads/feature`` is allowed (destination is 'feature')."""
    assert _run(hook, monkeypatch, "git push origin HEAD:refs/heads/feature") == 0


def test_allow_push_feature_branch(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push origin feature`` is allowed."""
    assert _run(hook, monkeypatch, "git push origin feature") == 0


def test_allow_force_push_feature_branch(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push --force origin feat/my-feature`` is allowed (existing regression guard)."""
    assert _run(hook, monkeypatch, "git push --force origin feat/my-feature") == 0


def test_allow_bash_c_echo_main(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bash -c "echo main"`` is allowed — unwrap must not over-block."""
    assert _run(hook, monkeypatch, 'bash -c "echo main"') == 0


def test_allow_git_global_dir_push_feature(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git -C /other/repo push origin feature`` is allowed."""
    assert _run(hook, monkeypatch, "git -C /other/repo push origin feature") == 0


# ---------------------------------------------------------------------------
# Message-correctness: deletion refspec must keep its own reason string
# ---------------------------------------------------------------------------


def test_delete_refspec_colon_main_reports_deletion_reason(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``git push origin :main`` must be blocked with the *deletion* reason, not push reason.

    This guards the ordering hazard documented in the plan: check_push_to_protected
    runs before check_delete_protected_branch. The colon-prefixed token must be
    skipped by the push check so the delete check owns it and reports the correct
    reason.
    """
    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    _set_stdin(monkeypatch, _bash_payload("git push origin :main"))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Deleting protected remote branch 'main'" in captured.err


# ---------------------------------------------------------------------------
# Existing regression: force-with-lease without "=" still blocked
# ---------------------------------------------------------------------------


def test_block_push_force_with_lease_plain(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``git push --force-with-lease origin main`` (no ``=``) is still blocked."""
    assert _run(hook, monkeypatch, "git push --force-with-lease origin main") == 2


# ---------------------------------------------------------------------------
# Determinism: bare push on protected branch is blocked only when on that branch
# ---------------------------------------------------------------------------


def test_bare_push_blocked_when_on_main(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``git push`` is blocked when current branch is main."""
    assert _run(hook, monkeypatch, "git push", branch="main") == 2


def test_bare_push_allowed_when_on_feature(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``git push`` with no explicit branch is allowed on a feature branch.

    (Force push without explicit branch is still blocked separately — this checks
    plain push only.)
    """
    # A bare "git push" with no force flag on a feature branch is allowed
    assert _run(hook, monkeypatch, "git push", branch="feature/my-work") == 0


# ---------------------------------------------------------------------------
# Multi-agent input-schema parsing (``_parse_input``)
#
# The hook serves five CLIs across three input schemas. Everything above uses
# the Claude/Gemini/Codex schema. These cover the other two, which deny via
# stdout JSON with exit 0 rather than via exit code 2 — so an exit-code-only
# assertion would pass even if their parsing broke entirely.
# ---------------------------------------------------------------------------

DANGEROUS = "git push --force origin HEAD:main"


def _copilot_payload(command: str) -> str:
    """Build a Copilot CLI payload (camelCase keys; ``toolArgs`` is a JSON string)."""
    return json.dumps({"toolName": "bash", "toolArgs": json.dumps({"command": command})})


def _agy_payload(command: str) -> str:
    """Build an Antigravity CLI payload (nested ``toolCall``, PascalCase args)."""
    return json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": command}}})


def _run_raw(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: str,
    *,
    branch: str = "feature/test",
) -> tuple[int, str]:
    """Run the hook on a raw payload; return ``(exit_code, stdout)``."""
    monkeypatch.setattr(hook, "get_current_branch", lambda: branch)
    _set_stdin(monkeypatch, payload)
    code = int(hook.main())
    return code, capsys.readouterr().out


def test_copilot_schema_denies_via_stdout(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Copilot payloads deny with ``permissionDecision`` on stdout and exit 0."""
    code, out = _run_raw(hook, monkeypatch, capsys, _copilot_payload(DANGEROUS))
    assert code == 0
    assert json.loads(out)["permissionDecision"] == "deny"


def test_antigravity_schema_denies_via_stdout(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Antigravity payloads deny with ``decision`` on stdout and exit 0."""
    code, out = _run_raw(hook, monkeypatch, capsys, _agy_payload(DANGEROUS))
    assert code == 0
    assert json.loads(out)["decision"] == "deny"


def test_copilot_schema_allows_safe_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A safe command through the Copilot schema emits no deny payload."""
    code, out = _run_raw(hook, monkeypatch, capsys, _copilot_payload("git status"))
    assert code == 0
    assert out.strip() == ""


def test_antigravity_schema_allows_safe_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A safe command through the Antigravity schema emits no deny payload."""
    code, out = _run_raw(hook, monkeypatch, capsys, _agy_payload("git status"))
    assert code == 0
    assert out.strip() == ""


def test_copilot_schema_survives_malformed_tool_args(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-JSON ``toolArgs`` string is tolerated rather than raising."""
    payload = json.dumps({"toolName": "bash", "toolArgs": "{not valid json"})
    code, _ = _run_raw(hook, monkeypatch, capsys, payload)
    assert code == 0


def test_non_dict_tool_input_is_tolerated(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-dict ``tool_input`` falls back to an empty dict instead of raising.

    Guards the ``isinstance`` check in ``_parse_input``: without it, ``.get()``
    would raise ``AttributeError`` on a string payload.
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": "oops"})
    code, _ = _run_raw(hook, monkeypatch, capsys, payload)
    assert code == 0


# --- Fail-closed behaviour (issue #679) ------------------------------------
#
# The hook uses two deny contracts: exit code 2 (Claude/Gemini/Codex) and
# stdout JSON (Antigravity/Copilot). They diverge on *failure*: a script that
# produces no output is "allow" for the stdout-contract CLIs. When the hook
# cannot evaluate a command it must deny for every CLI, which means emitting
# all three contracts at once because the caller is unknown at that point.


def _assert_denies_every_contract(code: int, out: str, err: str) -> None:
    """Assert the payload denies for all five supported CLIs."""
    assert code == 2, "Claude/Gemini/Codex block on exit code 2"
    payload = json.loads(out)
    assert payload["decision"] == "deny", "Antigravity reads `decision`"
    assert payload["permissionDecision"] == "deny", "Copilot reads `permissionDecision`"
    assert payload["reason"]
    assert payload["permissionDecisionReason"]
    assert "BLOCKED" in err, "Claude/Gemini/Codex surface the stderr message"


def test_malformed_stdin_denies_instead_of_allowing(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unparsable stdin denies for every CLI rather than returning 1.

    Regression for #679: ``return 1`` is not a block for any of the five CLIs,
    so malformed input previously let the operation through everywhere.
    """
    _set_stdin(monkeypatch, "not json")
    code = int(hook.run())
    captured = capsys.readouterr()
    _assert_denies_every_contract(code, captured.out, captured.err)


def test_internal_error_denies_instead_of_allowing(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unexpected exception inside ``main`` denies for every CLI."""

    def _boom() -> tuple[str, str, dict[str, object]]:
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(hook, "_parse_input", lambda *_: _boom())
    _set_stdin(monkeypatch, _bash_payload("git status"))
    code = int(hook.run())
    captured = capsys.readouterr()
    _assert_denies_every_contract(code, captured.out, captured.err)
    assert "RuntimeError" in captured.out


def test_non_dict_toplevel_payload_denies(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valid JSON that isn't an object denies rather than raising a traceback."""
    _set_stdin(monkeypatch, '"a bare string"')
    code = int(hook.run())
    captured = capsys.readouterr()
    _assert_denies_every_contract(code, captured.out, captured.err)


def test_run_passes_through_normal_outcomes(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``run`` is transparent when ``main`` completes normally."""
    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    _set_stdin(monkeypatch, _bash_payload("git status"))
    assert int(hook.run()) == 0
    assert capsys.readouterr().out.strip() == ""


def test_fail_closed_payload_is_a_single_json_object(
    hook: types.ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both stdout keys ride in one object; two objects would break parsers."""
    assert hook._fail_closed("probe") == 2
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    assert set(json.loads(out)) == {
        "decision",
        "reason",
        "permissionDecision",
        "permissionDecisionReason",
    }


def test_script_denies_malformed_input_as_a_subprocess() -> None:
    """End-to-end through the real ``__main__`` path, not just ``main()``.

    The in-process tests bypass the script's entry point; this one exercises
    the exit code a CLI actually observes.
    """
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )
    _assert_denies_every_contract(proc.returncode, proc.stdout, proc.stderr)


# --- Launcher fail-closed behaviour (issue #680) ---------------------------
#
# `block-dangerous-commands.sh` exists because the in-script guards from #679
# cannot cover a script that never starts. It checks preconditions rather than
# the hook's exit status: the hook exits 2 on its own fail-closed path, which
# is indistinguishable from "python3 could not find the file", so branching on
# exit status would append a second deny payload to the hook's own.

LAUNCHER_PATH = HOOK_PATH.with_suffix(".sh")

requires_posix_sh = pytest.mark.skipif(
    sys.platform == "win32",
    reason="launcher is POSIX sh; the hook wirings that use it are POSIX-only",
)


def _run_launcher(
    payload: str, *, cwd: Path | None = None, script: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the launcher with *payload* on stdin."""
    return subprocess.run(
        ["sh", str(script or LAUNCHER_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


@requires_posix_sh
def test_launcher_passes_through_a_normal_deny() -> None:
    """A dangerous command still denies with the CLI's native contract."""
    proc = _run_launcher(_agy_payload(DANGEROUS))
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "deny"


@requires_posix_sh
def test_launcher_passes_through_an_allow() -> None:
    """A safe command still produces no deny payload."""
    proc = _run_launcher(_agy_payload("git status"))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@requires_posix_sh
def test_launcher_emits_exactly_one_payload_on_fail_closed() -> None:
    """Regression: the launcher must not append a payload to the hook's own.

    Both "hook fail-closed" and "hook missing" exit 2. A launcher that keyed
    off the exit status would emit two JSON objects on stdout here.
    """
    proc = _run_launcher("not json")
    assert proc.returncode == 2
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON object, got {len(lines)}"
    json.loads(lines[0])


@requires_posix_sh
def test_launcher_denies_when_the_hook_script_is_missing(tmp_path: Path) -> None:
    """The case the launcher exists for: the .py is absent, so nothing can run."""
    stray = tmp_path / LAUNCHER_PATH.name
    stray.write_text(LAUNCHER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    proc = _run_launcher(_agy_payload("git status"), script=stray)

    payload = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert payload["decision"] == "deny"
    assert payload["permissionDecision"] == "deny"
    assert "BLOCKED" in proc.stderr


@requires_posix_sh
def test_launcher_resolves_the_hook_independently_of_cwd(tmp_path: Path) -> None:
    """The launcher locates the hook via its own path, not the caller's CWD."""
    proc = _run_launcher(_agy_payload(DANGEROUS), cwd=tmp_path)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "deny"


# ---------------------------------------------------------------------------
# Block-and-redirect: a commit message passed by heredoc (#759)
# ---------------------------------------------------------------------------

_BLOCKED_FLAG = "--" + "admin"  # assembled so this file is not itself blocked


def test_commit_heredoc_block_names_the_file_alternative(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The block must say what to do instead, not just that something is wrong.

    A commit message naming a blocked pattern is refused because the heredoc is
    scanned as arguments. The generic "contains dangerous pattern" wording sends
    the author hunting for a dangerous command they never wrote; the redirect
    sends them to ``-F <file>`` (ADR-9019, category 1).
    """
    command = f"git commit -F - <<EOF\ndocs: describe the {_BLOCKED_FLAG} bypass\nEOF"
    _set_stdin(monkeypatch, _bash_payload(command))
    with pytest.raises(SystemExit) as exc_info:
        sys.exit(hook.main())

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "git commit -F <file>" in err
    assert "tmp/agents/" in err


def test_redirect_rewrites_the_reason_not_the_verdict(hook: types.ModuleType) -> None:
    """Detection only: a command that was allowed stays allowed.

    ``redirect_reason`` runs after ``check_command`` has decided, so it cannot
    change what is blocked. That is what keeps this free of the bypass risk that
    stopped the hook being taught to parse heredoc bodies (ADR-9019, rule 3).
    """
    safe = "git commit -F - <<EOF\ndocs: a message with nothing blocked in it\nEOF"
    assert hook.check_command(safe) == (False, "")
    assert hook.redirect_reason(safe, "") == ""

    flagged = f"git commit -F - <<EOF\ndocs: the {_BLOCKED_FLAG} bypass\nEOF"
    is_dangerous, original = hook.check_command(flagged)
    assert is_dangerous
    assert hook.redirect_reason(flagged, original) != original


@pytest.mark.parametrize(
    ("template", "redirected"),
    [
        ("git commit -F - <<EOF\nx {flag}\nEOF", True),
        ("git commit --amend -F - <<EOF\nx {flag}\nEOF", True),
        ("cd /repo && git commit -F - <<EOF\nx {flag}\nEOF", True),
        ("/usr/bin/git commit -F - <<EOF\nx {flag}\nEOF", True),
        # Owned by another command: a commit quoted inside someone else's body
        # must not collect a redirect that does not apply to it.
        ("cat >> tests/t.py <<PY\nx = 'git commit -F - <<EOF {flag}'\nPY", False),
        ("git tag -F - <<EOF\nx {flag}\nEOF", False),
        ("cat > notes.md <<EOF\nx {flag}\nEOF", False),
        # No heredoc: never affected by the scan-as-arguments problem, so it
        # keeps the reason that actually applies to it.
        ("gh pr merge 1 {flag}", False),
        ('git commit -m "x" && gh pr merge 1 {flag}', False),
    ],
)
def test_redirect_fires_only_on_a_commit_heredoc(
    hook: types.ModuleType, template: str, redirected: bool
) -> None:
    """Scoped to the shape that has a better path available."""
    command = template.format(flag=_BLOCKED_FLAG)
    assert hook._is_commit_message_heredoc(command) is redirected
