"""Tests for the ``block-dangerous-commands`` PreToolUse hook.

The hook script lives at ``tools/hooks/ai/block-dangerous-commands.py``. Its
filename contains hyphens, so it isn't directly importable as a module — we
load it via ``importlib`` and invoke ``main()`` directly with a stubbed stdin.

Pattern mirrors ``tests/test_hook_cbm_code_discovery_gate.py``.
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
    # The allowed example copy asks git about the checkout (#1061)
    monkeypatch.setattr(hook, "_envrc_example_modified", lambda: False)
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


# --- Copilot apply_patch with bare patch text (issue #1042) -----------------
#
# Copilot CLI 1.0.104 in -p mode edits files through ``apply_patch`` and sends
# the patch text itself as ``toolArgs`` -- not JSON. It also runs the
# Claude-format hooks with ``tool_name: "Edit"`` and the same text as
# ``tool_input``. Both shapes below are copied from a live probe's debug log.

_BASHRC_PATCH = (
    "*** Begin Patch\n*** Update File: /home/user/.bashrc\n@@\n"
    "+export ALLOW_AI_READY_TO_MERGE=1\n*** End Patch\n"
)
_BENIGN_PATCH = (
    "*** Begin Patch\n*** Add File: docs/x.md\n+Never run git reset --hard here.\n*** End Patch\n"
)


def test_copilot_apply_patch_text_blocks_env_persistence(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Copilot patch-text payload persisting the bypass var is denied."""
    payload = json.dumps({"toolName": "apply_patch", "toolArgs": _BASHRC_PATCH})
    code, out = _run_raw(hook, monkeypatch, capsys, payload)
    assert code == 0
    assert json.loads(out)["permissionDecision"] == "deny"


def test_claude_format_patch_text_blocks_env_persistence(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Copilot's Claude-format ``Edit`` payload carrying patch text is denied."""
    payload = json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": _BASHRC_PATCH}
    )
    code, _ = _run_raw(hook, monkeypatch, capsys, payload)
    assert code == 2


def test_copilot_apply_patch_text_checks_move_destination(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A patch-text ``*** Move to:`` onto a protected file is denied."""
    patch = (
        "*** Begin Patch\n*** Update File: notes.txt\n*** Move to: .envrc.local\n@@\n"
        "+export ALLOW_AI_READY_TO_MERGE=1\n*** End Patch\n"
    )
    payload = json.dumps({"toolName": "apply_patch", "toolArgs": patch})
    code, out = _run_raw(hook, monkeypatch, capsys, payload)
    assert code == 0
    assert json.loads(out)["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "payload",
    [
        {"toolName": "apply_patch", "toolArgs": _BENIGN_PATCH},
        {"tool_name": "Edit", "tool_input": _BENIGN_PATCH},
    ],
    ids=["copilot", "claude-format"],
)
def test_patch_text_mentioning_dangerous_command_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: dict[str, str],
) -> None:
    """Patch text is file content, not a shell command: it is not scanned as one."""
    code, out = _run_raw(hook, monkeypatch, capsys, json.dumps(payload))
    assert code == 0
    assert out.strip() == ""


@pytest.mark.parametrize(
    "payload",
    [
        {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "apply_patch <<PATCH\n" + _BASHRC_PATCH + "PATCH",
                "_raw_patch": "",
            },
        },
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/home/user/.bashrc",
                "content": "export ALLOW_AI_READY_TO_MERGE=1",
                "_raw_patch": "",
            },
        },
        {
            "toolName": "create",
            "toolArgs": json.dumps(
                {
                    "_raw_patch": "",
                    "path": "/home/user/.bashrc",
                    "content": "export ALLOW_AI_READY_TO_MERGE=1",
                }
            ),
        },
    ],
    ids=["codex-apply-patch", "claude-write", "copilot-json"],
)
def test_caller_supplied_raw_patch_key_does_not_skip_checks(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: dict[str, object],
) -> None:
    """A tool call that sets the internal ``_raw_patch`` key itself is still checked."""
    code, out = _run_raw(hook, monkeypatch, capsys, json.dumps(payload))
    assert code == 2 or json.loads(out)["permissionDecision"] == "deny"


# --- apply_patch with JSON path/content instead of a command (issue #1048) --
#
# No CLI is known to send this shape. Without a ``command`` the Codex branch
# must fall through to the shape-based fallback rather than allow.

_BASHRC_WRITE = {"path": "/home/user/.bashrc", "content": "export ALLOW_AI_READY_TO_MERGE=1"}


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "apply_patch", "tool_input": _BASHRC_WRITE},
        {"toolName": "apply_patch", "toolArgs": json.dumps(_BASHRC_WRITE)},
    ],
    ids=["claude-format", "copilot"],
)
def test_apply_patch_json_path_content_blocks_env_persistence(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    payload: dict[str, object],
) -> None:
    """An ``apply_patch`` call with path + content and no command is still checked."""
    code, out = _run_raw(hook, monkeypatch, capsys, json.dumps(payload))
    assert code == 2 or json.loads(out)["permissionDecision"] == "deny"


def test_apply_patch_json_path_content_ordinary_write_is_allowed(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The fall-through does not block an ordinary path + content write."""
    payload = {"tool_name": "apply_patch", "tool_input": {"path": "docs/x.md", "content": "hi"}}
    code, out = _run_raw(hook, monkeypatch, capsys, json.dumps(payload))
    assert code == 0
    assert out.strip() == ""


def test_raw_patch_input_ignores_non_patch_strings(hook: types.ModuleType) -> None:
    """Only a string naming a patch target is wrapped; anything else stays empty."""
    assert hook._raw_patch_input("{not valid json") == {}
    assert hook._raw_patch_input(42) == {}
    assert hook._raw_patch_input(_BASHRC_PATCH) == {hook._RAW_PATCH_KEY: _BASHRC_PATCH}


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


# ---------------------------------------------------------------------------
# The merge rule reads each command on its own (#894)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # Read-only: `git` and `merge` in different commands, or merge as an argument.
        ("git log --oneline --grep merge -5", 0),
        ("git diff HEAD~1 -- tools/doit/github.py | grep -n merge", 0),
        ("git grep -n pr_merge -- tools/doit; echo merge", 0),
        ("git merge-base HEAD origin/main", 0),
        # `--ff-only` in another command does not make the merge fast-forward only.
        ("git merge origin/main; echo --ff-only", 2),
        ("git merge origin/main && echo --ff-only", 2),
        ("git merge origin/main;echo --ff-only", 2),
        # Still a merge wherever it sits on the line.
        ("git merge origin/main", 2),
        ("git -C . merge origin/main", 2),
        ("git status && git merge origin/main", 2),
        ("git merge --ff-only origin/main", 0),
        ("git merge --ff-only origin/main; echo merge", 0),
        ("git merge --ff-only;echo done", 0),
        # Gap 5 (#1007): a newline or a `#` comment does not end the command for
        # shlex, so `--ff-only` on the next line or inside a comment used to
        # count as an argument to the `git merge` before it.
        ("git merge feature\necho --ff-only", 2),
        ("git merge feature # --ff-only", 2),
        ("git merge feature #--ff-only", 2),
        ("git merge feature # c\n--ff-only", 2),
        # A `#` mid-word, or quoted, is not a comment, so the merge after it runs.
        ("x#y; git merge feature", 2),
        ("echo '#' ; git merge feature", 2),
        ("x\\ #; git merge feature", 2),
        # A quoted string spanning lines stays one word, and a glued `&&`
        # still ends the command before it.
        ('echo "x\n# y" ; git merge feature', 2),
        ('echo "a\nb"&&git merge feature', 2),
        ('echo "unterminated\n&&git merge feature', 2),
        # A backslash-newline continuation is still one command.
        ("git \\\nmerge feature", 2),
        ("git merge feature \\\n--ff-only", 0),
        # A real `--ff-only` elsewhere on the same command still allows.
        ("git merge feature $(echo --ff-only)", 2),
        ("git merge feature && git pull --ff-only", 2),
        # Gap 6 (#1007): `--attr-source` and `--config-env` are global options
        # that take a separate value; missing them from
        # `_GIT_GLOBAL_OPTS_WITH_VALUE` let their value be mistaken for the
        # subcommand, so the merge rule never fired.
        ("git --attr-source HEAD merge feature", 2),
        ("git --config-env foo.bar=baz merge feature", 2),
        # Gap 3 (#1011): the merge rule used to lex the whole command,
        # heredoc bodies included. An unbalanced `"` in a body opened a quote
        # that swallowed the `git merge` after the terminator. Passing the
        # merge rule the command with heredoc bodies already stripped fixes
        # it.
        ("cat <<'EOF'\n\"\nEOF\ngit merge feature \"", 2),
        # A merge in a heredoc body is still seen when the hook does not
        # recognise the receiver as running it (#1011): bodies are skipped
        # only in addition to the full scan, never instead of it.
        ("env -i bash <<EOF\ngit merge feature\nEOF", 2),
    ],
)
def test_merge_rule_on_main_reads_each_command(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    expected: int,
) -> None:
    """Matching `git`, `merge` and `--ff-only` anywhere on the line got both ways wrong (#894)."""
    assert _run(hook, monkeypatch, command, branch="main") == expected


# ---------------------------------------------------------------------------
# Dynamic write targets and git restores of protected files (#1055)
# ---------------------------------------------------------------------------

_DYNAMIC_TARGET_BLOCKED = [
    "f=.envrc.loc; echo x >> ${f}al",
    "echo x >> .envrc.loca?",
    "echo x >> .envrc.loca{l,}",
    "echo x >> $(printf .envrc.local)",
    "echo x >> `printf .envrc.local`",
    "echo x >> .envrc.l*l",
    "echo x >> .envrc.loca[l]",
    "f=.envrc.local; echo x >> $f",
    'echo x >> "$GITHUB_OUTPUT"',
    "f=.envrc.local; echo x | tee -a $f",
    "cp x .envrc.l*",
    "sed -i s/a/b/ .envrc.l*",
    "echo x >> $HOME/.config/fi*/config.fish",
    "git checkout other -- .envrc.local.example",
    "git restore --source=other .envrc.local.example",
    "git -C . restore -s other .envrc.local.example",
    "git checkout other -- .envrc.l*",
    "echo x >> ~/.bash*",
    # Grammar the scanner no longer tries to mirror: the rest is a wildcard
    "git checkout other .envrc.local.example",
    "echo x >> $'\\x2eenvrc.local'",
    "echo x >> .envrc.loca[]l]",
    "echo x >> .envrc.loc{a{l,},}",
    # Gaps from #1061: sources, later sed operands, broad pathspecs, dd, extglob
    "cp src/.envrc.loca? .",
    "cp src/.envrc.loca? ./",
    "mv src/.envrc.l* .",
    "sed -i s/a/b/ .envrc.loca? other.txt",
    "sed -e s/a/b/ -i .envrc.loca? other",
    "git checkout HEAD~1 -- .",
    "git checkout HEAD~1 .",
    "git restore --source=HEAD~1 :/",
    "git restore -s HEAD~1 ./",
    "git restore -s X ..",
    "git restore --source=X --pathspec-from-file=p",
    "git checkout other -- :(top).envrc.local.example",
    "dd if=evil of=.envrc.loca?",
    "dd if=evil of=.envrc.local",
    "echo x > .envrc.@(local)",
    "echo x > .envrc.+(local)",
    "echo x > .envrc.?(local)",
    # Review of #1064: attached sed scripts, wildcard after the dot, unnormalized
    # pathspecs, extglob outside redirects
    "sed -i -es/a/b/ .envrc.local",
    "sed -i -nes/a/b/ .envrc.loca?",
    "sed -ni s/a/b/ .envrc.local",
    "sed --in-place s/a/b/ .envrc.loca?",
    "sed -i -f script.sed .envrc.loca?",
    "cp src/.[e]nvrc.local .",
    "cp src/.?nvrc.local .",
    "git checkout HEAD~1 -- src/..",
    "git restore -s HEAD~1 ./.",
    "git restore -s HEAD~1 ../repo",
    "git checkout HEAD~1 -- /abs/repo",
    "cp src/.envrc.@(local) .",
    "tee .envrc.@(local) < x",
    # Second review of #1064: abbreviated long options, `~` paths, moved roots
    "sed --in-pl s/a/b/ .envrc.loca?",
    "sed -i --expr=s/a/b/ .envrc.loca?",
    "sed -i --expr s/a/b/ .envrc.loca?",
    "git restore --sour=HEAD~1 .",
    "git restore --source=HEAD~1 --pathspec-from=p",
    "git checkout HEAD~1 -- ~/src/repo",
    "git -C .. checkout HEAD~1 -- repo/",
    "git --work-tree=.. restore -s HEAD~1 repo/",
]

_DYNAMIC_TARGET_ALLOWED = [
    "cp .envrc.local.example .envrc.local",
    "echo 'export ENABLE_LSP_TOOL=1' >> .envrc.local",
    "cp src/* build/",
    "echo x >> out.log",
    "echo x >> *.log",
    "echo x >> $TMPDIR/out.log",
    "git checkout main",
    "git checkout -b feature/x",
    "git checkout main -- src/foo.py",
    "git restore src/foo.py",
    'git commit -m "a >> $f"',
    # Guard the everyday forms next to the #1061 gaps
    "cp src/*.py build/",
    "cp src/.* build/",  # documented residual: a bare `.*` is too common to block
    "cp $src build/",
    "sed -i s/a/b/ *.py",
    "sed -i s/a/$/ file.txt",
    "sed -i -e s/a/b/ file.txt",
    "git checkout -- .",
    "git checkout .",
    "git restore .",
    "git restore --staged .",
    "git checkout main -- src/",
    "git restore -s HEAD src/foo.py",
    "dd if=a of=out.img",
    "dd of=/dev/null",
    "git stash pop",  # the later `cp` is gated on HEAD instead
    "sed -i -es/a/$/ file.txt",
    "sed -n -e s/a/b/ .envrc.local",  # no -i: reads only
    "sed -i -E s/a/b/ file.txt",
    "git checkout main -- src/../src/foo.py",
    "git restore -s HEAD src/sub/..foo",
    "sed -n --quiet -e s/a/b/ file.txt",
    "git -C sub checkout -- file.py",  # no source: content comes from the index
    "git restore --staged src/foo.py",
]


@pytest.mark.parametrize("command", _DYNAMIC_TARGET_BLOCKED)
def test_dynamic_write_target_that_could_be_protected_is_blocked(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 2


@pytest.mark.parametrize("command", _DYNAMIC_TARGET_ALLOWED)
def test_write_target_that_cannot_be_protected_is_allowed(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 0


# ---------------------------------------------------------------------------
# The allowed example copy is gated on the example matching HEAD (#1061)
# ---------------------------------------------------------------------------

_ENVRC_COPY = "cp .envrc.local.example .envrc.local"


def _run_with_git(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    outcome: int | BaseException,
) -> int:
    """Run the hook with ``subprocess.run`` faked: return code *outcome*, or raise it."""

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if isinstance(outcome, BaseException):
            raise outcome
        return subprocess.CompletedProcess(args, outcome)

    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    monkeypatch.setattr(hook.subprocess, "run", fake_run)
    _set_stdin(monkeypatch, _bash_payload(command))
    return int(hook.main())


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (1, 2),  # example differs from HEAD
        (0, 0),  # clean
        (128, 0),  # not a repo: fail open
        (FileNotFoundError("git"), 0),  # git missing: fail open
        (subprocess.TimeoutExpired("git", 5), 0),  # timeout: fail open
    ],
)
def test_example_copy_is_gated_on_head(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    outcome: int | BaseException,
    expected: int,
) -> None:
    assert _run_with_git(hook, monkeypatch, _ENVRC_COPY, outcome) == expected


@pytest.mark.parametrize("outcome", [1, 0])
def test_other_documented_write_and_stash_pop_ignore_head(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, outcome: int
) -> None:
    echo = "echo 'export ENABLE_LSP_TOOL=1' >> .envrc.local"
    assert _run_with_git(hook, monkeypatch, echo, outcome) == 0
    assert _run_with_git(hook, monkeypatch, "git stash pop", outcome) == 0
