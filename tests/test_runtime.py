from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from uu_runtime.adapters import AdapterError, ClaudeAdapter, FakeAdapter
from uu_runtime.database import Database, utc_now
from uu_runtime.engine import Runtime, WorkflowError
from uu_runtime.models import ActionOwner, NextAction, Protocol, Purpose, TaskState
from uu_runtime.reporting import render_report


def result(status: str, **extra: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": status,
        "summary": status.lower().replace("_", " "),
        "report_markdown": f"# {status}",
        "findings": [],
        "dispositions": [],
        "checks": [{"command": "unit", "result": "passed"}],
        "residual_risks": [],
        "title": "",
    }
    value.update(extra)
    return value


class RuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        subprocess.run(["git", "-C", str(self.repository), "config", "user.email", "tests@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repository), "config", "user.name", "Runtime Tests"], check=True)
        (self.repository / "README.md").write_text("fixture\n", encoding="utf-8")
        (self.repository / "docs").mkdir()
        (self.repository / "docs" / "uu-test.md").write_text("# Plan\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repository), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repository), "commit", "-qm", "fixture"], check=True)
        self.database = Database(self.root / "runtime.sqlite3")
        self.runtime = Runtime(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start(self, scenario: list[dict[str, object]], risk: str = "routine") -> str:
        status = self.runtime.start({
            "title": "Fixture task",
            "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md",
            "risk_profile": risk,
            "handoff_report": "Initial Codex implementation",
            "adapter": "fake",
            "adapter_config": {"scenario": scenario},
        })
        return status["task_id"]

    def record_codex(self, task_id: str, report: str = "Codex correction") -> None:
        self.runtime.record_codex_result(task_id, result("COMPLETED", report_markdown=report))

    def test_clean_workflow_reaches_human_review(self) -> None:
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Implement fixture workflow")},
        ])

        completed = self.runtime.resume(task_id)

        self.assertEqual(TaskState.WAITING_FOR_HUMAN_REVIEW, completed["status"]["state"])
        self.assertEqual("Implement fixture workflow", completed["status"]["final_title"])
        self.assertEqual(1, completed["status"]["challenge_cycle"])
        self.assertEqual(["P1", "R1", "R2"], [item["lineage_label"] for item in completed["status"]["contexts"]])
        stored = self.database.require_one(
            "SELECT COUNT(*) AS count FROM reports WHERE task_id = ? AND report_type = 'FINAL_WORKFLOW'", (task_id,)
        )
        self.assertEqual(1, stored["count"])

    def test_revision_and_material_challenge_promote_challenger(self) -> None:
        review_finding = {
            "id": "review-1", "priority": "P1", "title": "Initial defect", "evidence": "code",
            "failure_scenario": "input", "impact": "incorrect", "correction": "fix",
        }
        challenge_finding = {
            "id": "challenge-1", "priority": "P1", "title": "Missed defect", "evidence": "test",
            "failure_scenario": "edge", "impact": "incorrect", "correction": "fix edge",
        }
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("REQUEST_CHANGES", findings=[review_finding])},
            {"purpose": "REVISION_VERIFICATION", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[challenge_finding])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "REQUEST_CHANGES",
                dispositions=[{"finding_id": "challenge-1", "disposition": "ACCEPTED", "evidence": "reproduced"}],
            )},
            {"purpose": "CHALLENGE_VERIFICATION", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Correct fixture workflow")},
        ], risk="feature")

        first = self.runtime.resume(task_id)
        self.assertEqual(ActionOwner.CODEX, first["next_action"]["owner"])
        self.assertIn("# REQUEST_CHANGES", first["next_action"]["inputs"]["review_report"])
        self.record_codex(task_id, "Fixed initial defect")

        second = self.runtime.resume(task_id)
        self.assertEqual(ActionOwner.CODEX, second["next_action"]["owner"])
        self.assertEqual("CHALLENGE_REVISION", second["next_action"]["purpose"])
        self.record_codex(task_id, "Fixed accepted challenge")

        completed = self.runtime.resume(task_id)
        self.assertEqual(TaskState.WAITING_FOR_HUMAN_REVIEW, completed["status"]["state"])
        self.assertEqual(2, completed["status"]["challenge_cycle"])
        self.assertEqual(2, completed["status"]["review_epoch"])
        contexts = {item["lineage_label"]: item for item in completed["status"]["contexts"]}
        self.assertIn("R3", contexts)
        task = self.runtime.task(task_id)
        frontier = self.database.require_one("SELECT lineage_label FROM contexts WHERE id = ?", (task["review_frontier_context_id"],))
        self.assertEqual("R2", frontier["lineage_label"])
        findings = {
            item["external_id"]: item
            for item in self.database.all(
                "SELECT external_id, status, disposition FROM findings WHERE task_id = ?", (task_id,)
            )
        }
        self.assertEqual("VERIFIED", findings["review-1"]["status"])
        self.assertEqual("ACCEPTED", findings["challenge-1"]["disposition"])
        self.assertEqual("VERIFIED", findings["challenge-1"]["status"])

    def test_rejected_challenge_does_not_promote_challenger(self) -> None:
        finding = {
            "id": "challenge-rejected", "priority": "P1", "title": "Not a defect", "evidence": "claim",
            "failure_scenario": "none", "impact": "none", "correction": "none",
        }
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[finding])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "APPROVE",
                dispositions=[{"finding_id": "challenge-rejected", "disposition": "REJECTED", "evidence": "contradicted by test"}],
            )},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Keep correct behavior")},
        ])

        self.runtime.resume(task_id)

        task = self.runtime.task(task_id)
        frontier = self.database.require_one("SELECT lineage_label FROM contexts WHERE id = ?", (task["review_frontier_context_id"],))
        self.assertEqual("R1", frontier["lineage_label"])
        finding_row = self.database.one("SELECT status, disposition FROM findings WHERE task_id = ?", (task_id,))
        self.assertEqual({"status": "RESOLVED", "disposition": "REJECTED"}, finding_row)

    def test_reused_model_finding_ids_preserve_both_epochs(self) -> None:
        finding = {
            "id": "P1", "priority": "P1", "title": "Epoch-specific defect", "evidence": "test",
            "failure_scenario": "edge", "impact": "failure", "correction": "fix",
        }
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[finding])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "REQUEST_CHANGES", dispositions=[{"finding_id": "P1", "disposition": "ACCEPTED", "evidence": "valid"}],
            )},
            {"purpose": "CHALLENGE_VERIFICATION", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[finding])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "APPROVE", dispositions=[{"finding_id": "P1", "disposition": "REJECTED", "evidence": "not reproducible"}],
            )},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Preserve finding history")},
        ], risk="feature")
        self.runtime.resume(task_id)
        self.record_codex(task_id)
        self.runtime.resume(task_id)
        findings = self.database.all(
            "SELECT id, external_id, disposition FROM findings WHERE task_id = ? ORDER BY created_at", (task_id,)
        )
        self.assertEqual(2, len(findings))
        self.assertEqual(["P1", "P1"], [item["external_id"] for item in findings])
        self.assertNotEqual(findings[0]["id"], findings[1]["id"])
        self.assertEqual(["ACCEPTED", "REJECTED"], [item["disposition"] for item in findings])

    def test_challenger_verification_can_request_another_revision(self) -> None:
        challenge = {
            "id": "challenge-loop", "priority": "P1", "title": "Boundary bug", "evidence": "test",
            "failure_scenario": "boundary", "impact": "failure", "correction": "guard",
        }
        verification = {**challenge, "id": "verification-loop", "title": "Fix incomplete"}
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[challenge])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "REQUEST_CHANGES", dispositions=[{"finding_id": "challenge-loop", "disposition": "ACCEPTED", "evidence": "valid"}],
            )},
            {"purpose": "CHALLENGE_VERIFICATION", "result": result("REQUEST_CHANGES", findings=[verification])},
            {"purpose": "CHALLENGE_VERIFICATION", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Finish boundary fix")},
        ])
        self.runtime.resume(task_id)
        self.record_codex(task_id)
        retry = self.runtime.resume(task_id)
        self.assertEqual("CHALLENGE_REVISION", retry["next_action"]["purpose"])
        self.record_codex(task_id)
        completed = self.runtime.resume(task_id)
        self.assertEqual(TaskState.WAITING_FOR_HUMAN_REVIEW, completed["status"]["state"])

    def test_security_profile_requires_two_clean_challenges(self) -> None:
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE_WITH_MINOR_ISSUES", residual_risks=["P3 note"])},
            {"purpose": "CHALLENGE", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Audit fixture")},
        ], risk="security")
        completed = self.runtime.resume(task_id)
        self.assertEqual(2, completed["status"]["challenge_cycle"])

    def test_second_active_task_in_same_repository_is_rejected(self) -> None:
        self.start([])
        with self.assertRaises(sqlite3.IntegrityError):
            self.start([])

    def test_next_action_is_idempotent_and_challenge_has_no_narratives(self) -> None:
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
        ])
        first = self.runtime.next_action(task_id)
        again = self.runtime.next_action(task_id)
        self.assertEqual(first.context_id, again.context_id)
        self.runtime.execute_next(task_id)
        challenge = self.runtime.next_action(task_id)
        self.assertEqual(Purpose.CHALLENGE, challenge.purpose)
        self.assertEqual({"repository_path", "canonical_plan_path"}, set(challenge.inputs))
        self.assertNotEqual(first.context_id, challenge.context_id)

    def test_incomplete_adjudication_blocks_safely(self) -> None:
        finding = {
            "id": "uncovered", "priority": "P1", "title": "Defect", "evidence": "test",
            "failure_scenario": "edge", "impact": "failure", "correction": "fix",
        }
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[finding])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result("APPROVE")},
        ])
        with self.assertRaises(WorkflowError):
            self.runtime.resume(task_id)
        self.assertEqual(TaskState.BLOCKED, self.runtime.status(task_id)["state"])

    def test_runtime_restart_resumes_without_repeating_review(self) -> None:
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("REQUEST_CHANGES", findings=[{
                "id": "restart", "priority": "P1", "title": "Restart defect", "evidence": "test",
                "failure_scenario": "restart", "impact": "failure", "correction": "fix",
            }])},
            {"purpose": "REVISION_VERIFICATION", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Resume safely")},
        ])
        self.runtime.resume(task_id)
        restarted = Runtime(Database(self.database.path))
        restarted.record_codex_result(task_id, result("COMPLETED", report_markdown="Restart correction"))
        completed = restarted.resume(task_id)
        purposes = [item["workflow_purpose"] for item in self.database.all(
            "SELECT workflow_purpose FROM runs WHERE task_id = ? ORDER BY sequence_number", (task_id,)
        )]
        self.assertEqual(1, purposes.count("INITIAL_REVIEW"))
        self.assertEqual(TaskState.WAITING_FOR_HUMAN_REVIEW, completed["status"]["state"])

    def test_claude_adapter_detects_read_only_mutation(self) -> None:
        executable = self.root / "mutating-claude"
        executable.write_text(
            "#!/bin/sh\ntouch unexpected-change\nprintf '%s' "
            "' {\"status\":\"APPROVE\",\"summary\":\"ok\",\"report_markdown\":\"ok\","
            "\"findings\":[],\"dispositions\":[],\"checks\":[],\"residual_risks\":[],\"title\":\"\"}'\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        action = NextAction(
            ActionOwner.CLAUDE, Purpose.INITIAL_REVIEW, Protocol.UU_REVIEW,
            "00000000-0000-4000-8000-000000000001", "R1", True,
            {"repository_path": str(self.repository), "canonical_plan_path": "docs/uu-test.md", "handoff_report": "work"},
        )
        with self.assertRaisesRegex(AdapterError, "changed the repository"):
            ClaudeAdapter(executable=str(executable)).run(action, self.repository)

    def test_refresh_context_creates_compact_p2_handoff(self) -> None:
        task_id = self.start([])
        refreshed = self.runtime.refresh_context(task_id, "P1 became stale")
        self.assertEqual(["P1", "P2"], [item["lineage_label"] for item in refreshed["status"]["contexts"]])
        handoff = json.loads(refreshed["handoff"])
        self.assertEqual("docs/uu-test.md", handoff["canonical_plan_path"])
        self.assertNotIn("transcript", handoff)

    def test_global_active_run_constraint(self) -> None:
        first = self.start([])
        second_repository = self.root / "repo-2"
        subprocess.run(["git", "clone", "-q", str(self.repository), str(second_repository)], check=True)
        second = self.runtime.start({
            "title": "Second fixture task",
            "repository_path": str(second_repository),
            "canonical_plan_path": "docs/uu-test.md",
            "risk_profile": "routine",
            "handoff_report": "Second implementation",
            "adapter": "fake",
            "adapter_config": {"scenario": []},
        })["task_id"]
        with self.database.transaction(immediate=True) as connection:
            context = connection.execute("SELECT constructive_context_id FROM tasks WHERE id = ?", (first,)).fetchone()[0]
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, started_at) "
                "VALUES ('active-1', ?, ?, 'UU_REVISE', 'REVISION_VERIFICATION', 1, 'RUNNING', ?)",
                (first, context, utc_now()),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.transaction(immediate=True) as connection:
                context = connection.execute("SELECT constructive_context_id FROM tasks WHERE id = ?", (second,)).fetchone()[0]
                connection.execute(
                    "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, started_at) "
                    "VALUES ('active-2', ?, ?, 'UU_REVISE', 'REVISION_VERIFICATION', 1, 'RUNNING', ?)",
                    (second, context, utc_now()),
                )

    def test_interrupted_run_is_marked_and_blocks_safely(self) -> None:
        task_id = self.start([])
        with self.database.transaction(immediate=True) as connection:
            context = connection.execute("SELECT constructive_context_id FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, started_at) "
                "VALUES ('interrupted', ?, ?, 'UU_REVISE', 'REVISION_VERIFICATION', 1, 'RUNNING', ?)",
                (task_id, context, utc_now()),
            )
        recovered = self.runtime.recover_interrupted(task_id, "process exited during run")
        self.assertEqual(TaskState.BLOCKED, recovered["state"])
        run = self.database.require_one("SELECT status, repository_after_json FROM runs WHERE id = 'interrupted'")
        self.assertEqual("INTERRUPTED", run["status"])
        self.assertTrue(run["repository_after_json"])

    def test_malformed_fake_result_blocks_task(self) -> None:
        task_id = self.start([{"purpose": "INITIAL_REVIEW", "result": result("NOT_A_STATUS")}])
        with self.assertRaises(AdapterError):
            self.runtime.execute_next(task_id)
        self.assertEqual(TaskState.BLOCKED, self.runtime.status(task_id)["state"])

    def test_report_contains_required_sections_and_exact_title(self) -> None:
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Exact title")},
        ])
        self.runtime.resume(task_id)
        report = render_report(self.database, task_id)
        for heading in (
            "Task and canonical plan", "Final status", "Timeline", "Context lineage",
            "Revision and challenge cycles", "Findings and dispositions", "Residual risk",
            "Human review checklist", "Repository status",
        ):
            self.assertIn(heading, report)
        self.assertIn("Exact title", report)
        self.assertIn("did not stage, commit, merge, rebase, or push", report)


if __name__ == "__main__":
    unittest.main()
