from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol as TypingProtocol

from .git_state import GitSnapshot, same_worktree, snapshot
from .models import (
    ChallengeStatus,
    CompletionStatus,
    NextAction,
    Protocol,
    ProtocolResult,
    Purpose,
    ReviewStatus,
)


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterRun:
    result: ProtocolResult
    raw_output: str
    stderr: str
    usage: dict[str, Any]
    before: GitSnapshot
    after: GitSnapshot


class HarnessAdapter(TypingProtocol):
    name: str

    def run(self, action: NextAction, repository: Path) -> AdapterRun: ...


def validate_result(protocol: Protocol, result: ProtocolResult, purpose: Purpose | None = None) -> None:
    if protocol == Protocol.UU_REVIEW:
        allowed = {str(item) for item in ReviewStatus}
    elif protocol == Protocol.UU_SECOND_OPINION:
        allowed = {str(item) for item in ChallengeStatus}
    else:
        allowed = {str(item) for item in CompletionStatus}
    if result.status not in allowed:
        raise AdapterError(f"invalid {protocol} status: {result.status!r}")
    if not isinstance(result.findings, list) or not isinstance(result.dispositions, list):
        raise AdapterError("findings and dispositions must be arrays")
    for finding in result.findings:
        required = {"id", "priority", "title"}
        if not isinstance(finding, dict) or not required.issubset(finding):
            raise AdapterError("every finding requires id, priority, and title")
    if result.status == "REQUEST_CHANGES" and not result.findings and purpose != Purpose.CHALLENGE_ADJUDICATION:
        raise AdapterError("REQUEST_CHANGES requires at least one finding")
    for disposition in result.dispositions:
        required = {"finding_id", "disposition", "evidence"}
        if not isinstance(disposition, dict) or not required.issubset(disposition):
            raise AdapterError("every disposition requires finding_id, disposition, and evidence")
        if disposition["disposition"] not in {"ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "ALREADY_RESOLVED", "BLOCKED"}:
            raise AdapterError(f"invalid finding disposition: {disposition['disposition']}")
        if not disposition["evidence"].strip():
            raise AdapterError("finding dispositions require concrete evidence")
    disposition_ids = [item["finding_id"] for item in result.dispositions]
    if len(disposition_ids) != len(set(disposition_ids)):
        raise AdapterError("duplicate finding dispositions are not allowed")
    if protocol == Protocol.UU_SUMMARIZE and result.status == CompletionStatus.COMPLETED and not result.title.strip():
        raise AdapterError("completed summarize result requires a title")


RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "report_markdown": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "priority": {"type": "string"},
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                    "failure_scenario": {"type": "string"},
                    "impact": {"type": "string"},
                    "correction": {"type": "string"},
                },
                "required": ["id", "priority", "title", "evidence", "failure_scenario", "impact", "correction"],
                "additionalProperties": False,
            },
        },
        "dispositions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "disposition": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["finding_id", "disposition", "evidence"],
                "additionalProperties": False,
            },
        },
        "checks": {"type": "array", "items": {"type": "object"}},
        "residual_risks": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
    },
    "required": ["status", "summary", "report_markdown", "findings", "dispositions", "checks", "residual_risks", "title"],
    "additionalProperties": False,
}


class ClaudeAdapter:
    name = "claude"

    def __init__(self, *, executable: str = "claude", timeout: int = 1800, model: str | None = None):
        self.executable = executable
        self.timeout = timeout
        self.model = model

    def run(self, action: NextAction, repository: Path) -> AdapterRun:
        if not shutil.which(self.executable):
            raise AdapterError(f"Claude executable not found: {self.executable}")
        if action.owner.value != "CLAUDE" or action.protocol is None or action.purpose is None:
            raise AdapterError("Claude adapter received a non-Claude action")
        if action.fresh and action.purpose == Purpose.CHALLENGE:
            allowed = {"repository_path", "canonical_plan_path"}
            unexpected = set(action.inputs) - allowed
            if unexpected:
                raise AdapterError(f"fresh challenge envelope is contaminated: {sorted(unexpected)}")

        before = snapshot(repository)
        prompt = self._prompt(action)
        command = [
            self.executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(RESULT_SCHEMA, separators=(",", ":")),
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "Read,Glob,Grep,Bash",
            "--disallowedTools",
            "Edit,Write,NotebookEdit",
        ]
        if self.model:
            command.extend(["--model", self.model])
        if action.fresh:
            if not action.context_id:
                raise AdapterError("new Claude context lacks a session UUID")
            command.extend(["--session-id", action.context_id])
        else:
            if not action.context_id:
                raise AdapterError("resumed Claude action lacks a session UUID")
            command.extend(["--resume", action.context_id])

        try:
            process = subprocess.run(
                command,
                cwd=repository,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise AdapterError(f"Claude timed out after {self.timeout}s") from error
        after = snapshot(repository)
        if not same_worktree(before, after):
            raise AdapterError("read-only Claude protocol changed the repository worktree")
        if process.returncode != 0:
            raise AdapterError(process.stderr.strip() or f"Claude exited with {process.returncode}")

        payload = self._extract_payload(process.stdout)
        result = ProtocolResult.from_dict(payload)
        validate_result(action.protocol, result, action.purpose)
        outer = json.loads(process.stdout)
        usage = outer.get("usage", {}) if isinstance(outer, dict) else {}
        return AdapterRun(result, process.stdout, process.stderr, usage, before, after)

    @staticmethod
    def _extract_payload(raw: str) -> dict[str, Any]:
        try:
            outer = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AdapterError("Claude returned malformed JSON") from error
        if not isinstance(outer, dict):
            raise AdapterError("Claude JSON output must be an object")
        for key in ("structured_output", "result"):
            candidate = outer.get(key)
            if isinstance(candidate, dict):
                return candidate
            if isinstance(candidate, str):
                try:
                    decoded = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return decoded
        if "status" in outer:
            return outer
        raise AdapterError("Claude JSON output did not contain a structured protocol result")

    @staticmethod
    def _prompt(action: NextAction) -> str:
        plan = action.inputs["canonical_plan_path"]
        if action.purpose == Purpose.CHALLENGE:
            return (
                "/uu-second-opinion\n\n"
                f"Canonical plan: {plan}\n"
                "Work only from the canonical plan and repository state. Do not use or request prior narratives. "
                "Return the required structured result and place the normal skill report in report_markdown."
            )
        if action.purpose == Purpose.FINAL_SUMMARY:
            return (
                "/uu-summarize\n\n"
                f"Canonical plan: {plan}\n"
                "Return the exact one-line title in title and the structured result."
            )
        handoff = action.inputs.get("handoff_report", "")
        challenge = action.inputs.get("challenge_report", "")
        if action.purpose == Purpose.CHALLENGE_ADJUDICATION:
            material = challenge
            label = "Second-opinion report for repository-context adjudication"
        else:
            material = handoff
            label = "Codex worker handoff"
        return (
            "/uu-review\n\n"
            f"Canonical plan: {plan}\n{label}:\n{material}\n\n"
            "Return the normal skill report in report_markdown plus the required structured fields. "
            "During challenge adjudication, include a disposition for every challenge finding."
        )


class FakeAdapter:
    name = "fake"

    def __init__(self, scenario: list[dict[str, Any]]):
        self.scenario = scenario

    def run(self, action: NextAction, repository: Path) -> AdapterRun:
        before = snapshot(repository)
        index = int(action.inputs.get("fake_index", 0))
        if index >= len(self.scenario):
            raise AdapterError(f"fake scenario exhausted at action {index}")
        step = self.scenario[index]
        expected = step.get("purpose")
        if expected and expected != str(action.purpose):
            raise AdapterError(f"fake step {index} expected {expected}, got {action.purpose}")
        result_data = step.get("result", step)
        result = ProtocolResult.from_dict(result_data)
        if action.protocol is None:
            raise AdapterError("fake adapter action lacks protocol")
        validate_result(action.protocol, result, action.purpose)
        after = snapshot(repository)
        raw = json.dumps(result.to_dict(), sort_keys=True)
        return AdapterRun(result, raw, "", {}, before, after)


def new_session_id() -> str:
    return str(uuid.uuid4())
