from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .adapters import AdapterError, AdapterRun, ClaudeAdapter, FakeAdapter, HarnessAdapter, new_session_id
from .database import Database, utc_now
from .git_state import snapshot as git_snapshot
from .models import (
    ActionOwner,
    CompletionStatus,
    ContextClass,
    Disposition,
    NextAction,
    Protocol,
    ProtocolResult,
    Purpose,
    RISK_PROFILES,
    ReviewStatus,
    TaskState,
    TERMINAL_STATES,
)


class WorkflowError(RuntimeError):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _slug(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in cleaned.split("-") if part)[:80] or "task"


class Runtime:
    def __init__(self, database: Database):
        self.database = database
        self.database.migrate()

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        required = {"title", "repository_path", "canonical_plan_path", "risk_profile", "handoff_report"}
        missing = sorted(required - request.keys())
        if missing:
            raise WorkflowError(f"start request missing: {', '.join(missing)}")
        repository = Path(request["repository_path"]).expanduser().resolve()
        if not (repository / ".git").exists():
            raise WorkflowError(f"not a Git repository: {repository}")
        plan = Path(request["canonical_plan_path"])
        plan_absolute = plan if plan.is_absolute() else repository / plan
        plan_absolute = plan_absolute.resolve()
        try:
            plan_relative = plan_absolute.relative_to(repository)
        except ValueError as error:
            raise WorkflowError("canonical plan must be inside the repository") from error
        if not plan_absolute.is_file():
            raise WorkflowError(f"canonical plan does not exist: {plan_absolute}")
        risk = request["risk_profile"]
        if risk not in RISK_PROFILES:
            raise WorkflowError(f"unknown risk profile: {risk}")
        adapter_name = request.get("adapter", "claude")
        adapter_config = request.get("adapter_config", {})
        if adapter_name not in {"claude", "fake"}:
            raise WorkflowError(f"unsupported adapter: {adapter_name}")

        task_id = request.get("task_id", _uuid())
        context_id = _uuid()
        now = utc_now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO tasks(id, title, slug, repository_path, canonical_plan_path, risk_profile, state, "
                "constructive_context_id, initial_handoff, last_codex_handoff, adapter_name, adapter_config_json, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id, request["title"], request.get("slug", _slug(request["title"])), str(repository),
                    str(plan_relative), risk, TaskState.READY_FOR_INITIAL_REVIEW, context_id,
                    request["handoff_report"], request["handoff_report"], adapter_name,
                    json.dumps(adapter_config, sort_keys=True), now, now,
                ),
            )
            connection.execute(
                "INSERT INTO contexts(id, task_id, lineage_label, context_class, adapter, harness, session_id, "
                "created_at, is_fresh) VALUES (?, ?, 'P1', ?, 'codex', 'codex-app', NULL, ?, 0)",
                (context_id, task_id, ContextClass.CONSTRUCTIVE, now),
            )
            connection.execute(
                "INSERT INTO approvals(task_id, gate, decision, actor, notes, created_at) "
                "VALUES (?, 'PLAN_APPROVAL', 'APPROVED', 'human', ?, ?)",
                (task_id, request.get("approval_notes", "Approved through Codex planning interaction"), now),
            )
            self.database.event(
                connection, task_id, "TASK_REGISTERED", None, TaskState.READY_FOR_INITIAL_REVIEW,
                {"constructive_context": "P1", "canonical_plan_path": str(plan_relative)},
            )
        return self.status(task_id)

    def task(self, task_id: str) -> dict[str, Any]:
        task = self.database.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not task:
            raise WorkflowError(f"unknown task: {task_id}")
        return task

    def status(self, task_id: str) -> dict[str, Any]:
        task = self.task(task_id)
        contexts = self.database.all(
            "SELECT lineage_label, context_class, adapter, harness, model_label, session_id, created_at, retired_at "
            "FROM contexts WHERE task_id = ? ORDER BY created_at, lineage_label", (task_id,),
        )
        active_run = self.database.one(
            "SELECT id, protocol, workflow_purpose, started_at FROM runs WHERE task_id = ? AND status = 'RUNNING'",
            (task_id,),
        )
        return {
            "task_id": task_id,
            "title": task["title"],
            "state": task["state"],
            "repository_path": task["repository_path"],
            "canonical_plan_path": task["canonical_plan_path"],
            "risk_profile": task["risk_profile"],
            "revision_cycle": task["revision_cycle"],
            "challenge_cycle": task["challenge_cycle"],
            "review_epoch": task["review_epoch"],
            "stop_reason": task["stop_reason"],
            "final_title": task["final_title"],
            "active_run": active_run,
            "contexts": contexts,
        }

    def active_tasks(self, repository_path: str | Path) -> list[dict[str, Any]]:
        repository = str(Path(repository_path).expanduser().resolve())
        return self.database.all(
            "SELECT id, title, state, canonical_plan_path, updated_at FROM tasks WHERE repository_path = ? "
            "AND state NOT IN (?, ?, ?) ORDER BY created_at DESC",
            (repository, TaskState.WAITING_FOR_HUMAN_REVIEW, TaskState.BLOCKED, TaskState.STOPPED),
        )

    def find_task(self, repository_path: str | Path) -> dict[str, Any] | None:
        repository = str(Path(repository_path).expanduser().resolve())
        return self.database.one(
            "SELECT * FROM tasks WHERE repository_path = ? AND state NOT IN (?, ?, ?) "
            "ORDER BY created_at DESC LIMIT 1",
            (repository, TaskState.WAITING_FOR_HUMAN_REVIEW, TaskState.BLOCKED, TaskState.STOPPED),
        )

    def next_action(self, task_id: str) -> NextAction:
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            state = TaskState(task["state"])
            plan_inputs = {
                "repository_path": task["repository_path"],
                "canonical_plan_path": task["canonical_plan_path"],
            }
            if state in TERMINAL_STATES:
                return NextAction(ActionOwner.HUMAN, None, None, None, None, False, plan_inputs, task["stop_reason"] or state)

            if state == TaskState.READY_FOR_INITIAL_REVIEW:
                context = self._ensure_initial_reviewer(connection, task)
                return NextAction(
                    ActionOwner.CLAUDE, Purpose.INITIAL_REVIEW, Protocol.UU_REVIEW,
                    context["session_id"], context["lineage_label"], self._context_unused(connection, context["id"]),
                    {**plan_inputs, "handoff_report": task["initial_handoff"]},
                )
            if state == TaskState.WAITING_FOR_CODEX_REVISION:
                return self._codex_action(connection, task, Purpose.REVISION_VERIFICATION, plan_inputs)
            if state == TaskState.READY_FOR_REVISION_VERIFICATION:
                context = self._context(connection, task["review_frontier_context_id"])
                return NextAction(
                    ActionOwner.CLAUDE, Purpose.REVISION_VERIFICATION, Protocol.UU_REVIEW,
                    context["session_id"], context["lineage_label"], False,
                    {**plan_inputs, "handoff_report": task["last_codex_handoff"] or ""},
                )
            if state == TaskState.READY_FOR_CHALLENGE:
                context = self._ensure_challenger(connection, task)
                return NextAction(
                    ActionOwner.CLAUDE, Purpose.CHALLENGE, Protocol.UU_SECOND_OPINION,
                    context["session_id"], context["lineage_label"], True, plan_inputs,
                )
            if state == TaskState.READY_FOR_CHALLENGE_ADJUDICATION:
                prior = self._context(connection, task["prior_review_context_id"])
                challenge = self._latest_result(connection, task_id, Purpose.CHALLENGE)
                return NextAction(
                    ActionOwner.CLAUDE, Purpose.CHALLENGE_ADJUDICATION, Protocol.UU_REVIEW,
                    prior["session_id"], prior["lineage_label"], False,
                    {**plan_inputs, "challenge_report": challenge["cleaned_report"] or challenge["raw_output"]},
                )
            if state == TaskState.WAITING_FOR_CHALLENGE_REVISION:
                return self._codex_action(connection, task, Purpose.CHALLENGE_REVISION, plan_inputs)
            if state == TaskState.READY_FOR_CHALLENGE_VERIFICATION:
                challenger = self._context(connection, task["active_challenger_context_id"])
                return NextAction(
                    ActionOwner.CLAUDE, Purpose.CHALLENGE_VERIFICATION, Protocol.UU_REVIEW,
                    challenger["session_id"], challenger["lineage_label"], False,
                    {**plan_inputs, "handoff_report": task["last_codex_handoff"] or ""},
                )
            if state == TaskState.READY_FOR_FINAL_SUMMARY:
                frontier = self._context(connection, task["review_frontier_context_id"])
                return NextAction(
                    ActionOwner.CLAUDE, Purpose.FINAL_SUMMARY, Protocol.UU_SUMMARIZE,
                    frontier["session_id"], frontier["lineage_label"], False, plan_inputs,
                )
            raise WorkflowError(f"no action defined for state {state}")

    def execute_next(self, task_id: str) -> dict[str, Any]:
        action = self.next_action(task_id)
        if action.owner != ActionOwner.CLAUDE:
            return {"action": action.to_dict(), "status": self.status(task_id)}
        task = self.task(task_id)
        adapter = self._adapter(task)
        if isinstance(adapter, FakeAdapter):
            completed = self.database.require_one(
                "SELECT COUNT(*) AS count FROM runs WHERE task_id = ? AND status = 'COMPLETED' AND context_id != ?",
                (task_id, task["constructive_context_id"]),
            )["count"]
            action = replace(action, inputs={**action.inputs, "fake_index": completed})
        run_id = self._begin_run(task, action)
        try:
            run = adapter.run(action, Path(task["repository_path"]))
            self._complete_run(task_id, run_id, action, run)
        except Exception as error:
            self._fail_run(task_id, run_id, error)
            raise
        return {"action": action.to_dict(), "result": run.result.to_dict(), "status": self.status(task_id)}

    def resume(self, task_id: str) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        while True:
            action = self.next_action(task_id)
            if action.owner != ActionOwner.CLAUDE:
                return {"history": history, "next_action": action.to_dict(), "status": self.status(task_id)}
            history.append(self.execute_next(task_id))

    def record_codex_result(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = ProtocolResult.from_dict(payload)
        if result.status not in {CompletionStatus.COMPLETED, CompletionStatus.BLOCKED, CompletionStatus.FAILED}:
            raise WorkflowError(f"invalid Codex completion status: {result.status}")
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            state = TaskState(task["state"])
            if state == TaskState.WAITING_FOR_CODEX_REVISION:
                purpose = Purpose.REVISION_VERIFICATION
                next_state = TaskState.READY_FOR_REVISION_VERIFICATION
            elif state == TaskState.WAITING_FOR_CHALLENGE_REVISION:
                purpose = Purpose.CHALLENGE_REVISION
                next_state = TaskState.READY_FOR_CHALLENGE_VERIFICATION
            else:
                raise WorkflowError(f"task is not waiting for Codex: {state}")
            run_id = _uuid()
            sequence = self._next_sequence(connection, task_id)
            now = utc_now()
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, "
                "started_at, finished_at, raw_output, cleaned_report, normalized_result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?)",
                (
                    run_id, task_id, task["constructive_context_id"], Protocol.UU_REVISE, purpose, sequence,
                    now, now, json.dumps(payload, sort_keys=True), result.report_markdown or result.summary,
                    json.dumps(result.to_dict(), sort_keys=True),
                ),
            )
            if result.status != CompletionStatus.COMPLETED:
                next_state = TaskState.BLOCKED
            connection.execute(
                "UPDATE tasks SET state = ?, pending_codex_purpose = NULL, last_codex_handoff = ?, "
                "stop_reason = ?, updated_at = ? WHERE id = ?",
                (
                    next_state, result.report_markdown or result.summary,
                    None if result.status == CompletionStatus.COMPLETED else result.summary or result.status,
                    now, task_id,
                ),
            )
            self.database.event(connection, task_id, "CODEX_RESULT_RECORDED", state, next_state, result.to_dict(), run_id)
        return self.status(task_id)

    def refresh_context(self, task_id: str, reason: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            current = self._context(connection, task["constructive_context_id"])
            count = connection.execute(
                "SELECT COUNT(*) FROM contexts WHERE task_id = ? AND context_class = ?",
                (task_id, ContextClass.CONSTRUCTIVE),
            ).fetchone()[0]
            new_id = _uuid()
            lineage = f"P{count + 1}"
            now = utc_now()
            connection.execute(
                "UPDATE contexts SET retired_at = ?, retirement_reason = ? WHERE id = ?",
                (now, reason, current["id"]),
            )
            connection.execute(
                "INSERT INTO contexts(id, task_id, lineage_label, context_class, adapter, harness, parent_context_id, "
                "created_at, is_fresh) VALUES (?, ?, ?, ?, 'codex', 'codex-app', ?, ?, 1)",
                (new_id, task_id, lineage, ContextClass.CONSTRUCTIVE, current["id"], now),
            )
            handoff = self._constructive_handoff(connection, task)
            connection.execute(
                "UPDATE tasks SET constructive_context_id = ?, last_codex_handoff = ?, updated_at = ? WHERE id = ?",
                (new_id, handoff, now, task_id),
            )
            self.database.event(
                connection, task_id, "CONTEXT_REFRESHED", task["state"], task["state"],
                {"from": current["lineage_label"], "to": lineage, "reason": reason, "handoff": handoff},
            )
        return {"status": self.status(task_id), "handoff": handoff}

    def stop(self, task_id: str, reason: str) -> dict[str, Any]:
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            before = task["state"]
            connection.execute(
                "UPDATE tasks SET state = ?, stop_reason = ?, updated_at = ? WHERE id = ?",
                (TaskState.STOPPED, reason, utc_now(), task_id),
            )
            self.database.event(connection, task_id, "HUMAN_STOP", before, TaskState.STOPPED, {"reason": reason})
        return self.status(task_id)

    def recover_interrupted(self, task_id: str, reason: str) -> dict[str, Any]:
        try:
            repository_after = json.dumps(git_snapshot(self.task(task_id)["repository_path"]).to_dict(), sort_keys=True)
        except Exception as error:
            repository_after = json.dumps({"snapshot_error": str(error)}, sort_keys=True)
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            run = connection.execute(
                "SELECT id FROM runs WHERE task_id = ? AND status = 'RUNNING'", (task_id,)
            ).fetchone()
            if not run:
                raise WorkflowError("task has no interrupted RUNNING record")
            now = utc_now()
            connection.execute(
                "UPDATE runs SET status = 'INTERRUPTED', finished_at = ?, error_json = ?, repository_after_json = ? "
                "WHERE id = ?",
                (now, json.dumps({"type": "InterruptedRun", "message": reason}), repository_after, run["id"]),
            )
            connection.execute(
                "UPDATE tasks SET state = ?, stop_reason = ?, updated_at = ? WHERE id = ?",
                (TaskState.BLOCKED, reason, now, task_id),
            )
            self.database.event(
                connection, task_id, "INTERRUPTED_RUN_BLOCKED", task["state"], TaskState.BLOCKED,
                {"reason": reason}, run["id"],
            )
        return self.status(task_id)

    def _adapter(self, task: dict[str, Any]) -> HarnessAdapter:
        config = json.loads(task["adapter_config_json"] or "{}")
        if task["adapter_name"] == "fake":
            return FakeAdapter(config.get("scenario", []))
        return ClaudeAdapter(
            executable=config.get("executable", "claude"),
            timeout=int(config.get("timeout", 1800)),
            model=config.get("model"),
        )

    def _begin_run(self, task: dict[str, Any], action: NextAction) -> str:
        expected = self.next_action(task["id"])
        repository_before = git_snapshot(task["repository_path"])
        with self.database.transaction(immediate=True) as connection:
            current = self._task(connection, task["id"])
            if (expected.purpose, expected.context_id) != (action.purpose, action.context_id):
                raise WorkflowError("task advanced before the run could start")
            context = connection.execute(
                "SELECT id FROM contexts WHERE task_id = ? AND session_id = ?",
                (task["id"], action.context_id),
            ).fetchone()
            run_id = _uuid()
            try:
                connection.execute(
                    "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, "
                    "started_at, repository_before_json) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)",
                    (
                        run_id, task["id"], context["id"], action.protocol, action.purpose,
                        self._next_sequence(connection, task["id"]), utc_now(),
                        json.dumps(repository_before.to_dict(), sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise WorkflowError("another runtime run is active") from error
            self.database.event(connection, task["id"], "RUN_STARTED", current["state"], current["state"], action.to_dict(), run_id)
            return run_id

    def _complete_run(self, task_id: str, run_id: str, action: NextAction, run: AdapterRun) -> None:
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            connection.execute(
                "UPDATE runs SET status = 'COMPLETED', finished_at = ?, raw_output = ?, cleaned_report = ?, "
                "normalized_result_json = ?, repository_before_json = ?, repository_after_json = ?, usage_json = ? "
                "WHERE id = ? AND status = 'RUNNING'",
                (
                    utc_now(), run.raw_output, run.result.report_markdown or run.result.summary,
                    json.dumps(run.result.to_dict(), sort_keys=True), json.dumps(run.before.to_dict(), sort_keys=True),
                    json.dumps(run.after.to_dict(), sort_keys=True), json.dumps(run.usage, sort_keys=True), run_id,
                ),
            )
            context = connection.execute("SELECT id FROM contexts WHERE session_id = ?", (action.context_id,)).fetchone()
            connection.execute("UPDATE contexts SET is_fresh = 0 WHERE id = ?", (context["id"],))
            self._store_findings(connection, task_id, run_id, run.result)
            self._transition(connection, task, action, run_id, run.result)
        completed = self.task(task_id)
        if completed["state"] == TaskState.WAITING_FOR_HUMAN_REVIEW:
            existing = self.database.one(
                "SELECT id FROM reports WHERE task_id = ? AND report_type = 'FINAL_WORKFLOW' LIMIT 1", (task_id,)
            )
            if not existing:
                from .reporting import render_report

                render_report(self.database, task_id, persist=True)

    def _fail_run(self, task_id: str, run_id: str, error: Exception) -> None:
        task_snapshot = self.task(task_id)
        try:
            repository_after = json.dumps(git_snapshot(task_snapshot["repository_path"]).to_dict(), sort_keys=True)
        except Exception as snapshot_error:
            repository_after = json.dumps({"snapshot_error": str(snapshot_error)}, sort_keys=True)
        with self.database.transaction(immediate=True) as connection:
            task = self._task(connection, task_id)
            now = utc_now()
            connection.execute(
                "UPDATE runs SET status = 'FAILED', finished_at = ?, error_json = ?, repository_after_json = ? WHERE id = ?",
                (now, json.dumps({"type": type(error).__name__, "message": str(error)}), repository_after, run_id),
            )
            connection.execute(
                "UPDATE tasks SET state = ?, stop_reason = ?, updated_at = ? WHERE id = ?",
                (TaskState.BLOCKED, str(error), now, task_id),
            )
            self.database.event(
                connection, task_id, "RUN_FAILED", task["state"], TaskState.BLOCKED,
                {"type": type(error).__name__, "message": str(error)}, run_id,
            )

    def _transition(
        self,
        connection: sqlite3.Connection,
        task: dict[str, Any],
        action: NextAction,
        run_id: str,
        result: ProtocolResult,
    ) -> None:
        before = TaskState(task["state"])
        status = result.status
        updates: dict[str, Any] = {}

        if action.purpose in {Purpose.INITIAL_REVIEW, Purpose.REVISION_VERIFICATION}:
            if status == ReviewStatus.REQUEST_CHANGES:
                after = TaskState.WAITING_FOR_CODEX_REVISION
                updates["revision_cycle"] = task["revision_cycle"] + 1
                updates["pending_codex_purpose"] = Purpose.REVISION_VERIFICATION
            elif status in {ReviewStatus.APPROVE, ReviewStatus.APPROVE_WITH_MINOR_ISSUES}:
                if action.purpose == Purpose.REVISION_VERIFICATION:
                    connection.execute(
                        "UPDATE findings SET verification_run_id = ?, status = 'VERIFIED', resolved_at = ? "
                        "WHERE task_id = ? AND status = 'OPEN' AND source_run_id IN "
                        "(SELECT id FROM runs WHERE workflow_purpose IN (?, ?))",
                        (run_id, utc_now(), task["id"], Purpose.INITIAL_REVIEW, Purpose.REVISION_VERIFICATION),
                    )
                after = TaskState.READY_FOR_CHALLENGE
            else:
                after = TaskState.BLOCKED
                updates["stop_reason"] = result.summary or status
        elif action.purpose == Purpose.CHALLENGE:
            if status == "APPROVE":
                after, policy_updates = self._finish_challenge(
                    connection, task, material=False, promote=False,
                    stopping_reason="clean challenge approved after the configured minimum",
                )
                updates.update(policy_updates)
            elif status == "REQUEST_CHANGES":
                after = TaskState.READY_FOR_CHALLENGE_ADJUDICATION
            else:
                after = TaskState.BLOCKED
                updates["stop_reason"] = result.summary or status
        elif action.purpose == Purpose.CHALLENGE_ADJUDICATION:
            accepted = self._apply_dispositions(connection, task["id"], run_id, result)
            if status == ReviewStatus.BLOCKED or any(item.get("disposition") == Disposition.BLOCKED for item in result.dispositions):
                after = TaskState.BLOCKED
                updates["stop_reason"] = result.summary or "challenge adjudication blocked"
            elif accepted:
                after = TaskState.WAITING_FOR_CHALLENGE_REVISION
                updates["pending_codex_purpose"] = Purpose.CHALLENGE_REVISION
            else:
                after, policy_updates = self._finish_challenge(
                    connection, task, material=False, promote=False,
                    stopping_reason="all material challenge findings were rejected with evidence",
                )
                updates.update(policy_updates)
        elif action.purpose == Purpose.CHALLENGE_VERIFICATION:
            if status == ReviewStatus.REQUEST_CHANGES:
                after = TaskState.WAITING_FOR_CHALLENGE_REVISION
                updates["pending_codex_purpose"] = Purpose.CHALLENGE_REVISION
            elif status in {ReviewStatus.APPROVE, ReviewStatus.APPROVE_WITH_MINOR_ISSUES}:
                self._mark_verified(connection, task["id"], run_id)
                after, policy_updates = self._finish_challenge(
                    connection, task, material=True, promote=True,
                    stopping_reason="verified material corrections reached the configured challenge maximum",
                )
                updates.update(policy_updates)
            else:
                after = TaskState.BLOCKED
                updates["stop_reason"] = result.summary or status
        elif action.purpose == Purpose.FINAL_SUMMARY:
            if status == CompletionStatus.COMPLETED:
                after = TaskState.WAITING_FOR_HUMAN_REVIEW
                updates.update({
                    "final_title": result.title,
                    "stop_reason": task["stop_reason"] or "workflow completed; awaiting human review",
                    "completed_at": utc_now(),
                })
            else:
                after = TaskState.BLOCKED
                updates["stop_reason"] = result.summary or status
        else:
            raise WorkflowError(f"unsupported transition purpose: {action.purpose}")

        updates["state"] = after
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*updates.values(), task["id"]))
        self.database.event(connection, task["id"], "RUN_COMPLETED", before, after, result.to_dict(), run_id)

    def _finish_challenge(
        self, connection: sqlite3.Connection, task: dict[str, Any], *, material: bool, promote: bool,
        stopping_reason: str,
    ) -> tuple[TaskState, dict[str, Any]]:
        completed = task["challenge_cycle"] + 1
        minimum, maximum = RISK_PROFILES[task["risk_profile"]]
        updates: dict[str, Any] = {"challenge_cycle": completed}
        active = task["active_challenger_context_id"]
        if promote:
            updates.update({
                "review_frontier_context_id": active,
                "review_epoch": task["review_epoch"] + 1,
            })
        updates.update({"prior_review_context_id": None, "active_challenger_context_id": None})
        if completed < minimum or (material and completed < maximum):
            return TaskState.READY_FOR_CHALLENGE, updates
        updates["stop_reason"] = stopping_reason
        return TaskState.READY_FOR_FINAL_SUMMARY, updates

    def _codex_action(
        self, connection: sqlite3.Connection, task: dict[str, Any], purpose: Purpose, base_inputs: dict[str, Any]
    ) -> NextAction:
        context = self._context(connection, task["constructive_context_id"])
        source_purpose = Purpose.CHALLENGE_ADJUDICATION if purpose == Purpose.CHALLENGE_REVISION else Purpose.REVISION_VERIFICATION
        latest = self._latest_result(connection, task["id"], source_purpose, fallback_review=True)
        return NextAction(
            ActionOwner.CODEX, purpose, Protocol.UU_REVISE, None, context["lineage_label"], bool(context["is_fresh"]),
            {**base_inputs, "review_report": latest["cleaned_report"] or latest["raw_output"]},
            "Apply only verified findings in the active Codex constructive context.",
        )

    def _ensure_initial_reviewer(self, connection: sqlite3.Connection, task: dict[str, Any]) -> dict[str, Any]:
        if task["review_frontier_context_id"]:
            return self._context(connection, task["review_frontier_context_id"])
        context = self._create_reviewer(connection, task["id"], "R1", ContextClass.REVIEW, None)
        connection.execute(
            "UPDATE tasks SET review_frontier_context_id = ?, updated_at = ? WHERE id = ?",
            (context["id"], utc_now(), task["id"]),
        )
        return context

    def _ensure_challenger(self, connection: sqlite3.Connection, task: dict[str, Any]) -> dict[str, Any]:
        if task["active_challenger_context_id"]:
            context = self._context(connection, task["active_challenger_context_id"])
            if not context["is_fresh"]:
                raise WorkflowError("active challenger context was already used")
            return context
        count = connection.execute(
            "SELECT COUNT(*) FROM contexts WHERE task_id = ? AND context_class IN (?, ?)",
            (task["id"], ContextClass.REVIEW, ContextClass.FRESH_CHALLENGE),
        ).fetchone()[0]
        context = self._create_reviewer(
            connection, task["id"], f"R{count + 1}", ContextClass.FRESH_CHALLENGE,
            task["review_frontier_context_id"],
        )
        connection.execute(
            "UPDATE tasks SET active_challenger_context_id = ?, prior_review_context_id = ?, updated_at = ? WHERE id = ?",
            (context["id"], task["review_frontier_context_id"], utc_now(), task["id"]),
        )
        return context

    def _create_reviewer(
        self, connection: sqlite3.Connection, task_id: str, lineage: str, context_class: ContextClass,
        parent: str | None,
    ) -> dict[str, Any]:
        context_id = _uuid()
        session_id = new_session_id()
        connection.execute(
            "INSERT INTO contexts(id, task_id, lineage_label, context_class, adapter, harness, session_id, "
            "parent_context_id, created_at, is_fresh) VALUES (?, ?, ?, ?, 'claude', 'claude-code', ?, ?, ?, 1)",
            (context_id, task_id, lineage, context_class, session_id, parent, utc_now()),
        )
        return self._context(connection, context_id)

    @staticmethod
    def _context(connection: sqlite3.Connection, context_id: str | None) -> dict[str, Any]:
        if not context_id:
            raise WorkflowError("required context is missing")
        row = connection.execute("SELECT * FROM contexts WHERE id = ?", (context_id,)).fetchone()
        if not row:
            raise WorkflowError(f"unknown context: {context_id}")
        return dict(row)

    @staticmethod
    def _context_unused(connection: sqlite3.Connection, context_id: str) -> bool:
        return connection.execute("SELECT COUNT(*) FROM runs WHERE context_id = ?", (context_id,)).fetchone()[0] == 0

    @staticmethod
    def _task(connection: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise WorkflowError(f"unknown task: {task_id}")
        return dict(row)

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection, task_id: str) -> int:
        return connection.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM runs WHERE task_id = ?", (task_id,)
        ).fetchone()[0]

    @staticmethod
    def _latest_result(
        connection: sqlite3.Connection, task_id: str, purpose: Purpose, *, fallback_review: bool = False
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM runs WHERE task_id = ? AND workflow_purpose = ? AND status = 'COMPLETED' "
            "ORDER BY sequence_number DESC LIMIT 1", (task_id, purpose),
        ).fetchone()
        if not row and fallback_review:
            row = connection.execute(
                "SELECT * FROM runs WHERE task_id = ? AND protocol = ? AND status = 'COMPLETED' "
                "ORDER BY sequence_number DESC LIMIT 1", (task_id, Protocol.UU_REVIEW),
            ).fetchone()
        if not row:
            raise WorkflowError(f"no completed {purpose} result found")
        return dict(row)

    @staticmethod
    def _store_findings(
        connection: sqlite3.Connection, task_id: str, run_id: str, result: ProtocolResult
    ) -> None:
        for finding in result.findings:
            connection.execute(
                "INSERT INTO findings(id, external_id, task_id, source_run_id, priority, title, evidence, "
                "failure_scenario, impact, correction, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)",
                (
                    f"{run_id}:{finding['id']}", finding["id"], task_id, run_id, finding["priority"], finding["title"],
                    finding.get("evidence", ""),
                    finding.get("failure_scenario", ""), finding.get("impact", ""), finding.get("correction", ""), utc_now(),
                ),
            )

    @staticmethod
    def _apply_dispositions(
        connection: sqlite3.Connection, task_id: str, run_id: str, result: ProtocolResult
    ) -> bool:
        open_findings = {
            row["external_id"]: row["id"] for row in connection.execute(
                "SELECT f.id, f.external_id FROM findings f JOIN runs r ON r.id = f.source_run_id "
                "WHERE f.task_id = ? AND f.status = 'OPEN' AND r.workflow_purpose = ?",
                (task_id, Purpose.CHALLENGE),
            ).fetchall()
        }
        supplied = {item["finding_id"] for item in result.dispositions}
        if set(open_findings) != supplied:
            raise WorkflowError(
                f"challenge adjudication dispositions do not cover open findings: "
                f"expected {sorted(open_findings)}, got {sorted(supplied)}"
            )
        accepted = False
        for item in result.dispositions:
            disposition = item["disposition"]
            if disposition in {Disposition.ACCEPTED, Disposition.PARTIALLY_ACCEPTED}:
                accepted = True
            connection.execute(
                "UPDATE findings SET adjudication_run_id = ?, disposition = ?, disposition_evidence = ?, "
                "status = ?, resolved_at = ? WHERE task_id = ? AND id = ?",
                (
                    run_id, disposition, item["evidence"],
                    "ACCEPTED" if disposition in {Disposition.ACCEPTED, Disposition.PARTIALLY_ACCEPTED} else "RESOLVED",
                    None if disposition in {Disposition.ACCEPTED, Disposition.PARTIALLY_ACCEPTED} else utc_now(),
                    task_id, open_findings[item["finding_id"]],
                ),
            )
        return accepted

    @staticmethod
    def _mark_verified(connection: sqlite3.Connection, task_id: str, run_id: str) -> None:
        connection.execute(
            "UPDATE findings SET verification_run_id = ?, status = 'VERIFIED', resolved_at = ? "
            "WHERE task_id = ? AND status IN ('ACCEPTED', 'OPEN')",
            (run_id, utc_now(), task_id),
        )

    @staticmethod
    def _constructive_handoff(connection: sqlite3.Connection, task: dict[str, Any]) -> str:
        findings = [dict(row) for row in connection.execute(
            "SELECT external_id AS id, priority, title, disposition, disposition_evidence, status FROM findings "
            "WHERE task_id = ? ORDER BY created_at, external_id", (task["id"],)
        ).fetchall()]
        latest = connection.execute(
            "SELECT cleaned_report FROM runs WHERE task_id = ? AND cleaned_report IS NOT NULL "
            "ORDER BY sequence_number DESC LIMIT 1", (task["id"],)
        ).fetchone()
        return json.dumps({
            "canonical_plan_path": task["canonical_plan_path"],
            "repository_path": task["repository_path"],
            "current_state": task["state"],
            "review_epoch": task["review_epoch"],
            "findings": findings,
            "latest_report": latest["cleaned_report"] if latest else "",
        }, indent=2, sort_keys=True)
