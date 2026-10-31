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
    from collections.abc import Callable, Iterator

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


@pytest.mark.parametrize(
    "command",
    [
        # the delimiter word continues past the part a plain name covers
        "cat <<E\\OF\nEOF\n(printenv)\nE",
        "cat <<'E'\\OF\nEOF\nx=$(printenv)\nE",
        "cat <<EOF\r\nEOF\n(printenv)\nEOF",
        # a delimiter line split by a backslash-newline ends the body
        "cat <<EOF\nEO\\\nF\n(printenv)",
        # a default value in a parameter expansion is run
        "echo ${x:-$(printenv)}",
        "echo ${x:-`printenv`}",
        'echo "${x:-$(printenv)}"',
        'echo "${x:-`printenv`}"',
        "echo ${x:-${y:-$(printenv)}}",
        "cat <<EOF\n${x:-$(printenv)}\nEOF",
        # quoted parts inside the expansion are read as the skipper reads them
        'echo ${x:-"$(printenv)"}',
        'echo ${x:-"\'"$(printenv)}',
        'echo ${x:-"}"$(printenv)}',
        "echo ${x:-$'}'$(printenv)}",
        "echo ${x:-$'\\''$(printenv)}",
        "echo ${x:-'}'$(printenv)}",
        'echo "${x:-"}"$(printenv)}"',
        'echo "${x:-\'}$(printenv)}"',
    ],
)
def test_check_command_scans_lines_the_shell_runs_and_expansion_defaults(
    hook: types.ModuleType, command: str
) -> None:
    """Lines outside a heredoc body and substitutions in ${...} are scanned."""
    is_dangerous, _reason = hook.check_command(command)
    assert is_dangerous


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'EOF'\nmentions $(printenv) here\nEOF",
        "cat <<EOF\nplain text\nEOF\necho done",
        "git commit -m \"$(cat <<'EOF'\nfix: a thing $(printenv)\n\nEOF\n)\"",
        "echo ${VAR:-default}",
        'echo "${VAR:-default}"',
        "echo ${#arr[@]}",
        "echo ${x:-'$(printenv)'}",
        "echo ${x:-$(echo hi)}",
    ],
)
def test_check_command_allows_well_formed_heredocs_and_plain_expansions(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """A quoted heredoc body and a plain ${...} expansion stay allowed."""
    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    is_dangerous, reason = hook.check_command(command)
    assert not is_dangerous, reason


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("echo ${x:-$(a)}", ["a"]),
        ("echo ${x:-`a`}", ["a"]),
        ('echo "${x:-$(a)} $(b)"', ["a", "b"]),
        ("echo ${x:-${y:-$(a)}} $(b)", ["a", "b"]),
        ("echo ${x:-'$(a)'}", []),
        ("echo \"${x:-'$(a)'}\"", ["a"]),
        ("echo ${x:-$((1+2))}", []),
        ("echo ${#arr[@]}", []),
        ('echo ${x:-"$(a)"}', ["a"]),
        ('echo ${x:-"}"$(a)}', ["a"]),
        ("echo ${x:-$'}'$(a)}", ["a"]),
        ("echo ${x:-$'\\''$(a)}", ["a"]),
        ("echo ${x:-$'$(a)'}", []),
        ("echo ${x:-'}'$(a)}", ["a"]),
        ('echo "${x:-"}"$(a)}"', ["a"]),
        ("cat <<'E'\\OF\nEOF\nx=$(a)\nE", ["a"]),
        ("cat <<E\\OF\nEOF\n(a)\nE", ["a"]),
        ("cat <<EOF\nEO\\\nF\n(a)", ["a"]),
    ],
)
def test_substitution_payloads_in_parameter_expansions(
    hook: types.ModuleType, command: str, expected: list[str]
) -> None:
    """Bodies inside ${...} are collected; quoted and arithmetic text is not."""
    assert hook._substitution_payloads(command) == expected


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


requires_posix_paths = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the hook reads patch paths as POSIX paths",
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


# A write command's operands end at `;`, `&&`, `||`, `|` or an unquoted newline,
# so a later command's expansion is not read as its destination (#1131)
_WRITE_COMMAND_END_ALLOWED = [
    'cp src/x.py tmp/tr.bak; out=$(true); echo "$out"',
    'cp tmp/tr.bak src/x.py; rm tmp/tr.bak; out=$(true); echo "$out"',
    'cp a b; echo "$x"',
    'cp a b && echo "$x"',
    'cp a b || echo "$x"',
    'cp a b | cat "$x"',
    'cp a b\nout=$(true); echo "$out"',
    'cp a b\necho "$x"',
    'cp a b\n\necho "$x"',
    '\ncp a b\necho "$x"\n',
    'mv a b; echo "$x"',
    'mv a b\necho "$x"',
    'mv a b && echo "$x"',
    'install a b; echo "$x"',
    'install a b || echo "$x"',
    'rsync a b; echo "$x"',
    'rsync a b\necho "$x"',
    'ln a b; echo "$x"',
    'ln a b && echo "$x"',
    'dd if=a of=b; echo "$x"',
    'dd if=a of=b\necho "$x"',
    'dd if=a of=b || echo "$x"',
    'cp a b ; out=$(true); echo "$out"',
]

_WRITE_COMMAND_END_BLOCKED = [
    "cp a $f",
    "cp a b; cp a $f",
    "cp a b && cp a $f",
    "cp a b || cp a $f",
    "cp a b;cp a $f",
    "cp a b\ncp a $f",
    "cp a b\ncp a .envrc.loca?",
    "cp a b; cp c .bashrc",
    "cp a b;cp c ~/.bash*",
    'cp a "$f"',
    "cp a $(echo b) $f",
    "cp a $(true; echo x) $f",
    "echo $(cp a $f)",
    "cp a ';' $f",
    "cp a 'b;' $f",
    'cp a "b\nc" $f',
    "echo hi\necho x >> .envrc.local",
    "echo hi\ncp a $f",
    "mv a $f",
    "mv a b\nmv a $f",
    "mv a b; mv a $f",
    "install a $f",
    "install a b; install a $f",
    "rsync a b; rsync a $f",
    "ln a b; ln a $f",
    "dd if=a of=$f",
    "dd if=a of=b; dd if=a of=$f",
    "dd if=a of=b\ndd if=a of=$f",
    # the allowed `.envrc.local` copy is the whole command or nothing
    "echo x > .envrc.local.example\ncp .envrc.local.example .envrc.local",
    "cp .envrc.local.example .envrc.local\necho x",
    "cp .envrc.local.example .envrc.local; echo x",
    # a command the tokens cannot be read for keeps the wider scan
    "cp a $(true; echo) $f ; ((1))",
    "cp a $(true; echo) $f\ncat <<EOF\nx\nEOF",
]


@pytest.mark.parametrize("command", _WRITE_COMMAND_END_ALLOWED)
def test_later_command_expansion_is_not_a_write_destination(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 0


@pytest.mark.parametrize("command", _WRITE_COMMAND_END_BLOCKED)
def test_expansion_in_a_write_commands_own_operands_is_blocked(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 2


def test_documented_envrc_copy_is_still_allowed_alone(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(hook, monkeypatch, "cp .envrc.local.example .envrc.local") == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a\nb", "a ; b"),
        ("\na\nb\n", "a ; b"),
        ("a\n\nb", "a ;  ; b"),
        ("a b", "a b"),
        ("\na b\n", "a b"),
        ('echo "a\nb"\nc', 'echo "a\nb" ; c'),
        ("echo 'a\nb'\nc", "echo 'a\nb' ; c"),
        ("echo $(a\nb)\nc", "echo $(a\nb) ; c"),
        ("echo `a\nb`\nc", "echo `a\nb` ; c"),
        ("echo a\\\nb\nc", "echo a\\\nb\nc"),
        ("echo a\\\nb", "echo a\\\nb"),
        ("echo 'a\nb", "echo 'a\nb"),
        ("echo $(a\nb", "echo $(a\nb"),
        ("cat <<EOF\nx\nEOF", "cat <<EOF\nx\nEOF"),
        ("a # c\nb", "a # c\nb"),
        ("cat <<< x\nb", "cat <<< x ; b"),
    ],
)
def test_newlines_as_separators(hook: types.ModuleType, text: str, expected: str) -> None:
    assert hook._newlines_as_separators(text) == expected


# A redirect after `git checkout`/`git restore` is no checkout argument (#1088)
_CHECKOUT_REDIRECT_ALLOWED = [
    "git checkout -q main 2>/dev/null",
    "git checkout -q main >/dev/null",
    "git checkout -q main &>/dev/null",
    "git checkout -q main 2>&1",
    "git checkout main >/dev/null 2>&1",
    "git checkout -q feature 2>/dev/null",
    "git restore --staged src/foo.py 2>/dev/null",
    "git checkout main </dev/null",
    "git checkout main 2>/dev/null && git pull",
]

_CHECKOUT_REDIRECT_BLOCKED = [
    "git checkout main -- .envrc.local.example 2>/dev/null",
    "git checkout main . >/dev/null",
    "git restore --source=main . 2>/dev/null",
    "git checkout main > .envrc.local",
    "git checkout main >/dev/null -- .envrc.local.example",
    "git restore --source=main 2>/dev/null .envrc.local.example",
    "git checkout main . 2>&1",
    # quoted operators lose their quoting in the tokens: still blocked
    "git checkout main '&' .envrc.local.example",
    "git checkout main '(' .envrc.local.example",
    "git checkout main '>' .envrc.local.example",
    # a spaced fd number may be a revision, so it is not dropped
    "git restore --source 2 >/dev/null .envrc.local.example",
    "git checkout 2 >/dev/null .",
]


@pytest.mark.parametrize("command", _CHECKOUT_REDIRECT_ALLOWED)
def test_checkout_with_redirect_is_allowed(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 0


@pytest.mark.parametrize("command", _CHECKOUT_REDIRECT_BLOCKED)
def test_checkout_redirect_does_not_hide_protected_write(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 2


# A `;`, `&&` or `||` glued to the last checkout argument ends the command (#1093)
_CHECKOUT_GLUED_SEPARATOR_ALLOWED = [
    "git checkout -b docs/x; grep -rl foo . 2>/dev/null",
    "git checkout -b docs/x; grep -rl foo .",
    "git checkout main; ls .",
    "git checkout -b docs/x ; grep -rl foo .",
    "git checkout -b docs/x && grep -rl foo . 2>/dev/null",
    "git checkout -b docs/x; grep -rl foo src 2>/dev/null",
    "git checkout main&& ls .",
    "git checkout main|| ls .",
]

_CHECKOUT_GLUED_SEPARATOR_BLOCKED = [
    "git checkout main -- .envrc.local.example; ls",
    "git checkout main .envrc.local.example; ls .",
    "git checkout main .; ls",
    "git restore --source=main .; ls",
    "git checkout main .&& ls",
    "git checkout main . || ls",
    "git checkout main; git checkout other -- .envrc.local.example",
    # a quoted `;` is no separator: a protected name after it stays a target
    "git checkout main 'x;' .envrc.local.example",
    # ... and a broad pathspec after it still counts, with the source before it
    "git checkout main 'x;' .",
    'git checkout main "x;" .',
    "git checkout main 'x&&' .",
    "git restore --source=main 'x;' .",
]


@pytest.mark.parametrize("command", _CHECKOUT_GLUED_SEPARATOR_ALLOWED)
def test_checkout_glued_separator_ends_scan(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 0


@pytest.mark.parametrize("command", _CHECKOUT_GLUED_SEPARATOR_BLOCKED)
def test_checkout_glued_separator_keeps_protected_write_blocked(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert _run(hook, monkeypatch, command) == 2


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


_EXAMPLE = ".envrc.local.example"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        capture_output=True,
        check=True,
    )


def _repo_with_example(root: Path) -> None:
    """Make *root* a repo whose HEAD holds the example as ``SAFE=1``."""
    _git(root, "init", "-q")
    # Windows runners set autocrlf globally; the LF bytes written here must match HEAD
    _git(root, "config", "core.autocrlf", "false")
    (root / _EXAMPLE).write_bytes(b"SAFE=1\n")
    _git(root, "add", _EXAMPLE)
    _git(root, "commit", "-qm", "example")


def _swap(root: Path) -> None:
    (root / _EXAMPLE).write_bytes(b"SWAPPED=1\n")


def _no_commit(root: Path) -> None:
    _git(root, "init", "-q")
    _swap(root)


def _untracked(root: Path) -> None:
    _repo_with_example(root)
    _git(root, "rm", "-q", "--cached", _EXAMPLE)
    _git(root, "commit", "-qm", "untrack")


def _flagged(flag: str) -> Callable[[Path], None]:
    def setup(root: Path) -> None:
        _repo_with_example(root)
        _git(root, "update-index", flag, _EXAMPLE)
        _swap(root)

    return setup


def _smudge_filter(root: Path) -> None:
    """A worktree attribute and repo-local filter that turn HEAD's blob into the swap."""
    _repo_with_example(root)
    (root / ".gitattributes").write_text(f"{_EXAMPLE} filter=x\n")
    _git(root, "config", "filter.x.smudge", "sed s/SAFE/SWAPPED/")
    _swap(root)


def _clean(root: Path) -> None:
    _repo_with_example(root)


def _modified(root: Path) -> None:
    _repo_with_example(root)
    _swap(root)


def _not_a_repo(root: Path) -> None:
    _swap(root)


def _no_example(root: Path) -> None:
    _git(root, "init", "-q")


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (_clean, 0),
        (_modified, 2),
        # index flags make `git diff` skip the worktree; the bytes still differ
        (_flagged("--skip-worktree"), 2),
        (_flagged("--assume-unchanged"), 2),
        # git filters are repo-controlled, so the raw blob is compared
        (_smudge_filter, 2),
        # inside a repo, an example HEAD does not hold fails closed
        (_untracked, 2),
        (_no_commit, 2),
        (_not_a_repo, 0),  # fail open
        (_no_example, 0),  # nothing to copy: the `cp` fails on its own
    ],
)
def test_example_copy_is_gated_on_head(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    setup: Callable[[Path], None],
    expected: int,
) -> None:
    setup(tmp_path)
    # keep git from finding an enclosing repo above tmp_path
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    _set_stdin(monkeypatch, _bash_payload(_ENVRC_COPY))
    assert int(hook.main()) == expected


def test_example_gate_matches_autocrlf_checkout(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clean Windows-style checkout (CRLF in the worktree, LF in HEAD) is not modified."""
    _repo_with_example(tmp_path)
    _git(tmp_path, "config", "core.autocrlf", "true")
    (tmp_path / _EXAMPLE).unlink()
    _git(tmp_path, "checkout", "--", _EXAMPLE)
    assert (tmp_path / _EXAMPLE).read_bytes() == b"SAFE=1\r\n"
    monkeypatch.chdir(tmp_path)
    assert hook._envrc_example_modified() is False


@pytest.mark.parametrize("error", [FileNotFoundError("git"), subprocess.TimeoutExpired("git", 5)])
def test_example_gate_fails_open_when_git_cannot_answer(
    hook: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: BaseException,
) -> None:
    _not_a_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert _run_with_git(hook, monkeypatch, _ENVRC_COPY, error) == 0


@pytest.mark.parametrize("outcome", [1, 0])
def test_other_documented_write_and_stash_pop_ignore_head(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, outcome: int
) -> None:
    echo = "echo 'export ENABLE_LSP_TOOL=1' >> .envrc.local"
    assert _run_with_git(hook, monkeypatch, echo, outcome) == 0
    assert _run_with_git(hook, monkeypatch, "git stash pop", outcome) == 0


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("", []),
        ("a ; b", [("a", False), (";", True), ("b", False)]),
        ("a;b", [("a", False), (";", True), ("b", False)]),
        ("x&&y", [("x", False), ("&&", True), ("y", False)]),
        ("a||b", [("a", False), ("||", True), ("b", False)]),
        ("a|b", [("a", False), ("|", True), ("b", False)]),
        ("a|&b", [("a", False), ("|&", True), ("b", False)]),
        ("a & b", [("a", False), ("&", True), ("b", False)]),
        ("(a)", [("(", True), ("a", False), (")", True)]),
        # shlex returns adjacent punctuation as one token; it is split here.
        (
            "(cd x)&&y;(z)&",
            [
                ("(", True),
                ("cd", False),
                ("x", False),
                (")", True),
                ("&&", True),
                ("y", False),
                (";", True),
                ("(", True),
                ("z", False),
                (")", True),
                ("&", True),
            ],
        ),
        ("a&;b", [("a", False), ("&", True), (";", True), ("b", False)]),
        ("a>&2|b", [("a", False), (">&", False), ("2", False), ("|", True), ("b", False)]),
        ("echo \\;&&x", [("echo", False), ("\\;", False), ("&&", True), ("x", False)]),
        (
            'echo \'&\' "a;b" "$(x & y)"',
            [("echo", False), ("'&'", False), ('"a;b"', False), ('"$(x & y)"', False)],
        ),
        ("echo \\;", [("echo", False), ("\\;", False)]),
        ("a\\;b", [("a\\;b", False)]),
        ("echo \\&&x", [("echo", False), ("\\&", False), ("&", True), ("x", False)]),
        # An even count of backslashes escapes itself, not the operator.
        ("a\\\\&b", [("a\\\\", False), ("&", True), ("b", False)]),
        ("a\\\\\\&b", [("a\\\\\\&b", False)]),
        (
            "echo $'a&b' ; ls",
            [("echo", False), ("$'a&b'", False), (";", True), ("ls", False)],
        ),
        (
            "echo $'a  &  b'x ; ls",
            [("echo", False), ("$'a  &  b'x", False), (";", True), ("ls", False)],
        ),
        (
            "echo $'a\\'b & c' ; ls",
            [("echo", False), ("$'a\\'b & c'", False), (";", True), ("ls", False)],
        ),
        ("echo $'ab' & ls", [("echo", False), ("$'ab'", False), ("&", True), ("ls", False)]),
        ("echo $'a&b", [("echo", False), ("$'a&b", False)]),
        ("echo $'a&b ; ls", [("echo", False), ("$'a&b", False), (";", False), ("ls", False)]),
        ("echo 'a & b", [("echo", False), ("'a", False), ("&", False), ("b", False)]),
        ('echo "a;b', [("echo", False), ('"a;b', False)]),
        ("a#b ; ls", [("a#b", False), (";", True), ("ls", False)]),
        (
            "ls >&2 &> f ;; <x",
            [
                ("ls", False),
                (">&", False),
                ("2", False),
                ("&>", False),
                ("f", False),
                (";;", False),
                ("<", False),
                ("x", False),
            ],
        ),
        (
            "git checkout $(echo main) x",
            [("git", False), ("checkout", False), ("$(echo main)", False), ("x", False)],
        ),
        (
            "git checkout `echo a & b` y",
            [("git", False), ("checkout", False), ("`echo a & b`", False), ("y", False)],
        ),
        ("cat <(ls) x", [("cat", False), ("<(ls)", False), ("x", False)]),
        ("cat >(ls) x", [("cat", False), (">(ls)", False), ("x", False)]),
        (
            'git checkout x "a\\" & b \\"c" y',
            [
                ("git", False),
                ("checkout", False),
                ("x", False),
                ('"a\\" & b \\"c"', False),
                ("y", False),
            ],
        ),
        (
            "echo $(a $(b & c)) ; d",
            [("echo", False), ("$(a $(b & c))", False), (";", True), ("d", False)],
        ),
        (
            'echo "$(x "y;z")" & d',
            [("echo", False), ('"$(x "y;z")"', False), ("&", True), ("d", False)],
        ),
        ('echo "`a & b`" & d', [("echo", False), ('"`a & b`"', False), ("&", True), ("d", False)]),
        ("echo ${x:-a&b} & d", [("echo", False), ("${x:-a&b}", False), ("&", True), ("d", False)]),
        ("echo $((1&2)) & d", [("echo", False), ("$((1&2))", False), ("&", True), ("d", False)]),
        ("$(a)&&b", [("$(a)", False), ("&&", True), ("b", False)]),
        ("echo a#b & c", [("echo", False), ("a#b", False), ("&", True), ("c", False)]),
        (
            "echo x # a & b\nls & c",
            [
                ("echo", False),
                ("x", False),
                ("#", False),
                ("a", False),
                ("&", False),
                ("b", False),
                ("ls", False),
                ("&", True),
                ("c", False),
            ],
        ),
        # Anything unclosed or not modelled comes out as words only.
        ("echo $(a & b", [("echo", False), ("$(a", False), ("&", False), ("b", False)]),
        ("echo ${a & b", [("echo", False), ("${a", False), ("&", False), ("b", False)]),
        ("echo `a & b", [("echo", False), ("`a", False), ("&", False), ("b", False)]),
        ("echo <(a & b", [("echo", False), ("<(a", False), ("&", False), ("b", False)]),
        ('echo "$(a & b"', [("echo", False), ('"$(a', False), ("&", False), ('b"', False)]),
        ("((a&1))", [("((a&1))", False)]),
        ("x ; ((a&1))", [("x", False), (";", False), ("((a&1))", False)]),
        # A comment after an operator inside a substitution can hide its `)`.
        (
            "echo $(a;# )\n b) & c",
            [
                ("echo", False),
                ("$(a;#", False),
                (")", False),
                ("b)", False),
                ("&", False),
                ("c", False),
            ],
        ),
        (
            "echo $(a|#)\n) ; d",
            [("echo", False), ("$(a|#)", False), (")", False), (";", False), ("d", False)],
        ),
        ("echo a\\", [("echo", False), ("a\\", False)]),
        ("cat <<EOF & x", [("cat", False), ("<<EOF", False), ("&", False), ("x", False)]),
        (
            "echo $(case a in a) b;; esac) & c",
            [
                ("echo", False),
                ("$(case", False),
                ("a", False),
                ("in", False),
                ("a)", False),
                ("b;;", False),
                ("esac)", False),
                ("&", False),
                ("c", False),
            ],
        ),
        ("[[ a && b ]]", [("[[", False), ("a", False), ("&&", False), ("b", False), ("]]", False)]),
    ],
)
def test_operator_tokens(
    hook: types.ModuleType, command: str, expected: list[tuple[str, bool]]
) -> None:
    assert hook.operator_tokens(command) == expected


@pytest.mark.parametrize("operator", ["&", "|&", "(", ")", ";", "&&", "||", "|"])
def test_restore_scan_ends_at_each_command_operator(hook: types.ModuleType, operator: str) -> None:
    """The checkout's arguments stop at the operator; the next command's do not count."""
    tokens = hook._exact_operator_tokens(f"git checkout main {operator} cat .envrc.local.example")
    assert tokens is not None
    assert tokens[:4] == ["git", "checkout", "main", operator]
    assert hook._git_restore_targets(tokens, 0, exact_operators=True) == []
    # the checkout's own protected argument before the operator is still found
    own = hook._exact_operator_tokens(f"git checkout .envrc.local.example {operator} cat x")
    assert own is not None
    assert hook._git_restore_targets(own, 0, exact_operators=True) == [".envrc.local.example"]


@pytest.mark.parametrize("operator", ["&", ";"])
@pytest.mark.parametrize("exact", [True, False])
def test_later_dashes_do_not_change_checkout_arguments(
    hook: types.ModuleType, operator: str, exact: bool
) -> None:
    command = f"git checkout .envrc.local.example {operator} x -- y"
    tokens = hook._exact_operator_tokens(command) if exact else command.split()
    assert tokens is not None
    targets = hook._git_restore_targets(tokens, 0, exact_operators=exact)
    assert ".envrc.local.example" in targets


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        # The scan runs on every token pass, and the older passes do not end
        # it at `&` (#1117)
        ("git checkout main & cat .envrc.local.example", True),
        ("git checkout main '&' .envrc.local.example", True),
        ("git checkout main \\& .envrc.local.example", True),
        ("git checkout $(echo main) .envrc.local.example", True),
        ("git checkout main .envrc.local.example '", True),
        # A quoted path built from a variable or substitution
        ('git checkout main "$PWD/.envrc.local.example"', True),
        ('git checkout main "$(pwd)/.envrc.local.example"', True),
        ('git checkout main "`pwd`/.envrc.local.example"', True),
        ('git restore -s main "$PWD/.envrc.local.example"', True),
        # words mixing quotes with `$'...'` segments (#1117)
        ("git checkout main \".envrc\"$'.local.example'", True),
        ("git checkout main '.envrc'$'.local'.example", True),
        ("git checkout main .envrc$'\\x2elocal'.example", True),
        ("git restore -s main x$'/../.envrc.local.example'", True),
        ("git checkout main $'.envrc.local.example'", True),
    ],
)
def test_check_command_checkout_operator_scan(
    hook: types.ModuleType, command: str, blocked: bool
) -> None:
    assert hook.check_command(command)[0] is blocked


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("a '&' b", ["a", "'&'", "b"]),
        ("git checkout 'ma'in", ["git", "checkout", "main"]),
        ("git checkout $(echo main) x", ["git", "checkout", "$(echo main)", "x"]),
        ("a & b", ["a", "&", "b"]),
        ('a "$PWD/x" "`pwd`"y', ["a", "$PWD/x", "`pwd`y"]),
        # a `$'` word gets the text bash passes (#1117)
        ("a $'x y'", ["a", "x y"]),
        ("a \".x\"$'.y'z", ["a", ".x.yz"]),
        ("a '.x'$'\\x2e'y", ["a", ".x.y"]),
        ("a $'\\056x'", ["a", ".x"]),
        ("a $'\\ex'", ["a", "\x1bx"]),
        ("a x$'\\c'y", ["a", "x$'\\c'y"]),
        ("a $'&'", ["a", "$'&'"]),
        ("a 'b", None),
    ],
)
def test_exact_operator_tokens(
    hook: types.ModuleType, command: str, expected: list[str] | None
) -> None:
    assert hook._exact_operator_tokens(command) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # each result is what bash 5.3 printf '%s' $'<body>' printed
        ("\\456envrc", ".envrc"),  # octal is masked to a byte
        ("\\056envrc", ".envrc"),
        ("\\0056envrc", "\x056envrc"),  # at most 3 octal digits
        ("\\x2envrc", ".nvrc"),  # at most 2 hex digits
        ("\\u002eenvrc", ".envrc"),
        ("\\x41F", "AF"),
        ("\\?", "?"),
        ("\\eX", "\x1bX"),
        ("\\a\\b\\f\\n\\r\\t\\v", "\a\b\f\n\r\t\v"),
        ("\\'q\\\"", "'q\""),
        # escapes bash keeps or treats specially, and non-ASCII results
        ("\\N{FULL STOP}envrc", None),
        ("\\cA", None),
        ("\\u2eenvrc", None),
        ("\\xG", None),
        ("é", None),
        ("x\\", None),
    ],
)
def test_decode_ansi_c(hook: types.ModuleType, body: str, expected: str | None) -> None:
    assert hook._decode_ansi_c(body) == expected


def _restore_token_lists(
    hook: types.ModuleType, command: str
) -> list[tuple[list[str], dict[str, bool]]]:
    """The token lists the checkout/restore scan runs on, with its flags."""
    exact = hook._exact_operator_tokens(command)
    assert exact is not None
    return [
        (exact, {"exact_operators": True}),
        (hook._redirect_tokens(command), {}),
        (command.split(), {"glued_separators": True}),
    ]


_RESTORE_PROTECTED = ".envrc.local.example"


@pytest.mark.parametrize("pathspec", [".", _RESTORE_PROTECTED])
@pytest.mark.parametrize(
    "options",
    ["-Ws HEAD~1", "-WsHEAD~1", "-sHEAD~1", "-s HEAD~1", "-SWs main", "-SWsmain", "-pWs main"],
)
def test_restore_short_option_cluster_source(
    hook: types.ModuleType, options: str, pathspec: str
) -> None:
    command = f"git restore {options} {pathspec}"
    for tokens, flags in _restore_token_lists(hook, command):
        assert hook._git_restore_targets(tokens, 0, **flags), (command, flags)
    blocked, _ = hook.check_command(command)
    assert blocked


@pytest.mark.parametrize(
    "command",
    ["git restore .", "git restore -W .", "git restore -SW .", "git restore -qp ."],
)
def test_restore_cluster_without_source_stays_allowed(hook: types.ModuleType, command: str) -> None:
    for tokens, flags in _restore_token_lists(hook, command):
        assert hook._git_restore_targets(tokens, 0, **flags) == []
    assert hook.check_command(command) == (False, "")


def test_restore_cluster_source_value_is_not_a_path(hook: types.ModuleType) -> None:
    """The value after a trailing `s` is skipped, so it is no pathspec."""
    for tokens, flags in _restore_token_lists(hook, f"git restore -Ws {_RESTORE_PROTECTED} x"):
        assert hook._git_restore_targets(tokens, 0, **flags) == []


@pytest.mark.parametrize("option", ["--pathspec-from-file=f", "--pathspec-from=f", "--path=f"])
def test_checkout_pathspec_from_file_with_revision_counts_as_source(
    hook: types.ModuleType, option: str
) -> None:
    command = f"git checkout main {option}"
    for tokens, flags in _restore_token_lists(hook, command):
        assert hook._git_restore_targets(tokens, 0, **flags) == [_RESTORE_PROTECTED]
    assert hook.check_command(command)[0]


def test_checkout_pathspec_from_file_without_revision_stays_allowed(hook: types.ModuleType) -> None:
    command = "git checkout --pathspec-from-file=f"
    for tokens, flags in _restore_token_lists(hook, command):
        assert hook._git_restore_targets(tokens, 0, **flags) == []
    assert hook.check_command(command) == (False, "")


@pytest.mark.parametrize(
    "prefix",
    [
        "GIT_WORK_TREE=.. git",
        "GIT_DIR=../.git git",
        "env GIT_WORK_TREE=.. git",
        "export GIT_WORK_TREE=..; git",
        "git -c core.worktree=.. ",
        "git -c Core.WorkTree=.. ",
        "git -ccore.worktree=.. ",
        "git --git-dir=../.git ",
        "git --git-dir ../.git ",
        "git --config-env=core.worktree=WT ",
        "git --config-env core.worktree=WT ",
        "git -C .. ",
        "git --work-tree=.. ",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.worktree GIT_CONFIG_VALUE_0=.. git",
        "GIT_CONFIG_PARAMETERS=x git",
        "read GIT_WORK_TREE < f; git",
        "printf -v GIT_DIR %s ../.git; git",
        "echo x >> .git/config; git",
        "git -c include.path=../x.cfg ",
        "git -cincludeIf.onbranch:main.path=x ",
        "git --config-env=include.path=P ",
    ],
)
@pytest.mark.parametrize(
    "tail",
    ["checkout main -- src/", "restore --source=main src/", "restore -Ws main src/"],
)
def test_working_tree_movers_block_a_sourced_restore(
    hook: types.ModuleType, prefix: str, tail: str
) -> None:
    command = f"{prefix.strip()} {tail}"
    for tokens, flags in _restore_token_lists(hook, command):
        idx = tokens.index("git")
        assert hook._git_restore_targets(tokens, idx, **flags) == [_RESTORE_PROTECTED], (
            command,
            flags,
        )
    assert hook.check_command(command)[0]


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        # after a cd, only a pathspec that climbs out of the new directory can
        # reach another tree's root
        ("cd .. && git checkout main -- ../", True),
        ("pushd x ; git restore -s main ../..", True),
        ("cd x ; git -c user.name=x checkout main -- /repo/", True),
        ("cd x && git restore -Ws main ~/repo/", True),
        ("cd x && git checkout main -- a/../../", True),
        ("cd x && git checkout main -- .?/", True),
        ("cd x && git checkout main -- '$UP'/", True),
        ("cd x && git checkout main -- :(top)src", True),
        ("popd && git checkout main -- ../", True),
        ("env -C .. git checkout main -- ../", True),
        ("env --chdir=x git restore -s main ../", True),
        ("env -C /wt git checkout main -- src/foo.py", False),
        ("cd /wt && git checkout main -- src/foo.py", False),
        ("cd /wt && git restore -s main src/ README.md", False),
    ],
)
def test_cd_moves_the_working_tree_for_climbing_pathspecs(
    hook: types.ModuleType, command: str, blocked: bool
) -> None:
    assert hook.check_command(command)[0] is blocked


@pytest.mark.parametrize(
    "setup",
    ["git config core.worktree ..", "git config include.path ../x.cfg"],
)
def test_earlier_repo_config_moves_the_working_tree(hook: types.ModuleType, setup: str) -> None:
    # git honours a core.worktree written to the repository config
    command = f"{setup} && git checkout main -- src/"
    tokens = hook._exact_operator_tokens(command)
    idx = len(tokens) - 1 - tokens[::-1].index("git")
    assert hook._git_restore_targets(tokens, idx, exact_operators=True) == [_RESTORE_PROTECTED]
    assert hook.check_command(command)[0]


@pytest.mark.parametrize(
    "command",
    [
        "git checkout main -- src/",
        "git restore --source=main src/",
        "git -c user.name=x checkout main -- src/",
    ],
)
def test_sourced_restore_without_a_mover_stays_allowed(
    hook: types.ModuleType, command: str
) -> None:
    for tokens, flags in _restore_token_lists(hook, command):
        assert hook._git_restore_targets(tokens, 0, **flags) == []
    assert hook.check_command(command) == (False, "")


def test_mover_without_a_source_stays_allowed(hook: types.ModuleType) -> None:
    command = "cd .. && git checkout -- src/"
    for tokens, flags in _restore_token_lists(hook, command):
        assert hook._git_restore_targets(tokens, tokens.index("git"), **flags) == []


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        # a closed group folds and keeps its original tokens after (#1120)
        (
            [".envrc.@", "(", "local", ")"],
            [".envrc.*", ".envrc.@", "(", "local", ")"],
        ),
        # a group holding `|` keeps them too: it may be a pipe
        (
            [".envrc.+", "(", "a", "|", "b", ")", "x"],
            [".envrc.*", ".envrc.+", "(", "a", "|", "b", ")", "x"],
        ),
        (
            ["echo", "x@", "(", "|", "tee", ".envrc.local", ")"],
            ["echo", "x*", "x@", "(", "|", "tee", ".envrc.local", ")"],
        ),
        (
            [".e?", "(", "(", "a", ")", ")"],
            [".e*", ".e?", "(", "(", "a", ")", ")"],
        ),
        # no closing `)`: every later token stays (#1104)
        (["echo", "x@", "(", "y"], ["echo", "x@", "(", "y"]),
        (
            ["echo", "x@", "(", "y", ";", "tee", ".envrc.local"],
            ["echo", "x@", "(", "y", ";", "tee", ".envrc.local"],
        ),
        # a `)` after the end of the command does not close the group
        (
            ["echo", "x@", "(", "&&", "tee", ".envrc.local", ")"],
            ["echo", "x@", "(", "&&", "tee", ".envrc.local", ")"],
        ),
        (["a*", "(", "&", "b", ")"], ["a*", "(", "&", "b", ")"]),
        (["a!", "(", "||", "b", ")"], ["a!", "(", "||", "b", ")"]),
        (["a@", "(", "|&", "b", ")"], ["a@", "(", "|&", "b", ")"]),
    ],
)
def test_collapse_extglobs_needs_a_closing_paren(
    hook: types.ModuleType, tokens: list[str], expected: list[str]
) -> None:
    assert hook._collapse_extglobs(tokens) == expected


@pytest.mark.parametrize(
    "command",
    [
        "echo 'x@(' ; echo y > .envrc.local",
        "echo x@'(' && cp a .envrc.local",
        "echo x@\\( ; tee .envrc.local < f",
    ],
)
def test_unclosed_extglob_keeps_later_commands(hook: types.ModuleType, command: str) -> None:
    assert hook.check_command(command)[0]


@pytest.mark.parametrize("op", [">", ">>", "&>", ">|"])
def test_folded_extglob_keeps_a_redirect_inside(hook: types.ModuleType, op: str) -> None:
    tokens = ["echo", "x@", "(", op, ".envrc.local", ")"]
    assert hook._collapse_extglobs(tokens) == ["echo", "x*", *tokens[1:]]


@pytest.mark.parametrize("op", [">", ">>", "&>", ">|"])
def test_quoted_paren_around_a_redirect_is_blocked(hook: types.ModuleType, op: str) -> None:
    assert hook.check_command(f"echo x@'(' {op} .envrc.local ')'")[0]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # When joining changes where the body ends (bash, dash and busybox sh
        # all join), a shell that did not join would end it elsewhere, so the
        # heredoc is unclear and nothing is stripped (#1113)
        ("cat <<EOF\nbody\nE\\\nOF\necho REAL\nEOF\n", None),
        ("cat <<EOF\nEO\\\nF\necho Z\nEOF\n", None),
        ("cat <<EOF\nline1\\\nEOF\necho still-body\nEOF\necho after\n", None),
        ("cat <<-EOF\nbody\n\tEO\\\nF\necho AFTER\nEOF\n", None),
        # joining that leaves the end in place strips the body as before
        (
            "cat <<-EOF\nbody\n\tE\\\n\tOF\necho AFTER1\nEOF\necho AFTER2\n",
            "cat <<-EOF\necho AFTER2\n",
        ),
        ("cat <<EOF\na\\\nb\nEOF\necho AFTER\n", "cat <<EOF\necho AFTER\n"),
        # an even count of backslashes joins nothing
        ("cat <<EOF\nbody\\\\\nEOF\necho AFTER\n", "cat <<EOF\necho AFTER\n"),
        # a quoted or escaped delimiter joins nothing
        ("cat <<'EOF'\nbody\nE\\\nOF\nEOF\necho AFTER\n", "cat <<'EOF'\necho AFTER\n"),
        ('cat <<"EOF"\nE\\\nOF\nEOF\necho AFTER\n', 'cat <<"EOF"\necho AFTER\n'),
        ("cat <<\\EOF\nE\\\nOF\nEOF\necho AFTER\n", "cat <<\\EOF\necho AFTER\n"),
    ],
)
def test_heredoc_body_ends_where_bash_joins_lines(
    hook: types.ModuleType, command: str, expected: str | None
) -> None:
    assert hook._without_heredoc_bodies(command) == (command if expected is None else expected)


def test_heredoc_joined_terminator_keeps_later_commands(hook: types.ModuleType) -> None:
    # bash ends the body at the joined `E\` + `OF`, so `cat ~/.netrc` runs
    command = "cat <<EOF\nbody\nE\\\nOF\ncat ~/.netrc\nEOF\n"
    assert hook.check_command(command)[0]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # the receiving shell joins a trailing `\` with the next line (#1122)
        ("bash <<EOF\ncat ~/.ne\\\ntrc\nEOF", ["cat ~/.ne\\", "trc", "cat ~/.netrc"]),
        ("bash <<'EOF'\ncat ~/.ne\\\ntrc\nEOF", ["cat ~/.ne\\", "trc", "cat ~/.netrc"]),
        (
            "bash <<-EOF\n\tcat ~/.n\\\n\\\netrc\nEOF",
            ["\tcat ~/.n\\", "\\", "etrc", "\tcat ~/.netrc", "cat ~/.netrc"],
        ),
        # `<<-` strips each line's tab before the shell joins (bash 5.3
        # ran `<<-EOF` and `<<-'EOF'` bodies `\techo ab\`, `\tcd` as `echo abcd`)
        (
            "bash <<-EOF\n\tcat ~/.ne\\\n\ttrc\nEOF",
            ["\tcat ~/.ne\\", "\ttrc", "\tcat ~/.ne\ttrc", "cat ~/.netrc"],
        ),
        # an even count of backslashes joins nothing
        ("sh <<EOF\necho a\\\\\nls\nEOF", ["echo a\\\\", "ls"]),
        ("bash <<EOF\necho ok\nEOF", ["echo ok"]),
    ],
)
def test_heredoc_payloads_join_continued_lines(
    hook: types.ModuleType, command: str, expected: list[str]
) -> None:
    assert hook._heredoc_payloads(command) == expected


# --- patch / git apply / git am as file writers (#1105) ---

_PATCH_STAND_IN = ".envrc.local.example"


def _unified(*paths: str) -> bytes:
    return "".join(f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n" for p in paths).encode()


@pytest.fixture
def patch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory holding a safe and a protected patch file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ok.patch").write_bytes(_unified("src/foo.py"))
    (tmp_path / "bad.patch").write_bytes(_unified(".bashrc"))
    (tmp_path / "example.patch").write_bytes(_unified(".envrc.local.example"))
    (tmp_path / "settings.patch").write_bytes(_unified(".claude/settings.json"))
    (tmp_path / "fish.patch").write_bytes(_unified("a/.config/fish/config.fish"))
    (tmp_path / "bare.patch").write_bytes(_unified("config.fish"))
    return tmp_path


def _patch_targets(hook: types.ModuleType, command: str, *, read: bool = True) -> list[list[str]]:
    """The write targets on each of the three token passes."""
    return [
        hook._bash_confirmed_write_targets(tokens, read_patch_files=read, **flags)
        for tokens, flags in _restore_token_lists(hook, command)
    ]


def _assert_patch_blocks(hook: types.ModuleType, command: str, *, read: bool = True) -> None:
    for targets in _patch_targets(hook, command, read=read):
        assert any(hook._matches_env_persistence_target(t, dynamic=True) for t in targets), command
    if read:
        assert hook.check_command(command)[0], command


def _assert_patch_allows(hook: types.ModuleType, command: str) -> None:
    for targets in _patch_targets(hook, command):
        assert targets == [], command
    assert hook.check_command(command) == (False, ""), command


@pytest.mark.parametrize(
    "template",
    [
        "git -C .config/fish apply {p}",
        "git -C.config/fish apply {p}",
        "git --work-tree=.config/fish apply {p}",
        "git --work-tree .config/fish apply {p}",
        "GIT_WORK_TREE=.config/fish git apply {p}",
        "env GIT_WORK_TREE=.config/fish git apply {p}",
        "git --git-dir=.git --work-tree=.config/fish apply {p}",
        "git --git-dir .git --work-tree /repo/.config/fish apply {p}",
        "GIT_WORK_TREE=/x git --work-tree=.config/fish apply {p}",
        "git -C /repo --work-tree=.config/fish apply {p}",
    ],
)
def test_git_apply_work_tree_protected_target_blocks(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    """A bare ``config.fish`` is protected only under the moved work tree (#1133)."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_blocks(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


@requires_posix_paths
@pytest.mark.parametrize(
    "template",
    [
        "git -C docs apply {p}",
        "git --work-tree=docs apply {p}",
        "git --work-tree docs apply {p}",
        "GIT_WORK_TREE=docs git apply {p}",
        "git --git-dir=.git --work-tree=docs apply {p}",
        "GIT_WORK_TREE=.config/fish git --work-tree=docs apply {p}",
    ],
)
def test_git_apply_work_tree_unprotected_target_allows(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_allows(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


@pytest.mark.parametrize(
    "template",
    [
        "git --work-tree=$TREE apply {p}",
        "git --work-tree $TREE apply {p}",
        "git -C $TREE apply {p}",
        "git --work-tree= apply {p}",
        "GIT_WORK_TREE=$TREE git apply {p}",
        "GIT_WORK_TREE= git apply {p}",
        "export GIT_WORK_TREE=$TREE; git apply {p}",
        "printf -v GIT_WORK_TREE .config/fish; git apply {p}",
    ],
)
def test_git_apply_unresolvable_work_tree_blocks(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    """A work tree the hook cannot spell out stands in as an unknown write."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    command = template.format(p=(patch_dir / "wt.patch").as_posix())
    tokens = hook.tokenize(command)
    git_idx = tokens.index("git")
    assert hook._git_patch_targets(tokens, git_idx, read_files=True) == [_PATCH_STAND_IN]


_COVERED_VALUE_OPTIONS = ["--attr-source", "--exec-path", "--namespace", "--super-prefix"]


def _wt_targets(hook: types.ModuleType, command: str) -> list[str]:
    tokens = hook.tokenize(command)
    targets: list[str] = hook._git_patch_targets(tokens, tokens.index("git"), read_files=True)
    return targets


@pytest.mark.parametrize(
    "template",
    [
        "git --work-tree=fish -C .config apply {p}",
        "git --work-tree fish -C .config apply {p}",
        "GIT_WORK_TREE=fish git -C .config apply {p}",
        "git -C ./.config/./fish apply {p}",
        "git -C docs -C /repo/.config/fish apply {p}",
        "git --git-dir=.git --work-tree=.config/fish -c core.worktree=docs apply {p}",
        "git -ccore.worktree=docs --work-tree=.config/fish apply {p}",
        "GIT_DIR=.git GIT_WORK_TREE=.config/fish git apply {p}",
    ],
)
def test_git_apply_work_tree_order_and_dots_block(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    """``-C`` applies wherever it stands; ``.`` segments are folded (#1133)."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_blocks(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


@requires_posix_paths
@pytest.mark.parametrize(
    "template",
    [
        "git --work-tree=fish -C docs apply {p}",
        "git -C docs --work-tree=fish apply {p}",
        "git -C .config/fish -C /repo/docs apply {p}",
        "git -C ./docs/./ apply {p}",
        "git --work-tree=./docs apply {p}",
    ],
)
def test_git_apply_work_tree_order_and_dots_allow(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_allows(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


@pytest.mark.parametrize(
    "template",
    [
        "git -C .. apply {p}",
        "git -C docs/.. apply {p}",
        "git -C docs/../.. apply {p}",
        "git -C ../docs apply {p}",
        "git -C docs -C .. apply {p}",
        "git -C .config/fish/.. apply {p}",
        "git -C '..\\docs' apply {p}",
        "git --work-tree=.. apply {p}",
        "git --work-tree=../x apply {p}",
        "git --work-tree=.config/../docs apply {p}",
        "git --work-tree ../docs apply {p}",
        "git -C docs --work-tree=../../x apply {p}",
        "GIT_WORK_TREE=../x git apply {p}",
        "GIT_WORK_TREE=.config/../docs git apply {p}",
        "env GIT_WORK_TREE=.. git apply {p}",
        "git --work-tree=docs apply --directory=../x {p}",
        "git apply --directory=../x {p}",
        "git apply --directory ../x {p}",
        "git apply --directory=docs/../x {p}",
        "git apply --directory='docs\\..\\x' {p}",
    ],
)
def test_git_apply_dotdot_segment_fails_closed(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    """A ``..`` segment in a root the hook would have to fold is never resolved."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    command = template.format(p=(patch_dir / "wt.patch").as_posix())
    assert _wt_targets(hook, command) == [_PATCH_STAND_IN], command


@pytest.mark.parametrize(
    "template",
    [
        "git -C ... apply {p}",
        "git -C ..docs apply {p}",
        "git --work-tree=docs.. apply {p}",
        "git apply --directory=..docs {p}",
    ],
)
def test_git_apply_dotdot_lookalike_is_not_a_segment(hook: types.ModuleType, template: str) -> None:
    tokens = hook.tokenize(template.format(p="x.patch"))
    assert hook._git_work_tree_root(tokens, 0, tokens.index("apply"))[1] is False


@pytest.mark.parametrize(
    "template",
    [
        "git --git-dir=.git apply {p}",
        "git --git-dir .git apply {p}",
        "GIT_DIR=.git git apply {p}",
        "env GIT_DIR=.git git apply {p}",
        "GIT_COMMON_DIR=.git git apply {p}",
        "env GIT_COMMON_DIR=.git git apply {p}",
        "GIT_CEILING_DIRECTORIES=/repo git apply {p}",
        "env GIT_CEILING_DIRECTORIES=/repo git apply {p}",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM=1 git apply {p}",
        "env GIT_DISCOVERY_ACROSS_FILESYSTEM=1 git apply {p}",
        "GIT_INDEX_FILE=x git apply {p}",
        "git -c core.worktree=.config/fish apply {p}",
        "git -ccore.worktree=.config/fish apply {p}",
        "git -c core.worktree=docs apply {p}",
        "git -c user.name=x apply {p}",
        "git --config-env=core.worktree=WT apply {p}",
        "git --config-env core.worktree=WT apply {p}",
        "git -c include.path=x apply {p}",
        "GIT_CONFIG_COUNT=1 git apply {p}",
        "GIT_CONFIG_PARAMETERS='core.worktree=x' git apply {p}",
        "GIT_CONFIG_GLOBAL=x GIT_CONFIG_KEY_0=core.worktree git apply {p}",
        "git -C docs --git-dir=.git apply {p}",
        "printf -v GIT_COMMON_DIR %s x; git apply {p}",
    ],
)
def test_git_apply_git_env_or_config_may_move_work_tree_blocks(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    """Any ``GIT_*`` word or config option may move the work tree (#1133)."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    command = template.format(p=(patch_dir / "wt.patch").as_posix())
    assert _wt_targets(hook, command) == [_PATCH_STAND_IN], command


@requires_posix_paths
@pytest.mark.parametrize(
    "template",
    [
        "git -c core.worktree=.config/fish --work-tree=docs apply {p}",
        "git --git-dir=.git --work-tree=docs apply {p}",
        "GIT_DIR=.git git --work-tree=docs apply {p}",
        "GIT_DIR=.git GIT_WORK_TREE=docs git apply {p}",
        "GIT_COMMON_DIR=.git GIT_WORK_TREE=docs git apply {p}",
        "GIT_CEILING_DIRECTORIES=/repo git --work-tree=docs apply {p}",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM=1 GIT_WORK_TREE=docs git apply {p}",
        "env GIT_CEILING_DIRECTORIES=/repo GIT_WORK_TREE=docs git apply {p}",
        "GIT_CONFIG_COUNT=1 git --work-tree=docs apply {p}",
        "git --config-env=core.worktree=WT --work-tree=docs apply {p}",
        "git -c user.name=x --work-tree=docs apply {p}",
    ],
)
def test_git_apply_literal_work_tree_overrides_config(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_allows(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


def _root(hook: types.ModuleType, command: str) -> tuple[str | None, bool]:
    tokens = hook.tokenize(command)
    result: tuple[str | None, bool] = hook._git_work_tree_root(
        tokens, tokens.index("git"), tokens.index("apply")
    )
    return result


@pytest.mark.parametrize(
    "command",
    [
        "cd sub && git apply p",
        "cd sub; git -C docs apply p",
        "cd sub && git --work-tree=docs apply p",
        "pushd sub; git apply p",
        "popd; git apply p",
        "env -C sub git apply p",
        "env -Csub git apply p",
        "env --chdir=sub git apply p",
        "cd /repo/sub && git -c user.name=x --work-tree=docs apply p",
    ],
)
def test_git_apply_cwd_moved_before_git_is_unresolvable(
    hook: types.ModuleType, command: str
) -> None:
    """A relative root has no meaning once the shell has changed directory."""
    assert _root(hook, command) == (None, True), command


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("cd sub && git -C /repo apply p", "/repo"),
        ("cd sub && git -C /repo -C docs apply p", "/repo/docs"),
        ("cd sub && git --work-tree=/repo/docs apply p", "/repo/docs"),
        ("cd sub && git --work-tree /repo/docs apply p", "/repo/docs"),
        ("cd sub && GIT_WORK_TREE=/repo/docs git apply p", "/repo/docs"),
        ("env -C sub git -C /repo/./docs apply p", "/repo/docs"),
        ("cd sub && git -C /repo --work-tree=docs apply p", "/repo/docs"),
    ],
)
def test_git_apply_absolute_root_resets_moved_cwd(
    hook: types.ModuleType, command: str, expected: str
) -> None:
    assert _root(hook, command) == (expected, False), command


@pytest.mark.parametrize(
    "command",
    [
        "git apply p",
        "git -C docs apply p",
        "git --work-tree=docs apply p",
        "GIT_WORK_TREE=docs git apply p",
        "git -C ./docs apply p",
    ],
)
def test_git_apply_cwd_not_moved_stays_resolvable(hook: types.ModuleType, command: str) -> None:
    assert _root(hook, command)[1] is False, command


@pytest.mark.parametrize(
    "template",
    [
        "cd sub && git apply {p}",
        "cd sub && git -C docs apply {p}",
        "env -C sub git apply {p}",
    ],
)
def test_git_apply_cwd_moved_blocks(hook: types.ModuleType, patch_dir: Path, template: str) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_blocks(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


def _value_options(hook: types.ModuleType) -> list[str]:
    return sorted(hook._GIT_GLOBAL_OPTS_WITH_VALUE - {"-C", "-c", "--work-tree"})


_VALUE_OPTION_COMMANDS = (
    "git {option} VALUE {prefix} apply {p}",
    "git {prefix} {option} VALUE apply {p}",
    "git {option}=VALUE {prefix} apply {p}",
)


@pytest.mark.parametrize("option", _COVERED_VALUE_OPTIONS)
@pytest.mark.parametrize(
    "prefix", ["-C .config/fish", "--work-tree=.config/fish", "--work-tree .config/fish"]
)
def test_git_apply_work_tree_after_value_taking_option_blocks(
    hook: types.ModuleType, patch_dir: Path, option: str, prefix: str
) -> None:
    """A value-taking global option before the subcommand never hides the tree."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    p = (patch_dir / "wt.patch").as_posix()
    for template in _VALUE_OPTION_COMMANDS:
        _assert_patch_blocks(hook, template.format(option=option, prefix=prefix, p=p))


@requires_posix_paths
@pytest.mark.parametrize("option", _COVERED_VALUE_OPTIONS)
@pytest.mark.parametrize("prefix", ["-C docs", "--work-tree=docs"])
def test_git_apply_work_tree_after_value_taking_option_allows(
    hook: types.ModuleType, patch_dir: Path, option: str, prefix: str
) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    p = (patch_dir / "wt.patch").as_posix()
    for template in _VALUE_OPTION_COMMANDS:
        _assert_patch_allows(hook, template.format(option=option, prefix=prefix, p=p))


def test_git_apply_value_option_list_is_covered(hook: types.ModuleType) -> None:
    """Every value-taking global option has a case above or in its own test."""
    own_tests = {"-C", "-c", "--work-tree", "--git-dir", "--config-env", "--list-cmds"}
    assert sorted(hook._GIT_GLOBAL_OPTS_WITH_VALUE - own_tests) == _COVERED_VALUE_OPTIONS


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (_unified("src/a.py"), {"a/src/a.py", "b/src/a.py"}),
        (
            b"diff --git a/x b/y\nsimilarity index 100%\nrename from x\nrename to y\n",
            {"x", "y", "a/x", "b/y"},
        ),
        (b"diff --git a/.bashrc b/.bashrc\nGIT binary patch\nliteral 0\n", {"a/.bashrc"}),
        (b"diff --git a/f b/f\nold mode 100644\nnew mode 100755\n", {"a/f", "b/f"}),
        (b"*** old/f.txt\t2020-01-01\n--- new/f.txt\n", {"old/f.txt", "new/f.txt"}),
        (b"Index: sub/f.txt\n====\n", {"sub/f.txt"}),
        (b"+++ b/f.txt\t2020-01-01 00:00:00\n", {"b/f.txt"}),
        (b'+++ "b/\\303\\251.txt"\n', {"b/\u00e9.txt"}),
        (b'+++ "b/bad\\q.txt"\n', None),
        (b'+++ "unterminated\n', None),
        (b"", None),
        (b"1,3c\nfoo\n.\nw\nq\n", None),
    ],
)
def test_patch_header_paths(hook: types.ModuleType, data: bytes, expected: set[str] | None) -> None:
    paths = hook._patch_header_paths(data)
    if expected is None:
        assert paths is None
    else:
        assert paths is not None
        assert expected <= set(paths)


def test_unquote_c_path(hook: types.ModuleType) -> None:
    assert hook._unquote_c_path("plain") == "plain"
    assert hook._unquote_c_path('"a\\tb"') == "a\tb"
    assert hook._unquote_c_path('"a\\12"') is None
    assert hook._unquote_c_path('"a"b"') is None
    assert hook._unquote_c_path('"a\\"') is None


def test_read_patch_paths_rejects_what_it_cannot_trust(
    hook: types.ModuleType, patch_dir: Path
) -> None:
    import os

    if hasattr(os, "mkfifo"):  # POSIX only
        os.mkfifo(patch_dir / "pipe.patch")
        assert hook._read_patch_paths("pipe.patch", base_dir=None, mbox=False) is None
    (patch_dir / "dir.patch").mkdir()
    (patch_dir / "empty.patch").write_bytes(b"")
    assert hook._read_patch_paths("dir.patch", base_dir=None, mbox=False) is None
    assert hook._read_patch_paths("missing.patch", base_dir=None, mbox=False) is None
    assert hook._read_patch_paths("empty.patch", base_dir=None, mbox=False) is None
    assert hook._read_patch_paths("/dev/null", base_dir=None, mbox=False) is None
    assert hook._read_patch_paths("ok.patch", base_dir=None, mbox=False)
    assert hook._read_patch_paths("ok.patch", base_dir=str(patch_dir), mbox=False)


def test_read_patch_paths_size_limit(
    hook: types.ModuleType, patch_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hook, "_PATCH_READ_LIMIT", len(_unified("src/foo.py")) - 1)
    assert hook._read_patch_paths("ok.patch", base_dir=None, mbox=False) is None
    monkeypatch.setattr(hook, "_PATCH_READ_LIMIT", len(_unified("src/foo.py")))
    assert hook._read_patch_paths("ok.patch", base_dir=None, mbox=False)


@pytest.mark.parametrize("encoding", ["base64", "Quoted-Printable", "BASE64"])
def test_read_patch_paths_mbox_transfer_encoding(
    hook: types.ModuleType, patch_dir: Path, encoding: str
) -> None:
    body = f"From a\nContent-Transfer-Encoding: {encoding}\n\n".encode() + _unified("src/foo.py")
    (patch_dir / "enc.mbox").write_bytes(body)
    assert hook._read_patch_paths("enc.mbox", base_dir=None, mbox=True) is None
    assert hook._read_patch_paths("enc.mbox", base_dir=None, mbox=False)


@pytest.mark.parametrize(
    "command",
    [
        "bash <<EOF\ncat ~/.ne\\\ntrc\nEOF",
        "bash <<'EOF'\ncat ~/.ne\\\ntrc\nEOF",
        "sh <<-EOF\n\tcat ~/.n\\\n\\\netrc\nEOF",
        "bash <<-EOF\n\tcat ~/.ne\\\n\ttrc\nEOF",
        "bash <<-'EOF'\n\tcat ~/.ne\\\n\ttrc\nEOF",
    ],
)
def test_heredoc_continued_command_is_checked(hook: types.ModuleType, command: str) -> None:
    assert hook.check_command(command)[0]


@pytest.mark.parametrize(
    "command",
    [
        "git apply bad.patch",
        "git apply example.patch",
        "git apply fish.patch",
        "git apply -R bad.patch",
        "git apply -p0 bad.patch",
        "git apply -p1 bad.patch",
        "git apply -Rp1 bad.patch",
        "git apply --cached bad.patch",
        "git apply --index bad.patch",
        "git apply --3way bad.patch",
        "git apply --check --apply bad.patch",
        "git apply --stat --apply bad.patch",
        "git apply --check --no-check bad.patch",
        "git apply --directory=.config/fish bare.patch",
        "git apply --directory .config/fish bare.patch",
        "git apply --build-fake-ancestor=.envrc.local ok.patch",
        "git apply --check --build-fake-ancestor=.envrc.local ok.patch",
        "git apply < bad.patch",
        "git apply - < bad.patch",
        "git apply<bad.patch",
        "git apply ok.patch bad.patch",
        "sudo git apply bad.patch",
        "git apply bad.patch 2>/dev/null",
        "git apply --exclude x bad.patch",
    ],
)
def test_git_apply_blocks_protected_targets(
    hook: types.ModuleType, patch_dir: Path, command: str
) -> None:
    if command == "git apply<bad.patch":
        # glued: only the redirect-splitting passes see the subcommand
        for tokens, flags in _restore_token_lists(hook, command)[:2]:
            assert hook._bash_confirmed_write_targets(tokens, read_patch_files=True, **flags)
        assert hook.check_command(command)[0]
        return
    _assert_patch_blocks(hook, command)


@pytest.mark.parametrize(
    "command",
    [
        "git apply",
        "git apply -",
        "git apply < missing.patch",
        "git apply --unsafe-paths ok.patch",
        "git apply --unsafe-paths --no-unsafe-paths --unsafe-paths ok.patch",
        'git apply "$P"',
        "git apply *.patch",
        "git apply ok.patch <<EOF",
        "git apply missing.patch",
        "printf x > ok.patch && git apply ok.patch",
        "cd sub && git apply ok.patch",
        "git -C sub apply ok.patch",
        "env -C sub git apply ok.patch",
        "xargs git apply",
        "cat ok.patch | git apply",
        "git apply --apply --check --no-check",
    ],
)
def test_git_apply_unresolvable_is_blocked(
    hook: types.ModuleType, patch_dir: Path, command: str
) -> None:
    assert hook.check_command(command)[0], command


def test_git_apply_wrapped_payload_is_unresolvable(hook: types.ModuleType, patch_dir: Path) -> None:
    assert hook.check_command("bash -c 'git apply ok.patch'")[0]
    assert hook.check_command("git apply ok.patch") == (False, "")


def test_git_apply_after_cd_allows_absolute_path(hook: types.ModuleType, patch_dir: Path) -> None:
    # as_posix(): a shell reads the backslashes of a Windows path as escapes
    command = f"git apply {patch_dir.as_posix()}/ok.patch"
    _assert_patch_allows(hook, command)


def test_patch_not_read_for_multiline_command(hook: types.ModuleType, patch_dir: Path) -> None:
    assert hook.check_command("echo hi\ngit apply ok.patch")[0]


@pytest.mark.parametrize(
    "command",
    [
        "git apply ok.patch",
        "git apply < ok.patch",
        "git apply - < ok.patch",
        "git apply -p1 ok.patch",
        "git apply --unsafe-paths --no-unsafe-paths ok.patch",
        "git apply --check bad.patch",
        "git apply --stat bad.patch",
        "git apply --numstat bad.patch",
        "git apply --summary bad.patch",
        "git apply --stat --no-apply bad.patch",
        "git apply --check --unsafe-paths bad.patch",
        "git apply --check",
        "git apply --stat < nothing.patch",
        "git apply ok.patch 2>/dev/null",
    ],
)
def test_git_apply_allowed(hook: types.ModuleType, patch_dir: Path, command: str) -> None:
    _assert_patch_allows(hook, command)


@pytest.mark.parametrize(
    "command",
    [
        "git am bad.patch",
        "git am --3way bad.patch",
        "git am -3 -s bad.patch",
        "git am < bad.patch",
        "git am --continue",
        "git am --resolved",
        "git am -r",
        "git am --skip",
        "git am --retry",
        "git am",
        "git am enc.mbox",
        "git am maildir",
    ],
)
def test_git_am_blocks(hook: types.ModuleType, patch_dir: Path, command: str) -> None:
    body = b"From a\nContent-Transfer-Encoding: base64\n\n" + _unified("src/foo.py")
    (patch_dir / "enc.mbox").write_bytes(body)
    (patch_dir / "maildir").mkdir()
    for targets in _patch_targets(hook, command):
        assert any(hook._matches_env_persistence_target(t, dynamic=True) for t in targets), command
    assert hook.check_command(command)[0], command


@pytest.mark.parametrize(
    "command",
    [
        "git am --abort",
        "git am --quit",
        "git am --show-current-patch",
        "git am --show-current-patch=diff",
        "git am ok.patch",
        "git am -3 ok.patch",
        "git am --directory=src ok.patch",
    ],
)
def test_git_am_allowed(hook: types.ModuleType, patch_dir: Path, command: str) -> None:
    _assert_patch_allows(hook, command)


@pytest.mark.parametrize(
    "command",
    [
        "patch .envrc.local fix.patch",
        "patch -p1 .bashrc",
        "patch -o .bashrc a b",
        "patch --output=.envrc.local a b",
        "patch --output .envrc a b",
        "patch --dry-run -o .envrc.local a b",
        "patch -r .envrc x y",
        "patch --reject-file=.envrc x y",
        "patch -p1 < bad.patch",
        "patch -p1 <bad.patch",
        "patch -i bad.patch",
        "patch --input=bad.patch",
        "patch -ibad.patch",
        "patch -d . -i bad.patch",
        "patch -d sub -i ../bad.patch",
        "patch -p1",
        "patch",
        "patch -b -z .local -p1 < ok.patch",
        "patch -B x -p1 < ok.patch",
        "patch -Y x -p1 < ok.patch",
        "patch --suffix=.x -p1 < ok.patch",
        "patch .envrc.loca? fix.patch",
        "sudo patch -p1 < bad.patch",
        "timeout 5 patch -p1 < bad.patch",
        "env X=1 patch -p1 < bad.patch",
        "xargs patch -p1",
        "cat bad.patch | patch -p1",
        "patch -p1 < ok.patch && echo done; patch -p1 < bad.patch",
        "patch -p1 -i bad.patch 2>/dev/null",
    ],
)
def test_patch_command_blocks(hook: types.ModuleType, patch_dir: Path, command: str) -> None:
    (patch_dir / "sub").mkdir(exist_ok=True)
    if command in {"patch -p1 <bad.patch"}:
        for tokens, flags in _restore_token_lists(hook, command)[:2]:
            assert hook._bash_confirmed_write_targets(tokens, read_patch_files=True, **flags)
        assert hook.check_command(command)[0]
        return
    if "&&" in command:
        assert hook.check_command(command)[0]
        return
    _assert_patch_blocks(hook, command)


@pytest.mark.parametrize(
    "command",
    [
        "patch src/a.py fix.patch",
        "patch -o out.py src/a.py fix.patch",
        "patch -o - src/a.py fix.patch",
        "patch --dry-run -p1 < x.patch",
        "patch --dry-run -p1",
        "patch -s --dry-run src/a.py",
        "patch -p1 < ok.patch",
        "patch -Np1 -i ok.patch",
        "patch -p 1 -i ok.patch",
        "patch -p1 < ok.patch 2>/dev/null",
        "patch --version",
        "patch --help",
        "patch -v",
        "echo the patch is ready",
    ],
)
def test_patch_command_allowed(hook: types.ModuleType, patch_dir: Path, command: str) -> None:
    _assert_patch_allows(hook, command)


def test_patch_without_read_permission_uses_stand_in(
    hook: types.ModuleType, patch_dir: Path
) -> None:
    for command in ("git apply ok.patch", "patch -p1 < ok.patch", "git am ok.patch"):
        for targets in _patch_targets(hook, command, read=False):
            assert targets == [_PATCH_STAND_IN], command


def test_patch_command_separator_ends_the_scan(hook: types.ModuleType, patch_dir: Path) -> None:
    for command in ("git apply ok.patch; echo bad.patch", "patch -p1 < ok.patch && echo x"):
        _assert_patch_allows(hook, command)


def test_patch_glued_separators_do_not_hide_a_target(
    hook: types.ModuleType, patch_dir: Path
) -> None:
    for command in ("true;git apply bad.patch", "x&&patch -p1 <bad.patch;", "true;patch -p1"):
        assert hook.check_command(command)[0], command


def test_patch_reader_is_not_used_in_nested_payload(
    hook: types.ModuleType, patch_dir: Path
) -> None:
    assert hook.check_command("patch -p1 < ok.patch", _depth=1)[0]
    assert not hook.check_command("patch -p1 < ok.patch", _depth=0)[0]


def test_patch_naming_ai_cli_settings_is_a_target_without_blocking(
    hook: types.ModuleType, patch_dir: Path
) -> None:
    """Like `cp`, a settings file needs the literal variable name to block."""
    for targets in _patch_targets(hook, "git apply settings.patch"):
        assert "b/.claude/settings.json" in targets
    assert hook.check_command("git apply settings.patch") == (False, "")


@pytest.mark.parametrize(
    "header",
    [
        "+++ b/.bashrc 2024-01-01 00:00:00.000000000 +0000",
        "--- a/.bashrc  extra",
        "*** .bashrc Mon Jan  1 00:00:00 2024",
    ],
)
def test_patch_header_paths_split_at_a_blank(hook: types.ModuleType, header: str) -> None:
    paths = hook._patch_header_paths((header + "\n").encode())
    assert paths is not None
    assert any(hook._is_env_persistence_target(p) for p in paths)


@pytest.mark.parametrize(
    "headers",
    [
        "Content-Transfer-Encoding: base64",
        "content-transfer-encoding:BASE64",
        "Content-Transfer-Encoding:\n base64",
        "Content-Transfer-Encoding: 7bit\n base64",
        "Content-Transfer-Encoding: x-uuencode",
        'Content-Type: multipart/mixed; boundary="b"',
    ],
)
def test_read_patch_paths_mbox_decoded_bodies_are_unresolvable(
    hook: types.ModuleType, patch_dir: Path, headers: str
) -> None:
    (patch_dir / "m.mbox").write_bytes(f"From a\n{headers}\n\n".encode() + _unified("src/foo.py"))
    assert hook._read_patch_paths("m.mbox", base_dir=None, mbox=True) is None


@pytest.mark.parametrize(
    "headers", ["Content-Transfer-Encoding: 8bit", "Content-Transfer-Encoding: 7bit"]
)
def test_read_patch_paths_mbox_plain_encodings_are_read(
    hook: types.ModuleType, patch_dir: Path, headers: str
) -> None:
    (patch_dir / "m.mbox").write_bytes(f"From a\n{headers}\n\n".encode() + _unified("src/foo.py"))
    assert hook._read_patch_paths("m.mbox", base_dir=None, mbox=True)


@pytest.mark.parametrize(
    "command",
    [
        "SIMPLE_BACKUP_SUFFIX=.local patch -b -p1 -i ok.patch",
        "env VERSION_CONTROL=simple patch -p1 -i ok.patch",
        "PATCH_VERSION_CONTROL=t patch -p1 < ok.patch",
    ],
)
def test_patch_backup_naming_from_the_environment_is_unresolvable(
    hook: types.ModuleType, patch_dir: Path, command: str
) -> None:
    for targets in _patch_targets(hook, command):
        assert _PATCH_STAND_IN in targets
    assert hook.check_command(command)[0]


@pytest.mark.parametrize(
    "name", ["SIMPLE_BACKUP_SUFFIX", "VERSION_CONTROL", "PATCH_VERSION_CONTROL"]
)
def test_patch_backup_naming_inherited_by_the_hook_is_unresolvable(
    hook: types.ModuleType, patch_dir: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, ".local")
    assert hook.check_command("patch -p1 -i ok.patch")[0]
    monkeypatch.delenv(name)
    assert not hook.check_command("patch -p1 -i ok.patch")[0]


# --- command word normalised once (#1132) ---

_QUALIFIED_RULES = [
    "git push --force origin main",
    "git push origin HEAD:main",
    "git push origin --delete main",
    "git branch -D main",
    "gh pr create --title x",
    "gh pr merge 1",
    "gh issue create --title x",
    "uv add requests",
    "doit release",
    "gh pr edit 1 --add-label ready-to-merge",
    "git merge feature/x",
    "printenv",
    "env",
    "cat ~/.netrc",
    "sudo rm file",
    "rm -rf /",
    "git apply bad.patch",
    "git am bad.patch",
    "patch -p1 -i bad.patch",
    "git checkout -- .envrc.local.example",
    'bash -c "gh pr merge 1"',
]


def _qualify(command: str, hook: types.ModuleType) -> str:
    """Rewrite each rule-keyed command word in *command* to a path-qualified form."""
    out = []
    for word in command.split(" "):
        if word in hook._RULE_COMMAND_WORDS:
            word = f"/usr/bin/{word}"
        out.append(word)
    return " ".join(out)


@pytest.mark.parametrize("command", _QUALIFIED_RULES)
def test_path_qualified_command_word_gets_the_bare_result(
    hook: types.ModuleType,
    patch_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setattr(hook, "get_current_branch", lambda: "main")
    monkeypatch.delenv("ALLOW_AI_READY_TO_MERGE", raising=False)
    qualified = _qualify(command, hook)
    assert qualified != command
    assert hook.check_command(command)[0], command
    assert hook.check_command(qualified) == hook.check_command(command)


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["/usr/bin/git", "status"], ["git", "status"]),
        (["true", "&&", "./bin/gh", "pr"], ["true", "&&", "gh", "pr"]),
        (["FOO=1", "/usr/bin/git", "push"], ["FOO=1", "git", "push"]),
        (["sudo", "-n", "/usr/bin/rm", "x"], ["sudo", "-n", "rm", "x"]),
        (["timeout", "5", "/usr/bin/git"], ["timeout", "5", "git"]),
        (["then", "/usr/bin/git"], ["then", "git"]),
        # Not command words, options and redirects.
        (["cat", "src/foo.py", "/opt/tool"], ["cat", "src/foo.py", "/opt/tool"]),
        (
            ["cat", "--x=/usr/bin/git", ">/usr/bin/git"],
            ["cat", "--x=/usr/bin/git", ">/usr/bin/git"],
        ),
    ],
)
def test_normalise_command_words_reduces_rule_words(
    hook: types.ModuleType, tokens: list[str], expected: list[str]
) -> None:
    assert hook._normalise_command_words(tokens) == expected


@pytest.mark.parametrize(
    "prefix",
    [
        "if true; then ",
        "! ",
        "{ ",
        "( ",
        "$( ",
        "nohup ",
        "time ",
        "exec ",
        "xargs ",
        "doas ",
        "stdbuf -o0 ",
        "timeout 5 ",
        "timeout -s KILL 5 ",
        "true\n",
        "echo x > out; ",
    ],
)
def test_path_qualified_rule_word_after_a_keyword_or_wrapper_is_blocked(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    monkeypatch.setattr(hook, "get_current_branch", lambda: "main")
    for rule in ("git push origin main", "gh pr merge 1"):
        bare = f"{prefix}{rule}"
        assert hook.check_command(bare)[0], bare
        qualified = bare.replace(rule.split()[0], f"/usr/bin/{rule.split()[0]}", 1)
        assert hook.check_command(qualified)[0], qualified


def test_operand_path_ending_in_a_command_word_keeps_its_path(
    hook: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A patch file or write target named like a command is still that path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "git").write_bytes(_unified("src/foo.py"))
    (tmp_path / "dir" / "patch").write_bytes(_unified(".bashrc"))
    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    # A harmless patch file named `git` is read from dir/git, not from `git`.
    assert hook.check_command("patch -p1 -i dir/git") == (False, "")
    assert hook.check_command("git apply dir/git") == (False, "")
    # A protected patch file named `patch` is still read from dir/patch.
    assert hook.check_command("patch -p1 -i dir/patch")[0]
    assert hook.check_command("git apply dir/patch")[0]
    # A redirect target named like a command is not rewritten.
    assert hook.check_command("echo x > dir/git") == (False, "")
    assert hook.check_command("cat dir/git") == (False, "")


@pytest.mark.parametrize(
    "command", ["/usr/bin/git status", "/usr/bin/gh pr view 1", "/bin/cat README.md"]
)
def test_path_qualified_safe_commands_stay_allowed(
    hook: types.ModuleType, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setattr(hook, "get_current_branch", lambda: "feature/test")
    assert hook.check_command(command) == (False, "")


@pytest.mark.parametrize(
    "template",
    [
        "cd x; git -C /abs --work-tree=rel apply {p}",
        "cd x; git --work-tree=rel -C /abs apply {p}",
        "cd x; git --work-tree=/abs -C rel apply {p}",
        "cd x; git -C rel --work-tree=/abs apply {p}",
        "env -C x git -C rel --work-tree=rel2 apply {p}",
        "cd x; GIT_WORK_TREE=/abs git -C rel apply {p}",
        "cd x; GIT_WORK_TREE=rel git -C /abs apply {p}",
        "cd x; git --work-tree=~/rel apply {p}",
    ],
)
def test_git_apply_moved_cwd_relative_final_root_blocks(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    """The final root decides, not an earlier absolute option (#1133)."""
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    command = template.format(p=(patch_dir / "wt.patch").as_posix())
    assert _wt_targets(hook, command) == [_PATCH_STAND_IN], command


@requires_posix_paths
@pytest.mark.parametrize(
    "template",
    [
        "env -C x git -C rel --work-tree=/abs/docs apply {p}",
        "env -C x git --work-tree=rel -C /abs/docs apply {p}",
        "env -C x git -C /abs --work-tree=docs apply {p}",
        "env -C x git --work-tree=docs -C /abs apply {p}",
    ],
)
def test_git_apply_moved_cwd_absolute_final_root_allows(
    hook: types.ModuleType, patch_dir: Path, template: str
) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    _assert_patch_allows(hook, template.format(p=(patch_dir / "wt.patch").as_posix()))


@pytest.mark.parametrize(
    "command",
    [
        "sudo -D x git apply {p}",
        "sudo --chdir=x git apply {p}",
        "nsenter -w x git apply {p}",
        "unshare --wd=x git apply {p}",
        "chroot x git apply {p}",
        "env -i git apply {p}",
        "doas -u u git apply {p}",
    ],
)
def test_wrapper_options_may_move_cwd(hook: types.ModuleType, command: str) -> None:
    tokens = hook.tokenize(command.format(p="x.patch"))
    assert hook._cwd_moved(tokens, tokens.index("git")) is True


@pytest.mark.parametrize(
    "command", ["sudo git apply {p}", "env VAR=1 git apply {p}", "git apply {p}"]
)
def test_bare_wrapper_does_not_move_cwd(hook: types.ModuleType, command: str) -> None:
    tokens = hook.tokenize(command.format(p="x.patch"))
    assert hook._cwd_moved(tokens, tokens.index("git")) is False


@pytest.mark.parametrize("command", ["sudo -D x git apply {p}", "env -i git apply {p}"])
def test_wrapper_options_make_patch_target_unresolvable(
    hook: types.ModuleType, patch_dir: Path, command: str
) -> None:
    (patch_dir / "wt.patch").write_bytes(_unified("config.fish"))
    p = (patch_dir / "wt.patch").as_posix()
    assert _wt_targets(hook, command.format(p=p)) == [_PATCH_STAND_IN]


@pytest.mark.parametrize("operator", ["'>'", "'>>'", '">"', "\\>", "$'>'"])
@pytest.mark.parametrize(
    "prefix",
    [
        "git restore --source=HEAD~1",
        "git restore -s HEAD~1",
        "git checkout HEAD~1 --",
        "git checkout HEAD~1",
    ],
)
def test_quoted_operator_word_does_not_swallow_broad_pathspec(
    hook: types.ModuleType, prefix: str, operator: str
) -> None:
    # the tokens lost the quoting, so a quoted `>` read as a redirect hid the `.` (#1134)
    assert hook.check_command(f"{prefix} {operator} .")[0] is True


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        ("git restore --source=HEAD~1 . > out", True),
        ("git checkout . > /dev/null", False),
        ("git restore . > out", False),
        ("git restore --source=HEAD~1 f.txt > out.txt", False),
    ],
)
def test_unquoted_redirects_keep_their_behaviour(
    hook: types.ModuleType, command: str, blocked: bool
) -> None:
    assert hook.check_command(command)[0] is blocked


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git restore '>' .", True),
        ('git restore ">>" .', True),
        ("git restore \\> .", True),
        ("git restore > out", False),
        ("git restore 'a>' .", False),
        ("git restore . ; echo", False),
        ("echo 'unclosed", False),
    ],
)
def test_has_quoted_redirect_word(hook: types.ModuleType, command: str, expected: bool) -> None:
    assert hook._has_quoted_redirect_word(command) is expected


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["if", "true", ";", "then", "printenv", ";", "fi"], [0, 1, 3, 4, 6]),
        (["!", "printenv"], [0, 1]),
        (["time", "-p", "env"], [0, 1, 2]),
        (["while", "true", ";", "do", "env", ";", "done"], [0, 1, 3, 4, 6]),
        (["echo", "then", "printenv"], [0]),
        (["echo", "if", "x"], [0]),
    ],
)
def test_command_start_indices_follow_keywords(
    hook: types.ModuleType, tokens: list[str], expected: list[int]
) -> None:
    """A reserved word at a command start makes the next token a start."""
    assert hook._command_start_indices(tokens) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("x=$(printenv)", ["printenv"]),
        ("x=`printenv`", ["printenv"]),
        ('echo "$(printenv) $(env)"', ["printenv", "env"]),
        ("diff <(a) >(b)", ["a", "b"]),
        ("(printenv)", ["printenv"]),
        ("true && (env)", ["env"]),
        ("x=$(echo $(printenv))", ["echo $(printenv)"]),
        ("echo '$(printenv)'", []),
        ("echo $'$(printenv)'", []),
        ('echo "\\$(printenv)"', []),
        ("echo $((1 + 2))", []),
        ("arr=(printenv)", []),
        ("f() { :; }", []),
        ("echo $(printenv", []),
        ("x=$(a) $(b", ["a"]),
        ("then(a)", ["a"]),
        ("do(a)", ["a"]),
        ("else(a)", ["a"]),
        ("{(a); }", ["a"]),
        ("!(a)", ["a"]),
        ("f(){ :; }", []),
        ("x+=(a)", []),
        ("x=(a)", []),
        ("x=$(cat <<EOF\nEOF\n) $(b)", ["b"]),
        ("echo \"$(cat <<'EOF'\nbody $(a)\nEOF\n)\" $(b)", ["b"]),
        ("cat <<EOF\nv $(a) `b`\nEOF", ["a", "b"]),
        ("cat <<'EOF'\nv $(a)\nEOF", []),
        ("cat <<-EOF\n\tv $(a)\n\tEOF\n$(b)", ["a", "b"]),
        ("cat <<EOF\nv \\$(a)\nEOF", []),
        ("cat <<< $(a)", ["a"]),
    ],
)
def test_substitution_payloads(hook: types.ModuleType, command: str, expected: list[str]) -> None:
    """Bodies of substitutions and subshells are returned; quoted text is not."""
    assert hook._substitution_payloads(command) == expected


def test_all_substitution_payloads_follows_nesting(hook: types.ModuleType) -> None:
    """Nested bodies are all returned, whatever the depth."""
    command = "echo $(a $(b $(c $(d $(e)))))"
    assert hook._all_substitution_payloads(command) == [
        "a $(b $(c $(d $(e))))",
        "b $(c $(d $(e)))",
        "c $(d $(e))",
        "d $(e)",
        "e",
    ]


def test_all_substitution_payloads_reads_unquoted_heredoc_bodies(hook: types.ModuleType) -> None:
    """An unquoted-delimiter heredoc body is read; a quoted one is not."""
    assert hook._all_substitution_payloads("cat <<EOF\n$(a $(b))\nEOF") == ["a $(b)", "b"]
    assert hook._all_substitution_payloads("cat <<'EOF'\n$(a)\nEOF") == []


def test_all_substitution_payloads_gives_up_past_the_limit(hook: types.ModuleType) -> None:
    """Too many bodies are reported as unreadable, and the command is blocked."""
    command = " ".join(f"$(x{n})" for n in range(hook._MAX_SUBSTITUTION_PAYLOADS + 1))
    assert hook._all_substitution_payloads(command) is None
    is_dangerous, reason = hook.check_command(command)
    assert is_dangerous
    assert "too deeply" in reason
