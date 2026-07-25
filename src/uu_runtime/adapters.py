from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
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
from .policy import ClaudePolicy, MIN_CLAUDE_VERSION, format_version, select_observed_model, parse_version


class AdapterError(RuntimeError):
    pass


class HarnessExhaustedError(AdapterError):
    """The harness cannot continue without a fresh context or larger budget."""


class StructuredOutputError(AdapterError):
    """Claude completed a call but returned a payload outside the protocol contract."""

    def __init__(
        self, message: str, *, raw_output: str, stderr: str, payload: dict[str, Any],
        usage: dict[str, Any], before: GitSnapshot, after: GitSnapshot,
    ):
        super().__init__(message)
        self.raw_output = raw_output
        self.stderr = stderr
        self.payload = payload
        self.usage = usage
        self.before = before
        self.after = after


class ModelPolicyError(AdapterError):
    """A completed call used an unacceptable or unreported model identity."""

    def __init__(
        self, message: str, *, raw_output: str, payload: dict[str, Any], usage: dict[str, Any],
        before: GitSnapshot, after: GitSnapshot,
    ):
        super().__init__(message)
        self.raw_output = raw_output
        self.payload = payload
        self.usage = usage
        self.before = before
        self.after = after


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


PRIORITIES = {"P0", "P1", "P2", "P3"}
DISPOSITIONS = {"ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "ALREADY_RESOLVED", "BLOCKED"}


def validate_result(
    protocol: Protocol, result: ProtocolResult, purpose: Purpose | None = None,
    expected_disposition_ids: set[str] | None = None,
) -> None:
    if protocol == Protocol.UU_REVIEW:
        allowed = {str(item) for item in ReviewStatus}
    elif protocol == Protocol.UU_SECOND_OPINION:
        allowed = {str(item) for item in ChallengeStatus}
    else:
        allowed = {str(item) for item in CompletionStatus}
    if not isinstance(result.status, str) or result.status not in allowed:
        raise AdapterError(f"invalid {protocol} status: {result.status!r}")
    if not isinstance(result.findings, list) or not isinstance(result.dispositions, list):
        raise AdapterError("findings and dispositions must be arrays")
    for finding in result.findings:
        required = {"id", "priority", "title"}
        if not isinstance(finding, dict) or not required.issubset(finding):
            raise AdapterError("every finding requires id, priority, and title")
        if not isinstance(finding["id"], str) or not isinstance(finding["title"], str):
            raise AdapterError("finding id and title must be strings")
        if not isinstance(finding["priority"], str) or finding["priority"] not in PRIORITIES:
            raise AdapterError(f"invalid finding priority: {finding['priority']}")
    if result.status == "APPROVE" and result.findings:
        raise AdapterError("APPROVE cannot include findings")
    if result.status == "APPROVE_WITH_MINOR_ISSUES" and (
        not result.findings or any(item["priority"] != "P3" for item in result.findings)
    ):
        raise AdapterError("APPROVE_WITH_MINOR_ISSUES requires only P3 findings")
    if result.status == "REQUEST_CHANGES" and not result.findings and purpose != Purpose.CHALLENGE_ADJUDICATION:
        raise AdapterError("REQUEST_CHANGES requires at least one finding")
    if result.status == "REQUEST_CHANGES" and purpose != Purpose.CHALLENGE_ADJUDICATION:
        required_priorities = {"P0", "P1"} if protocol == Protocol.UU_SECOND_OPINION else {"P0", "P1", "P2"}
        if not any(item["priority"] in required_priorities for item in result.findings):
            raise AdapterError(f"REQUEST_CHANGES requires one of {sorted(required_priorities)}")
    if purpose != Purpose.CHALLENGE_ADJUDICATION and result.dispositions:
        raise AdapterError("dispositions are only allowed during challenge adjudication")
    for disposition in result.dispositions:
        required = {"finding_id", "disposition", "evidence"}
        if not isinstance(disposition, dict) or not required.issubset(disposition):
            raise AdapterError("every disposition requires finding_id, disposition, and evidence")
        if not isinstance(disposition["finding_id"], str):
            raise AdapterError("finding disposition IDs must be strings")
        if not isinstance(disposition["disposition"], str) or disposition["disposition"] not in DISPOSITIONS:
            raise AdapterError(f"invalid finding disposition: {disposition['disposition']}")
        if not isinstance(disposition["evidence"], str) or not disposition["evidence"].strip():
            raise AdapterError("finding dispositions require concrete evidence")
    disposition_ids = [item["finding_id"] for item in result.dispositions]
    if len(disposition_ids) != len(set(disposition_ids)):
        raise AdapterError("duplicate finding dispositions are not allowed")
    if expected_disposition_ids is not None and set(disposition_ids) != expected_disposition_ids:
        raise AdapterError(
            "challenge adjudication dispositions do not cover open findings: "
            f"expected {sorted(expected_disposition_ids)}, got {sorted(disposition_ids)}"
        )
    if protocol == Protocol.UU_SUMMARIZE and result.status == CompletionStatus.COMPLETED and (
        not isinstance(result.title, str) or not result.title.strip()
    ):
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
                    "priority": {"type": "string", "enum": sorted(PRIORITIES)},
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
                    "disposition": {"type": "string", "enum": sorted(DISPOSITIONS)},
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


def result_schema(
    protocol: Protocol, purpose: Purpose | None = None, expected_disposition_ids: set[str] | None = None,
) -> dict[str, Any]:
    schema = json.loads(json.dumps(RESULT_SCHEMA))
    if protocol == Protocol.UU_REVIEW:
        statuses = [str(item) for item in ReviewStatus]
    elif protocol == Protocol.UU_SECOND_OPINION:
        statuses = [str(item) for item in ChallengeStatus]
    else:
        statuses = [str(item) for item in CompletionStatus]
    schema["properties"]["status"] = {"type": "string", "enum": statuses}
    if purpose != Purpose.CHALLENGE_ADJUDICATION:
        schema["properties"]["dispositions"]["maxItems"] = 0
    elif expected_disposition_ids is not None:
        count = len(expected_disposition_ids)
        schema["properties"]["dispositions"].update({"minItems": count, "maxItems": count})
        schema["properties"]["dispositions"]["items"]["properties"]["finding_id"] = {
            "type": "string", "enum": sorted(expected_disposition_ids),
        }
    if protocol == Protocol.UU_SUMMARIZE:
        schema["properties"]["findings"]["maxItems"] = 0
    if protocol == Protocol.UU_SUMMARIZE:
        schema["properties"]["title"]["minLength"] = 1
    return schema


class ClaudeAdapter:
    name = "claude"

    def __init__(
        self, *, executable: str = "claude", timeout: float = 1800, policy: ClaudePolicy | None = None,
        enforce_model: bool | None = None, skill_root: Path | None = None,
    ):
        self.executable = executable
        self.timeout = timeout
        self.policy = policy or ClaudePolicy()
        self.enforce_model = executable == "claude" if enforce_model is None else enforce_model
        self.skill_root = skill_root or Path.home() / ".claude" / "skills"

    def run(
        self, action: NextAction, repository: Path, *, repair: bool = False,
        repair_error: StructuredOutputError | None = None,
    ) -> AdapterRun:
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
        if self.enforce_model:
            version = self.version(repository)
        else:
            try:
                version = self.version(repository)
            except AdapterError:
                version = "unknown"
        if self.enforce_model and parse_version(version) < MIN_CLAUDE_VERSION:
            raise AdapterError(
                f"Claude Code {version} is too old; {format_version(MIN_CLAUDE_VERSION)} or newer is required. "
                "Run `claude update`."
            )
        profile = self.policy.profile(self._role(action.protocol))
        prompt = self._repair_prompt(action, repair_error) if repair else self._prompt(action)
        allowed_tools = [] if repair else self.policy.allowed_tools()
        command = [
            self.executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(result_schema(
                action.protocol, action.purpose, set(action.inputs.get("expected_disposition_ids", []))
                if action.purpose == Purpose.CHALLENGE_ADJUDICATION else None,
            ), separators=(",", ":")),
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            ",".join(allowed_tools),
            "--disallowedTools",
            "Edit,Write,NotebookEdit" + (",Bash,Read,Glob,Grep" if repair else ""),
            "--model",
            profile.model,
        ]
        if profile.effort:
            command.extend(["--effort", profile.effort])
        if repair:
            command.extend(["--tools", ""])
        if action.fresh:
            if not action.context_id:
                raise AdapterError("new Claude context lacks a session UUID")
            command.extend(["--session-id", action.context_id])
        else:
            if not action.context_id:
                raise AdapterError("resumed Claude action lacks a session UUID")
            command.extend(["--resume", action.context_id])

        process = subprocess.Popen(command, cwd=repository, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = time.monotonic()
        stdout = stderr = ""
        while True:
            remaining = self.timeout - (time.monotonic() - started)
            if remaining <= 0:
                process.kill()
                process.communicate()
                error = subprocess.TimeoutExpired(command, self.timeout)
                raise HarnessExhaustedError(
                    f"Claude timed out after {self.timeout}s; workflow paused without retry"
                ) from error
            try:
                stdout, stderr = process.communicate(timeout=min(30.0, remaining))
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                if elapsed >= 1:
                    print(
                        f"uu-runtime: Claude {action.purpose} still running "
                        f"({int(elapsed)}s elapsed, {int(self.timeout)}s timeout)",
                        file=sys.stderr,
                        flush=True,
                    )
        if process.returncode is None:
            raise HarnessExhaustedError(
                f"Claude timed out after {self.timeout}s; workflow paused without retry"
            )
        after = snapshot(repository)
        if not same_worktree(before, after):
            raise AdapterError("read-only Claude protocol changed the repository worktree")
        if process.returncode != 0:
            message = stderr.strip() or stdout.strip() or f"Claude exited with {process.returncode}"
            if self._looks_exhausted(message):
                raise HarnessExhaustedError(f"Claude exhausted its context or token budget; workflow paused: {message}")
            raise AdapterError(message)

        outer, payload = self._extract_payload(stdout)
        usage = outer.get("usage", {}) if isinstance(outer, dict) else {}
        model_usage = outer.get("modelUsage", {}) if isinstance(outer, dict) else {}
        observed_model, observed = select_observed_model(model_usage, profile)
        observed_details = model_usage.get(observed_model, {}) if observed_model else {}
        detected_provider = outer.get("provider", "") if isinstance(outer, dict) else ""
        if not detected_provider and isinstance(observed_details, dict):
            detected_provider = observed_details.get("provider", "")
        usage = {
            **usage,
            "requested_role": profile.role,
            "requested_model": profile.model,
            "minimum_model": profile.minimum_model,
            "pin_model": profile.pin_model,
            "requested_effort": profile.effort,
            "observed_model": observed_model,
            "observed_models": observed,
            "claude_version": version,
            "provider": detected_provider,
            "model_satisfied": bool(observed_model),
            "modelUsage": model_usage,
        }
        if self.enforce_model and not usage["model_satisfied"]:
            raise ModelPolicyError(
                f"Claude model mismatch for {profile.role}: requested {profile.model!r} with minimum "
                f"{profile.minimum_model!r}, observed {observed or 'unreported'}",
                raw_output=stdout, payload=payload, usage=usage, before=before, after=after,
            )
        result = ProtocolResult.from_dict(payload)
        try:
            validate_result(
                action.protocol, result, action.purpose,
                set(action.inputs.get("expected_disposition_ids", []))
                if action.purpose == Purpose.CHALLENGE_ADJUDICATION else None,
            )
        except AdapterError as error:
            raise StructuredOutputError(
                str(error), raw_output=stdout, stderr=stderr, payload=payload,
                usage=usage, before=before, after=after,
            ) from error
        return AdapterRun(result, stdout, stderr, usage, before, after)

    @staticmethod
    def _extract_payload(raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            outer = json.loads(raw)
        except json.JSONDecodeError as error:
            raise AdapterError("Claude returned malformed JSON") from error
        if not isinstance(outer, dict):
            raise AdapterError("Claude JSON output must be an object")
        for key in ("structured_output", "result"):
            candidate = outer.get(key)
            if isinstance(candidate, dict):
                return outer, candidate
            if isinstance(candidate, str):
                try:
                    decoded = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return outer, decoded
        if "status" in outer:
            return outer, outer
        raise AdapterError("Claude JSON output did not contain a structured protocol result")

    @staticmethod
    def _looks_exhausted(message: str) -> bool:
        lowered = message.lower()
        return any(marker in lowered for marker in (
            "context window", "context length", "token limit", "max tokens", "maximum tokens",
            "out of tokens", "prompt is too long", "prompt too long", "budget exhausted", "usage limit reached",
        ))

    def version(self, repository: Path | None = None) -> str:
        result = subprocess.run(
            [self.executable, "--version"], cwd=repository, capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            raise AdapterError(result.stderr.strip() or "could not determine Claude Code version")
        return result.stdout.strip()

    def _skill_contract(self, protocol: Protocol) -> str:
        name = {
            Protocol.UU_REVIEW: "uu-review",
            Protocol.UU_SECOND_OPINION: "uu-second-opinion",
            Protocol.UU_SUMMARIZE: "uu-summarize",
        }.get(protocol)
        if not name:
            raise AdapterError(f"no Claude skill contract for {protocol}")
        path = self.skill_root / name / "SKILL.md"
        if not path.is_file():
            raise AdapterError(f"Claude skill contract not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _role(protocol: Protocol) -> str:
        if protocol == Protocol.UU_SECOND_OPINION:
            return "second_opinion"
        if protocol == Protocol.UU_SUMMARIZE:
            return "summarize"
        return "review"

    def _prompt(self, action: NextAction) -> str:
        contract = self._skill_contract(action.protocol)
        plan = action.inputs["canonical_plan_path"]
        if action.purpose == Purpose.CHALLENGE:
            return (
                f"Protocol contract (follow directly; do not invoke the Skill tool):\n{contract}\n\n"
                f"Canonical plan: {plan}\n"
                "Work only from the canonical plan and repository state. Do not use or request prior narratives. "
                "Use the exact underscore-delimited status token required by the JSON schema. "
                "Return the required structured result and place the normal skill report in report_markdown."
            )
        if action.purpose == Purpose.FINAL_SUMMARY:
            return (
                f"Protocol contract (follow directly; do not invoke the Skill tool):\n{contract}\n\n"
                f"Canonical plan: {plan}\n"
                "Use the exact underscore-delimited status token required by the JSON schema. "
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
            f"Protocol contract (follow directly; do not invoke the Skill tool):\n{contract}\n\n"
            f"Canonical plan: {plan}\n{label}:\n{material}\n\n"
            "Use the exact underscore-delimited status token required by the JSON schema. "
            "Return the normal skill report in report_markdown plus the required structured fields. "
            "During challenge adjudication, include a disposition for every challenge finding."
        )

    def _repair_prompt(self, action: NextAction, error: StructuredOutputError | None) -> str:
        if error is None:
            raise AdapterError("structured repair requires the original validation error")
        contract = self._skill_contract(action.protocol)
        diagnostic = str(error)
        fields = [token.rstrip(":") for token in diagnostic.split() if token.startswith(("status", "finding", "disposition"))]
        return (
            "Your previous protocol call completed, but its structured result failed runtime protocol validation.\n"
            "Do not inspect the repository, invoke tools, or repeat the substantive work. Re-emit the completed "
            "judgment under the contract and schema. Preserve substantive conclusions; select the status required "
            "by the automated rules for those conclusions.\n\n"
            f"Relevant protocol contract:\n{contract}\n\n"
            f"Exact validation diagnostic: {diagnostic}\n"
            f"Offending-field hints: {json.dumps(fields)}\n"
            f"Original structured payload:\n{json.dumps(error.payload, indent=2, sort_keys=True)}\n\n"
            "Automated status rules: APPROVE has no findings; APPROVE_WITH_MINOR_ISSUES has P3 findings only; "
            "ordinary REQUEST_CHANGES includes a P0-P2 finding; second-opinion REQUEST_CHANGES includes P0/P1. "
            "Dispositions are empty outside challenge adjudication, where every challenged finding is covered once. "
            "Use only P0-P3 priorities and the disposition enums supplied by the schema."
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
        validate_result(
            action.protocol, result, action.purpose,
            set(action.inputs.get("expected_disposition_ids", []))
            if action.purpose == Purpose.CHALLENGE_ADJUDICATION else None,
        )
        after = snapshot(repository)
        raw = json.dumps(result.to_dict(), sort_keys=True)
        return AdapterRun(result, raw, "", {}, before, after)


def new_session_id() -> str:
    return str(uuid.uuid4())
