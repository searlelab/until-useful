from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Protocol(StrEnum):
    UU_PLAN = "UU_PLAN"
    UU_REVIEW = "UU_REVIEW"
    UU_REVISE = "UU_REVISE"
    UU_SECOND_OPINION = "UU_SECOND_OPINION"
    UU_SUMMARIZE = "UU_SUMMARIZE"


class Purpose(StrEnum):
    INITIAL_IMPLEMENTATION = "INITIAL_IMPLEMENTATION"
    INITIAL_REVIEW = "INITIAL_REVIEW"
    REVISION_VERIFICATION = "REVISION_VERIFICATION"
    CHALLENGE = "CHALLENGE"
    CHALLENGE_ADJUDICATION = "CHALLENGE_ADJUDICATION"
    CHALLENGE_REVISION = "CHALLENGE_REVISION"
    CHALLENGE_VERIFICATION = "CHALLENGE_VERIFICATION"
    FINAL_SUMMARY = "FINAL_SUMMARY"
    INPUT_RESOLUTION = "INPUT_RESOLUTION"


class ContextClass(StrEnum):
    CONSTRUCTIVE = "CONSTRUCTIVE"
    REVIEW = "REVIEW"
    FRESH_CHALLENGE = "FRESH_CHALLENGE"


class TaskState(StrEnum):
    WAITING_FOR_INITIAL_IMPLEMENTATION = "WAITING_FOR_INITIAL_IMPLEMENTATION"
    READY_FOR_INITIAL_REVIEW = "READY_FOR_INITIAL_REVIEW"
    WAITING_FOR_CODEX_REVISION = "WAITING_FOR_CODEX_REVISION"
    READY_FOR_REVISION_VERIFICATION = "READY_FOR_REVISION_VERIFICATION"
    READY_FOR_CHALLENGE = "READY_FOR_CHALLENGE"
    READY_FOR_CHALLENGE_ADJUDICATION = "READY_FOR_CHALLENGE_ADJUDICATION"
    WAITING_FOR_CHALLENGE_REVISION = "WAITING_FOR_CHALLENGE_REVISION"
    READY_FOR_CHALLENGE_VERIFICATION = "READY_FOR_CHALLENGE_VERIFICATION"
    READY_FOR_FINAL_SUMMARY = "READY_FOR_FINAL_SUMMARY"
    WAITING_FOR_HUMAN_REVIEW = "WAITING_FOR_HUMAN_REVIEW"
    NEEDS_INPUT = "NEEDS_INPUT"
    WAITING_FOR_CODEX_INPUT_RESOLUTION = "WAITING_FOR_CODEX_INPUT_RESOLUTION"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    STOPPED = "STOPPED"


class ReviewStatus(StrEnum):
    APPROVE = "APPROVE"
    APPROVE_WITH_MINOR_ISSUES = "APPROVE_WITH_MINOR_ISSUES"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    BLOCKED = "BLOCKED"


class ChallengeStatus(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    BLOCKED = "BLOCKED"


class CompletionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NO_CURRENT_CHANGESET = "NO_CURRENT_CHANGESET"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class Disposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    ALREADY_RESOLVED = "ALREADY_RESOLVED"
    BLOCKED = "BLOCKED"


class ActionOwner(StrEnum):
    CLAUDE = "CLAUDE"
    CODEX = "CODEX"
    HUMAN = "HUMAN"
    NONE = "NONE"


class PipelineOutcome(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    APPROVE = "APPROVE"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class InputDecision(StrEnum):
    REVISED = "REVISED"
    RETRY = "RETRY"
    APPROVE = "APPROVE"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"


def pipeline_outcome(state: TaskState | str) -> PipelineOutcome:
    state = TaskState(state)
    if state == TaskState.WAITING_FOR_HUMAN_REVIEW:
        return PipelineOutcome.APPROVE
    if state in {TaskState.NEEDS_INPUT, TaskState.BLOCKED}:
        return PipelineOutcome.NEEDS_INPUT
    if state == TaskState.FAILED:
        return PipelineOutcome.FAILED
    if state == TaskState.STOPPED:
        return PipelineOutcome.STOPPED
    return PipelineOutcome.IN_PROGRESS


@dataclass(frozen=True)
class Finding:
    id: str
    priority: str
    title: str
    evidence: str = ""
    failure_scenario: str = ""
    impact: str = ""
    correction: str = ""


@dataclass(frozen=True)
class ProtocolResult:
    status: str
    summary: str = ""
    report_markdown: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    dispositions: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    residual_risks: list[str] = field(default_factory=list)
    title: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProtocolResult":
        known = {key: value.get(key, default) for key, default in (
            ("status", ""), ("summary", ""), ("report_markdown", ""),
            ("findings", []), ("dispositions", []), ("checks", []),
            ("residual_risks", []), ("title", ""),
        )}
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NextAction:
    owner: ActionOwner
    purpose: Purpose | None
    protocol: Protocol | None
    context_id: str | None
    lineage: str | None
    fresh: bool
    inputs: dict[str, Any]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("owner", "purpose", "protocol"):
            if value[key] is not None:
                value[key] = str(value[key])
        return value


RISK_PROFILES: dict[str, tuple[int, int]] = {
    "routine": (1, 1),
    "feature": (1, 2),
    "critical": (1, 3),
    "security": (2, 4),
}


TERMINAL_STATES = {
    TaskState.WAITING_FOR_HUMAN_REVIEW,
    TaskState.NEEDS_INPUT,
    TaskState.FAILED,
    TaskState.BLOCKED,
    TaskState.STOPPED,
}
