from __future__ import annotations

import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MIN_CLAUDE_VERSION = (2, 1, 219)
MODEL_FLOORS = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}
DEFAULT_ALLOWED_COMMANDS = (
    "git status",
    "git diff",
    "git log",
    "git show",
)
FORBIDDEN_GIT_SUBCOMMANDS = {
    "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "commit", "merge",
    "mv", "pull", "push", "rebase", "reset", "restore", "revert", "rm", "stash", "switch", "tag",
}
ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "log", "show"}
FORBIDDEN_SHELL = re.compile(r"[;&|`$<>{}\n\r]")
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")
MODEL_PATTERN = re.compile(r"^claude-(opus|sonnet|haiku)-(\d+)(?:-(\d+))?(?:-|$)")


@dataclass(frozen=True)
class ClaudeProfile:
    role: str
    model: str
    minimum_model: str
    pin_model: bool = False
    effort: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "minimum_model": self.minimum_model,
            "pin_model": self.pin_model,
            "effort": self.effort,
        }


DEFAULT_PROFILES = {
    "review": ClaudeProfile("review", "sonnet", MODEL_FLOORS["sonnet"], effort="medium"),
    "second_opinion": ClaudeProfile("second_opinion", "opus", MODEL_FLOORS["opus"], effort="medium"),
    "summarize": ClaudeProfile("summarize", "haiku", MODEL_FLOORS["haiku"]),
}


@dataclass(frozen=True)
class ClaudePolicy:
    roles: dict[str, ClaudeProfile] | None = None
    allowed_commands: tuple[str, ...] = DEFAULT_ALLOWED_COMMANDS

    def __post_init__(self) -> None:
        if self.roles is None:
            object.__setattr__(self, "roles", dict(DEFAULT_PROFILES))

    @property
    def model(self) -> str:
        return self.roles["review"].model

    @property
    def minimum_model(self) -> str:
        return self.roles["review"].minimum_model

    @property
    def pin_model(self) -> bool:
        return self.roles["review"].pin_model

    def profile(self, role: str) -> ClaudeProfile:
        return self.roles[role]

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles": {name: profile.to_dict() for name, profile in self.roles.items()},
            "allowed_commands": list(self.allowed_commands),
        }

    def allowed_tools(self) -> list[str]:
        return ["Read", "Glob", "Grep", *(f"Bash({command}:*)" for command in self.allowed_commands)]


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.search(value)
    if not match:
        raise ValueError(f"could not parse Claude Code version: {value!r}")
    return tuple(int(part) for part in match.groups())


def format_version(value: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def validate_command(command: str) -> str:
    command = command.strip()
    if not command or FORBIDDEN_SHELL.search(command):
        raise ValueError(f"unsafe Claude command rule: {command!r}")
    arguments = shlex.split(command)
    if not arguments or any("=" in argument for argument in arguments[:1]):
        raise ValueError(f"environment assignments are not allowed: {command!r}")
    executable = arguments[0]
    if "/" in executable or executable in {"bash", "sh", "zsh", "env", "xargs", "sudo"}:
        raise ValueError(f"shells and path-qualified executables are not allowed: {command!r}")
    if executable == "git" and len(arguments) > 1 and arguments[1] in FORBIDDEN_GIT_SUBCOMMANDS:
        raise ValueError(f"write-capable Git command is not allowed: {command!r}")
    if executable == "git" and (len(arguments) < 2 or arguments[1] not in ALLOWED_GIT_SUBCOMMANDS):
        raise ValueError(f"only narrow Git inspection commands are allowed: {command!r}")
    return " ".join(arguments)


def _minimum_for(model: str) -> str:
    if model in MODEL_FLOORS:
        return MODEL_FLOORS[model]
    if model.startswith("claude-"):
        raise ValueError("full model IDs require pin_model=true")
    raise ValueError(f"unsupported Claude model alias: {model!r}")


def _profile(role: str, configured: dict[str, Any]) -> ClaudeProfile:
    default = DEFAULT_PROFILES[role]
    model = str(configured.get("model", default.model))
    pin_model = bool(configured.get("pin_model", False))
    if model.startswith("claude-") and not pin_model:
        raise ValueError("full model IDs require pin_model=true")
    if pin_model and not model.startswith("claude-"):
        raise ValueError("pin_model=true requires a full claude-* model ID")
    minimum = str(configured.get("minimum_model") or (model if pin_model else _minimum_for(model)))
    effort = configured.get("effort", default.effort)
    if effort not in {None, "low", "medium", "high"}:
        raise ValueError(f"unsupported Claude effort: {effort!r}")
    return ClaudeProfile(role, model, minimum, pin_model, effort)


def load_policy(repository: str | Path, overrides: dict[str, Any] | None = None) -> ClaudePolicy:
    configured: dict[str, Any] = {}
    path = Path(repository).resolve() / ".until-useful.toml"
    if path.is_file():
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        configured = value.get("claude", {})
        if not isinstance(configured, dict):
            raise ValueError(".until-useful.toml [claude] must be a table")
    overrides = overrides or {}
    configured_roles = configured.get("roles", {})
    if configured_roles and not isinstance(configured_roles, dict):
        raise ValueError("claude.roles must be a table")
    global_values = {
        key: value for key, value in configured.items()
        if key in {"model", "minimum_model", "pin_model", "effort"}
    }
    global_override = {
        key: value for key, value in overrides.items()
        if key in {"model", "minimum_model", "pin_model", "effort"} and value is not None
    }
    if global_override.get("model") is not None and "minimum_model" not in global_override:
        global_values.pop("minimum_model", None)
    if global_override.get("model") is not None and "pin_model" not in global_override:
        global_values["pin_model"] = False
    global_values.update(global_override)
    role_overrides = overrides.get("roles", {}) or {}
    profiles: dict[str, ClaudeProfile] = {}
    for role in DEFAULT_PROFILES:
        values = dict(configured_roles.get(role, {}))
        values.update(global_values)
        selected_override = role_overrides.get(role, {})
        if selected_override.get("model") is not None and "minimum_model" not in selected_override:
            values.pop("minimum_model", None)
        if selected_override.get("model") is not None and "pin_model" not in selected_override:
            values["pin_model"] = False
        values.update(selected_override)
        profiles[role] = _profile(role, values)
    raw_commands = overrides.get("allowed_commands", configured.get("allowed_commands", list(DEFAULT_ALLOWED_COMMANDS)))
    if not isinstance(raw_commands, list) or not all(isinstance(item, str) for item in raw_commands):
        raise ValueError("claude.allowed_commands must be an array of strings")
    commands = tuple(dict.fromkeys(validate_command(item) for item in raw_commands))
    return ClaudePolicy(roles=profiles, allowed_commands=commands)


def model_satisfies(observed: str, policy: ClaudePolicy | ClaudeProfile) -> bool:
    if policy.pin_model:
        return observed == policy.model
    observed_match = MODEL_PATTERN.match(observed)
    minimum_match = MODEL_PATTERN.match(policy.minimum_model)
    if not observed_match or not minimum_match or observed_match.group(1) != minimum_match.group(1):
        return False
    observed_version = tuple(int(part or 0) for part in observed_match.groups()[1:])
    minimum_version = tuple(int(part or 0) for part in minimum_match.groups()[1:])
    return observed_version >= minimum_version


def select_observed_model(model_usage: Any, policy: ClaudePolicy | ClaudeProfile) -> tuple[str, list[str]]:
    reported = sorted(model_usage) if isinstance(model_usage, dict) else []
    satisfying = [model for model in reported if model_satisfies(model, policy)]
    return (satisfying[-1] if satisfying else ""), reported
