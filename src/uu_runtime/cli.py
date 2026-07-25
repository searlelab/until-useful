from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .database import Database, SCHEMA_VERSION, default_database_path
from .engine import Runtime, WorkflowError
from .reporting import render_report
from .policy import MIN_CLAUDE_VERSION, format_version, load_policy, select_observed_model, parse_version


def _read_json(source: str) -> dict[str, Any]:
    if source == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("input JSON must be an object")
    return value


def _emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _runtime(arguments: argparse.Namespace) -> Runtime:
    return Runtime(Database(arguments.database))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uu-runtime", description="Codex-orchestrated Until Useful Runtime")
    parser.add_argument("--database", default=str(default_database_path()), help="SQLite database path")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    start = subcommands.add_parser("start", help="register an approved Codex implementation")
    start.add_argument("--input", default="-", help="request JSON path or - for stdin")
    _add_model_arguments(start)

    register = subcommands.add_parser("register-plan", help="register an approved plan before implementation")
    register.add_argument("--input", default="-", help="request JSON path or - for stdin")
    _add_model_arguments(register)

    for name in ("next", "resume", "contexts"):
        command = subcommands.add_parser(name)
        command.add_argument("--task", required=True)

    status = subcommands.add_parser("status")
    status.add_argument("--task")
    status.add_argument("--repository", default=os.getcwd())

    record = subcommands.add_parser("record-codex-result")
    record.add_argument("--task", required=True)
    record.add_argument("--input", default="-", help="result JSON path or - for stdin")

    provide = subcommands.add_parser("provide-input")
    provide.add_argument("--task", required=True)
    provide.add_argument("--input", default="-", help="human guidance text path or - for stdin")

    resolution = subcommands.add_parser("record-input-resolution")
    resolution.add_argument("--task", required=True)
    resolution.add_argument("--input", default="-", help="resolution JSON path or - for stdin")

    report = subcommands.add_parser("report")
    report.add_argument("--task", required=True)
    report.add_argument("--persist", action="store_true")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")

    refresh = subcommands.add_parser("refresh-context")
    refresh.add_argument("--task", required=True)
    refresh.add_argument("--reason", required=True)

    stop = subcommands.add_parser("stop")
    stop.add_argument("--task", required=True)
    stop.add_argument("--reason", required=True)

    interrupted = subcommands.add_parser("recover-interrupted")
    interrupted.add_argument("--task", required=True)
    interrupted.add_argument("--reason", required=True)

    invalid = subcommands.add_parser("recover-invalid-output")
    invalid.add_argument("--task", required=True)
    _add_model_arguments(invalid)

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--repository", default=os.getcwd())
    doctor.add_argument("--live", action="store_true")
    doctor.add_argument("--timeout", type=float, default=30)
    _add_model_arguments(doctor)
    return parser


def _add_model_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--model", default=None)
    command.add_argument("--minimum-model", default=None)
    command.add_argument("--pin-model", action="store_true")
    command.add_argument("--effort", choices=("low", "medium", "high"), default=None)
    for role in ("review", "second-opinion", "summarize"):
        prefix = role.replace("-", "_")
        command.add_argument(f"--{role}-model", dest=f"{prefix}_model", default=None)
        command.add_argument(f"--{role}-minimum-model", dest=f"{prefix}_minimum_model", default=None)
        command.add_argument(f"--{role}-pin-model", dest=f"{prefix}_pin_model", action="store_true")
        command.add_argument(f"--{role}-effort", dest=f"{prefix}_effort", choices=("low", "medium", "high"), default=None)


def _model_payload(arguments: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    config = dict(payload.get("adapter_config", {}))
    if getattr(arguments, "model", None) is not None:
        config["model"] = arguments.model
    if getattr(arguments, "minimum_model", None) is not None:
        config["minimum_model"] = arguments.minimum_model
    if getattr(arguments, "pin_model", False):
        config["pin_model"] = True
    if getattr(arguments, "effort", None) is not None:
        config["effort"] = arguments.effort
    roles = dict(config.get("roles", {}))
    for cli_role, config_role in (("review", "review"), ("second_opinion", "second_opinion"), ("summarize", "summarize")):
        values = dict(roles.get(config_role, {}))
        for suffix in ("model", "minimum_model", "effort"):
            value = getattr(arguments, f"{cli_role}_{suffix}", None)
            if value is not None:
                values[suffix] = value
        if getattr(arguments, f"{cli_role}_pin_model", False):
            values["pin_model"] = True
        if values:
            roles[config_role] = values
    if roles:
        config["roles"] = roles
    return {**payload, "adapter_config": config}


def doctor(
    database_path: str, repository: str, *, live: bool = False, timeout: float = 30,
    model: str | None = None, minimum_model: str | None = None, pin_model: bool = False,
    adapter_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    database = Database(database_path)
    checks: list[dict[str, Any]] = []
    try:
        database.migrate()
        connection = database.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        finally:
            connection.close()
        checks.append({"name": "database", "ok": version == SCHEMA_VERSION, "detail": str(database.path)})
    except Exception as error:
        checks.append({"name": "database", "ok": False, "detail": str(error)})
    claude = shutil.which("claude")
    checks.append({"name": "claude", "ok": bool(claude), "detail": claude or "not found"})
    version = ""
    if claude:
        try:
            process = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=10, check=False)
            version = process.stdout.strip()
            current = parse_version(version)
            ok = process.returncode == 0 and current >= MIN_CLAUDE_VERSION
            detail = version if ok else f"{version}; run `claude update` (requires {format_version(MIN_CLAUDE_VERSION)}+)"
            checks.append({"name": "claude_version", "ok": ok, "detail": detail})
        except (subprocess.TimeoutExpired, ValueError) as error:
            checks.append({"name": "claude_version", "ok": False, "detail": str(error)})
    repository_path = Path(repository).expanduser().resolve()
    checks.append({"name": "git_repository", "ok": (repository_path / ".git").exists(), "detail": str(repository_path)})
    skill_roots = [Path.home() / ".claude" / "skills"]
    required = ("uu-review", "uu-second-opinion", "uu-summarize")
    for skill in required:
        locations = [str(root / skill / "SKILL.md") for root in skill_roots if (root / skill / "SKILL.md").is_file()]
        checks.append({"name": f"skill:{skill}", "ok": bool(locations), "detail": locations or "not installed for Claude"})
    try:
        policy = load_policy(repository_path, adapter_config or {
            "model": model, "minimum_model": minimum_model, "pin_model": pin_model or None,
        })
        checks.append({"name": "claude_policy", "ok": True, "detail": policy.to_dict()})
        checks.append({"name": "claude_effective_tools", "ok": True, "detail": policy.allowed_tools()})
    except ValueError as error:
        policy = None
        checks.append({"name": "claude_policy", "ok": False, "detail": str(error)})
    if live and claude and policy:
        auth_ok = False
        try:
            auth = subprocess.run(
                [claude, "auth", "status"], capture_output=True, text=True, timeout=timeout, check=False,
            )
            try:
                auth_detail = json.loads(auth.stdout) if auth.stdout.strip() else auth.stderr.strip()
                if isinstance(auth_detail, dict):
                    auth_detail = {
                        key: auth_detail.get(key) for key in ("loggedIn", "authMethod", "apiProvider")
                        if key in auth_detail
                    }
            except json.JSONDecodeError:
                auth_detail = auth.stdout.strip() or auth.stderr.strip() or f"exit {auth.returncode}"
            checks.append({
                "name": "claude_authentication", "ok": auth.returncode == 0,
                "detail": auth_detail,
            })
            auth_ok = auth.returncode == 0
        except subprocess.TimeoutExpired:
            checks.append({"name": "claude_authentication", "ok": False, "detail": "authentication_timeout"})
        probe_schema = {
            "type": "object", "properties": {"ready": {"const": True}},
            "required": ["ready"], "additionalProperties": False,
        }
        for role, profile in policy.roles.items():
            try:
                if not auth_ok:
                    raise RuntimeError("skipped because Claude authentication failed")
                command = [
                    claude, "-p", "Return ready=true. Do not use tools.", "--output-format", "json",
                    "--json-schema", json.dumps(probe_schema, separators=(",", ":")), "--tools", "",
                    "--model", profile.model, "--no-session-persistence",
                ]
                if profile.effort:
                    command.extend(["--effort", profile.effort])
                probe = subprocess.run(
                    command, cwd=repository_path, capture_output=True, text=True, timeout=timeout, check=False,
                )
                outer = json.loads(probe.stdout) if probe.returncode == 0 else {}
                model_usage = outer.get("modelUsage", {}) if isinstance(outer, dict) else {}
                observed_model, observed = select_observed_model(model_usage, profile)
                ok = probe.returncode == 0 and bool(observed_model)
                checks.append({
                    "name": f"claude_live_profile:{role}", "ok": ok,
                    "detail": {"requested": profile.model, "effort": profile.effort,
                               "observed": observed_model, "reported_models": observed,
                               "stderr": probe.stderr.strip()},
                })
            except (subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as error:
                checks.append({"name": f"claude_live_profile:{role}", "ok": False, "detail": str(error)})
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        runtime = _runtime(arguments)
        if arguments.command == "start":
            _emit(runtime.start(_model_payload(arguments, _read_json(arguments.input))))
        elif arguments.command == "register-plan":
            _emit(runtime.register_plan(_model_payload(arguments, _read_json(arguments.input))))
        elif arguments.command == "next":
            _emit(runtime.next_action(arguments.task).to_dict())
        elif arguments.command == "resume":
            _emit(runtime.resume(arguments.task))
        elif arguments.command == "status":
            _emit(runtime.status(arguments.task) if arguments.task else {"active_tasks": runtime.active_tasks(arguments.repository)})
        elif arguments.command == "contexts":
            _emit(runtime.status(arguments.task)["contexts"])
        elif arguments.command == "record-codex-result":
            _emit(runtime.record_codex_result(arguments.task, _read_json(arguments.input)))
        elif arguments.command == "provide-input":
            guidance = sys.stdin.read() if arguments.input == "-" else Path(arguments.input).read_text(encoding="utf-8")
            _emit(runtime.provide_input(arguments.task, guidance))
        elif arguments.command == "record-input-resolution":
            _emit(runtime.record_input_resolution(arguments.task, _read_json(arguments.input)))
        elif arguments.command == "report":
            content = render_report(runtime.database, arguments.task, persist=arguments.persist)
            _emit({"task_id": arguments.task, "report": content}) if arguments.format == "json" else print(content, end="")
        elif arguments.command == "refresh-context":
            _emit(runtime.refresh_context(arguments.task, arguments.reason))
        elif arguments.command == "stop":
            _emit(runtime.stop(arguments.task, arguments.reason))
        elif arguments.command == "recover-interrupted":
            _emit(runtime.recover_interrupted(arguments.task, arguments.reason))
        elif arguments.command == "recover-invalid-output":
            _emit(runtime.recover_invalid_output(
                arguments.task, model=arguments.model,
                minimum_model=arguments.minimum_model, pin_model=arguments.pin_model,
                adapter_config=_model_payload(arguments, {})["adapter_config"],
            ))
        elif arguments.command == "doctor":
            result = doctor(
                arguments.database, arguments.repository, live=arguments.live, timeout=arguments.timeout,
                model=arguments.model, minimum_model=arguments.minimum_model, pin_model=arguments.pin_model,
                adapter_config=_model_payload(arguments, {})["adapter_config"],
            )
            _emit(result)
            return 0 if result["ok"] else 1
        return 0
    except (WorkflowError, ValueError, json.JSONDecodeError, OSError, RuntimeError, sqlite3.IntegrityError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
