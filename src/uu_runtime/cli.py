from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .database import Database, SCHEMA_VERSION, default_database_path
from .engine import Runtime, WorkflowError
from .reporting import render_report


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

    for name in ("next", "resume", "contexts"):
        command = subcommands.add_parser(name)
        command.add_argument("--task", required=True)

    status = subcommands.add_parser("status")
    status.add_argument("--task")
    status.add_argument("--repository", default=os.getcwd())

    record = subcommands.add_parser("record-codex-result")
    record.add_argument("--task", required=True)
    record.add_argument("--input", default="-", help="result JSON path or - for stdin")

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

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--repository", default=os.getcwd())
    return parser


def doctor(database_path: str, repository: str) -> dict[str, Any]:
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
    repository_path = Path(repository).expanduser().resolve()
    checks.append({"name": "git_repository", "ok": (repository_path / ".git").exists(), "detail": str(repository_path)})
    skill_roots = [Path.home() / ".claude" / "skills"]
    required = ("uu-review", "uu-second-opinion", "uu-summarize")
    for skill in required:
        locations = [str(root / skill / "SKILL.md") for root in skill_roots if (root / skill / "SKILL.md").is_file()]
        checks.append({"name": f"skill:{skill}", "ok": bool(locations), "detail": locations or "not installed for Claude"})
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        runtime = _runtime(arguments)
        if arguments.command == "start":
            _emit(runtime.start(_read_json(arguments.input)))
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
        elif arguments.command == "report":
            content = render_report(runtime.database, arguments.task, persist=arguments.persist)
            _emit({"task_id": arguments.task, "report": content}) if arguments.format == "json" else print(content, end="")
        elif arguments.command == "refresh-context":
            _emit(runtime.refresh_context(arguments.task, arguments.reason))
        elif arguments.command == "stop":
            _emit(runtime.stop(arguments.task, arguments.reason))
        elif arguments.command == "recover-interrupted":
            _emit(runtime.recover_interrupted(arguments.task, arguments.reason))
        elif arguments.command == "doctor":
            result = doctor(arguments.database, arguments.repository)
            _emit(result)
            return 0 if result["ok"] else 1
        return 0
    except (WorkflowError, ValueError, json.JSONDecodeError, OSError, RuntimeError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
