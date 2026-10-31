"""Doit task that resolves a cross-agent role to a subagent, an inline run, or a CLI command.

Cross-agent work (reviews, plan review, "implement issue N with <agent>", ``multi-*``) names a
*role*. Each person picks, per role, which CLI runs it and on which model, in a layered TOML
config kept outside the repo (user) or gitignored (project-local). :func:`task_agent_cmd` turns
a role plus the host the caller runs in into one JSON line a skill can act on, so skills never
parse the TOML or build CLI flags themselves. With no config the result is exactly the invocation
the skills used before roles existed.

See ``docs/development/ai/agent-roles.md`` and ADR-9030.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404  # subprocess runs the CLIs' zero-token model listers
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doit.tools import title_with_actions

REPO_ROOT = Path(__file__).resolve().parents[2]

ROLES: tuple[str, ...] = ("plan", "plan_review", "code", "review", "adversarial_review")

# Canonical CLI names. ``antigravity`` is accepted as an alias of ``agy``.
CLIS: tuple[str, ...] = ("claude", "codex", "copilot", "agy")
_CLI_ALIASES: dict[str, str] = {"antigravity": "agy"}

# Only these CLIs take a reasoning effort.
EFFORT_CLIS: frozenset[str] = frozenset({"codex", "copilot"})

# Model names the Claude Code Agent tool and ``claude --model`` accept as aliases.
CLAUDE_ALIASES: frozenset[str] = frozenset({"opus", "sonnet", "haiku", "fable"})

_CONFIG_KEYS: frozenset[str] = frozenset({"cli", "model", "effort"})

PROMPT_SLOT = "'<prompt>'"

# Today's non-interactive invocation per CLI. Mirrors the "Non-interactive flags per CLI"
# table in docs/development/ai/cross-agent-delegation.md; tests/test_cross_agent_contract.py
# keeps the two in step.
BASE_COMMANDS: dict[str, str] = {
    "claude": "claude -p '<prompt>'",
    "codex": "codex -a never --dangerously-bypass-hook-trust exec '<prompt>' < /dev/null",
    "copilot": "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS=true copilot --allow-all -p '<prompt>'",
    "agy": (
        "agy -p '<prompt>' --dangerously-skip-permissions "
        '--add-dir "$(git rev-parse --show-toplevel)"'
    ),
}

# The no-token command that lists the models each CLI accepts.
LISTER_COMMANDS: dict[str, list[str]] = {
    "agy": ["agy", "models"],
    "codex": ["codex", "debug", "models"],
    "copilot": ["copilot", "help", "config"],
}

USER_CONFIG_RELATIVE = Path("pyproject-template") / "agents.toml"
LOCAL_CONFIG_RELATIVE = Path(".config") / "pyproject_template" / "agents.local.toml"

LISTER_TIMEOUT_SECONDS = 60


class AgentConfigError(Exception):
    """Raised for an invalid agent-role config or an unusable argument."""


@dataclass(frozen=True)
class RoleConfig:
    """The resolved settings of one role after the config layers are merged."""

    cli: str
    model: str | None = None
    effort: str | None = None


Layer = dict[str, dict[str, str]]


def canonical_cli(name: str) -> str:
    """Return the canonical CLI name for *name*, accepting the ``antigravity`` alias.

    Raises:
        AgentConfigError: If *name* is not a known CLI.
    """
    lowered = name.strip().lower()
    canonical = _CLI_ALIASES.get(lowered, lowered)
    if canonical not in CLIS:
        raise AgentConfigError(f"unknown cli {name!r}; expected one of {', '.join(CLIS)}")
    return canonical


def user_config_path(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """Return the user-layer config path, honouring ``$XDG_CONFIG_HOME``."""
    env = os.environ if env is None else env
    xdg = env.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else (home if home is not None else Path.home()) / ".config"
    return base / USER_CONFIG_RELATIVE


def local_config_path(root: Path | None = None) -> Path:
    """Return the project-local (gitignored) config path under *root* (default: the repo)."""
    return (root if root is not None else REPO_ROOT) / LOCAL_CONFIG_RELATIVE


def _check_value(role: str, key: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentConfigError(f"roles.{role}.{key} must be a non-empty string")
    if value.startswith("-"):
        raise AgentConfigError(f"roles.{role}.{key} must not start with '-': {value!r}")
    return value.strip()


def parse_layer(text: str, source: str = "config") -> Layer:
    """Parse one TOML config layer into ``{role: {key: value}}``.

    Raises:
        AgentConfigError: On invalid TOML, an unknown table, role or key, or a bad value.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise AgentConfigError(f"{source}: invalid TOML: {e}") from e

    unknown_top = sorted(set(data) - {"roles"})
    if unknown_top:
        raise AgentConfigError(f"{source}: unknown top-level key(s): {', '.join(unknown_top)}")
    roles = data.get("roles", {})
    if not isinstance(roles, dict):
        raise AgentConfigError(f"{source}: 'roles' must be a table")

    layer: Layer = {}
    for role, table in roles.items():
        if role not in ROLES:
            raise AgentConfigError(
                f"{source}: unknown role {role!r}; expected one of {', '.join(ROLES)}"
            )
        if not isinstance(table, dict):
            raise AgentConfigError(f"{source}: roles.{role} must be a table")
        unknown = sorted(set(table) - _CONFIG_KEYS)
        if unknown:
            raise AgentConfigError(f"{source}: roles.{role}: unknown key(s): {', '.join(unknown)}")
        entry: dict[str, str] = {}
        for key, value in table.items():
            checked = _check_value(role, key, value)
            entry[key] = canonical_cli(checked) if key == "cli" else checked
        layer[role] = entry
    return layer


def merge_layers(user: Layer, local: Layer) -> Layer:
    """Merge the project-local layer over the user layer.

    Within a role the local layer overrides key by key, except that a local ``cli`` replaces the
    role wholesale: the user's model and effort belong to the user's CLI, not the local one.
    """
    merged: Layer = {role: dict(entry) for role, entry in user.items()}
    for role, entry in local.items():
        if "cli" in entry:
            merged[role] = dict(entry)
        else:
            merged.setdefault(role, {}).update(entry)
    return merged


def _to_role_configs(merged: Layer) -> dict[str, RoleConfig]:
    configs: dict[str, RoleConfig] = {}
    for role, entry in merged.items():
        cli = entry.get("cli")
        if cli is None:
            raise AgentConfigError(f"roles.{role} has no cli")
        effort = entry.get("effort")
        if effort is not None and cli not in EFFORT_CLIS:
            raise AgentConfigError(
                f"roles.{role}: effort is not supported for cli {cli!r} "
                f"(only {', '.join(sorted(EFFORT_CLIS))}); put it in the model name"
            )
        configs[role] = RoleConfig(cli=cli, model=entry.get("model"), effort=effort)
    return configs


def _read_layer(path: Path) -> Layer:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise AgentConfigError(f"{path}: cannot read: {e}") from e
    return parse_layer(text, str(path))


def load_role_configs(
    user_path: Path | None = None, local_path: Path | None = None
) -> dict[str, RoleConfig]:
    """Load, merge and validate both layers. A missing file is an empty layer."""
    user = _read_layer(user_path if user_path is not None else user_config_path())
    local = _read_layer(local_path if local_path is not None else local_config_path())
    return _to_role_configs(merge_layers(user, local))


def build_command(cli: str, model: str | None = None, effort: str | None = None) -> str:
    """Return the non-interactive shell command for *cli*, with the ``'<prompt>'`` slot.

    With no model and no effort this is exactly today's invocation. Values are shell-quoted.
    """
    cli = canonical_cli(cli)
    base = BASE_COMMANDS[cli]
    flags: list[str] = []
    if cli == "codex":
        if model:
            flags += ["-m", shlex.quote(model)]
        if effort:
            flags += ["-c", shlex.quote(f"model_reasoning_effort={effort}")]
    else:
        if model:
            flags += ["--model", shlex.quote(model)]
        if effort:
            flags += ["--reasoning-effort", shlex.quote(effort)]
    if not flags:
        return base
    joined = " ".join(flags)
    if cli == "codex":
        # Codex options belong to ``exec``, before the prompt.
        return base.replace(PROMPT_SLOT, f"{joined} {PROMPT_SLOT}")
    return f"{base} {joined}"


def resolve(
    role: str,
    host: str,
    configs: Mapping[str, RoleConfig],
    cli: str | None = None,
) -> dict[str, str]:
    """Resolve *role* for *host* to a ``subagent``, ``inline`` or ``cli`` result.

    Args:
        role: One of :data:`ROLES`.
        host: The CLI the caller runs in.
        configs: The merged role configs.
        cli: Optional target CLI that overrides the role's own (used by bridges that always
            reach one specific CLI). Role model and effort apply only when the role's CLI is
            the target.

    Raises:
        AgentConfigError: On an unknown role, host or cli.
    """
    if role not in ROLES:
        raise AgentConfigError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    host_cli = canonical_cli(host)
    config = configs.get(role)

    if cli:
        target = canonical_cli(cli)
    elif config is not None:
        target = config.cli
    else:
        target = host_cli

    model = effort = None
    if config is not None and config.cli == target:
        model, effort = config.model, config.effort

    if target == host_cli == "codex":
        # Codex `spawn_agent` takes `model` and `reasoning_effort` when spawned with
        # `fork_turns: "none"`; verified live in Codex CLI 0.166.0 (#1151).
        result = {"mode": "subagent"}
        if model:
            result["model"] = model
        if effort:
            result["effort"] = effort
        return result

    if target == host_cli and effort is None:
        if host_cli == "claude" and (model is None or model in CLAUDE_ALIASES):
            return {"mode": "subagent", "model": model} if model else {"mode": "subagent"}
        # Copilot's `task` tool does not honour a chosen model: its `model` schema allowed only
        # `auto` (#1151), so a configured model resolves to cli. agy has no subagent mechanism.
        if model is None:
            return {"mode": "inline" if host_cli == "agy" else "subagent"}

    return {"mode": "cli", "cli": target, "command": build_command(target, model, effort)}


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
Which = Callable[[str], str | None]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=LISTER_TIMEOUT_SECONDS,
    )


def _models_agy(output: str) -> set[str]:
    return {line.split()[0] for line in output.splitlines() if line.strip() and "\t" in line}


def _models_codex(output: str) -> set[str]:
    data = json.loads(output)
    return {str(m["slug"]) for m in data["models"]}


def _models_copilot(output: str) -> set[str]:
    models: set[str] = set()
    in_block = False
    for line in output.splitlines():
        if re.match(r"^\s+`model`:", line):
            in_block = True
            continue
        if in_block:
            match = re.match(r'^\s+- "([^"]+)"\s*$', line)
            if match:
                models.add(match.group(1))
            else:
                break
    return models


_PARSERS: dict[str, Callable[[str], set[str]]] = {
    "agy": _models_agy,
    "codex": _models_codex,
    "copilot": _models_copilot,
}


def check_models(
    configs: Mapping[str, RoleConfig],
    runner: Runner = _default_runner,
    which: Which = shutil.which,
) -> tuple[list[str], list[str]]:
    """Validate every configured model against its CLI's own model list.

    Each model must equal an entry of the lister's output (a prefix is not enough). Each CLI's
    lister runs once. Claude models are not listed anywhere: the aliases pass, others are noted.

    Returns:
        ``(errors, notes)``.
    """
    errors: list[str] = []
    notes: list[str] = []
    wanted: dict[str, list[tuple[str, str]]] = {}
    for role, config in configs.items():
        if config.model is None:
            continue
        if config.cli == "claude":
            if config.model not in CLAUDE_ALIASES:
                notes.append(f"roles.{role}: claude model {config.model!r} is unchecked")
            continue
        wanted.setdefault(config.cli, []).append((role, config.model))

    for cli, entries in wanted.items():
        if which(cli) is None:
            errors.append(f"{cli} is not installed, so its models cannot be checked")
            continue
        try:
            result = runner(LISTER_COMMANDS[cli])
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"{' '.join(LISTER_COMMANDS[cli])} failed: {e}")
            continue
        if result.returncode != 0:
            errors.append(
                f"{' '.join(LISTER_COMMANDS[cli])} exited {result.returncode}: "
                f"{(result.stderr or '').strip()}"
            )
            continue
        try:
            known = _PARSERS[cli](result.stdout)
        except (ValueError, KeyError, TypeError) as e:
            errors.append(f"cannot parse the {cli} model list: {e}")
            continue
        for role, model in entries:
            if model not in known:
                errors.append(
                    f"roles.{role}: {model!r} is not a {cli} model "
                    f"(see `{' '.join(LISTER_COMMANDS[cli])}`)"
                )
    return errors, notes


def _fail(message: str) -> None:
    print(f"agent_cmd: {message}", file=sys.stderr)
    sys.exit(1)


def task_agent_cmd() -> dict[str, Any]:
    """Resolve a cross-agent role to a subagent, an inline run, or a ready CLI command.

    Reads the user config (``$XDG_CONFIG_HOME/pyproject-template/agents.toml``, else
    ``~/.config/pyproject-template/agents.toml``) and the gitignored project-local
    ``.config/pyproject_template/agents.local.toml``, then prints one JSON line last on stdout:

    - ``{"mode": "subagent"}``, optionally with ``"model"`` (Claude alias or Codex model) and,
      on Codex, ``"effort"``: run the brief in the host's own subagent with those settings.
    - ``{"mode": "inline"}``: the host has no subagent mechanism and is the target; do the work
      in the session.
    - ``{"mode": "cli", "cli": "<name>", "command": "<shell string>"}``: run ``command`` after
      replacing the literal ``'<prompt>'`` with the quoted prompt.

    With no config the result is exactly today's invocation. Roles: plan, plan_review, code,
    review, adversarial_review. ``--cli`` fixes the target CLI (bridges); role model and
    effort apply only when the role's CLI is that target. ``--check`` validates the configured
    model names against each CLI's own list and exits 1 on any error. Errors go to stderr and
    exit 1.

    Examples:
        doit agent_cmd --role=code --host=claude
        doit agent_cmd --role=review --host=claude --cli=codex
        doit agent_cmd --check
    """

    def resolve_role(role: str = "", host: str = "", cli: str = "", check: bool = False) -> None:
        try:
            configs = load_role_configs()
            if check:
                errors, notes = check_models(configs)
                print(json.dumps({"ok": not errors, "errors": errors, "notes": notes}))
                if errors:
                    sys.exit(1)
                return
            if not role:
                _fail("--role is required")
            if not host:
                _fail("--host is required")
            print(json.dumps(resolve(role, host, configs, cli or None)))
        except AgentConfigError as e:
            _fail(str(e))

    return {
        "actions": [resolve_role],
        "params": [
            {
                "name": "role",
                "long": "role",
                "default": "",
                "help": f"Role: {', '.join(ROLES)}",
            },
            {
                "name": "host",
                "long": "host",
                "default": "",
                "help": "The CLI the caller runs in: claude, codex, copilot, agy (or antigravity)",
            },
            {
                "name": "cli",
                "long": "cli",
                "default": "",
                "help": "Fix the target CLI (bridges); role model/effort apply only if it matches",
            },
            {
                "name": "check",
                "long": "check",
                "type": bool,
                "default": False,
                "help": "Validate configured model names against each CLI's own list",
            },
        ],
        "title": title_with_actions,
        "verbosity": 2,
    }
