from __future__ import annotations

import json
import io
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uu_runtime.adapters import AdapterError, AdapterRun, ClaudeAdapter, HarnessExhaustedError, result_schema, validate_result
from uu_runtime.database import Database, utc_now
from uu_runtime.cli import doctor, main as cli_main
from uu_runtime.engine import Runtime, WorkflowError
from uu_runtime.git_state import same_worktree, snapshot
from uu_runtime.models import ActionOwner, NextAction, Protocol, ProtocolResult, Purpose, TaskState, pipeline_outcome
from uu_runtime.policy import ClaudePolicy, load_policy, model_satisfies, parse_version, select_observed_model
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

    def review_action(self) -> NextAction:
        return NextAction(
            ActionOwner.CLAUDE, Purpose.INITIAL_REVIEW, Protocol.UU_REVIEW,
            "00000000-0000-4000-8000-000000000001", "R1", True,
            {
                "repository_path": str(self.repository),
                "canonical_plan_path": "docs/uu-test.md",
                "handoff_report": "work",
            },
        )

    def executable(self, name: str, body: str) -> Path:
        executable = self.root / name
        executable.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        executable.chmod(0o755)
        return executable

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
        self.assertEqual("APPROVE", completed["status"]["outcome"])

    def test_pipeline_outcomes_are_independent_of_manual_statuses(self) -> None:
        self.assertEqual("IN_PROGRESS", pipeline_outcome(TaskState.READY_FOR_INITIAL_REVIEW))
        self.assertEqual("APPROVE", pipeline_outcome(TaskState.WAITING_FOR_HUMAN_REVIEW))
        self.assertEqual("NEEDS_INPUT", pipeline_outcome(TaskState.NEEDS_INPUT))
        self.assertEqual("NEEDS_INPUT", pipeline_outcome(TaskState.BLOCKED))
        self.assertEqual("FAILED", pipeline_outcome(TaskState.FAILED))
        self.assertEqual("STOPPED", pipeline_outcome(TaskState.STOPPED))

    def test_plan_registration_precedes_initial_implementation(self) -> None:
        status = self.runtime.register_plan({
            "title": "Early fixture task",
            "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md",
            "risk_profile": "routine",
            "adapter": "fake",
            "adapter_config": {"scenario": []},
        })
        task_id = status["task_id"]
        action = self.runtime.next_action(task_id)
        self.assertEqual(TaskState.WAITING_FOR_INITIAL_IMPLEMENTATION, status["state"])
        self.assertEqual(ActionOwner.CODEX, action.owner)
        self.assertEqual(Purpose.INITIAL_IMPLEMENTATION, action.purpose)
        completed = self.runtime.record_codex_result(task_id, result("COMPLETED", report_markdown="Initial draft"))
        self.assertEqual(TaskState.READY_FOR_INITIAL_REVIEW, completed["state"])
        self.assertEqual("Initial draft", self.runtime.task(task_id)["initial_handoff"])
        self.assertEqual([], [item for item in completed["contexts"] if item["context_class"] == "REVIEW"])

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

    def test_challenge_verification_pauses_after_three_failed_corrections(self) -> None:
        challenge = {
            "id": "bounded-loop", "priority": "P1", "title": "Persistent defect", "evidence": "test",
            "failure_scenario": "boundary", "impact": "failure", "correction": "fix",
        }
        scenario: list[dict[str, object]] = [
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[challenge])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "REQUEST_CHANGES",
                dispositions=[{"finding_id": "bounded-loop", "disposition": "ACCEPTED", "evidence": "valid"}],
            )},
        ]
        for attempt in range(3):
            scenario.append({"purpose": "CHALLENGE_VERIFICATION", "result": result(
                "REQUEST_CHANGES", findings=[{**challenge, "id": f"still-broken-{attempt}"}],
            )})
        task_id = self.start(scenario)
        self.runtime.resume(task_id)
        for _ in range(3):
            self.record_codex(task_id)
            resumed = self.runtime.resume(task_id)

        self.assertEqual(TaskState.NEEDS_INPUT, resumed["status"]["state"])
        self.assertIn("requested changes 3 times", resumed["status"]["stop_reason"])

    def test_accepted_p2_does_not_force_an_extra_challenge(self) -> None:
        material = {
            "id": "material-challenge", "priority": "P1", "title": "Rejected material issue", "evidence": "test",
            "failure_scenario": "none", "impact": "none", "correction": "none",
        }
        challenge = {
            "id": "minor-challenge", "priority": "P2", "title": "Limited issue", "evidence": "test",
            "failure_scenario": "rare", "impact": "limited", "correction": "fix",
        }
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE")},
            {"purpose": "CHALLENGE", "result": result("REQUEST_CHANGES", findings=[material, challenge])},
            {"purpose": "CHALLENGE_ADJUDICATION", "result": result(
                "REQUEST_CHANGES",
                dispositions=[
                    {"finding_id": "material-challenge", "disposition": "REJECTED", "evidence": "not reproducible"},
                    {"finding_id": "minor-challenge", "disposition": "ACCEPTED", "evidence": "valid"},
                ],
            )},
            {"purpose": "CHALLENGE_VERIFICATION", "result": result("APPROVE")},
            {"purpose": "FINAL_SUMMARY", "result": result("COMPLETED", title="Finish minor correction")},
        ], risk="feature")
        self.runtime.resume(task_id)
        self.record_codex(task_id)
        completed = self.runtime.resume(task_id)
        self.assertEqual(TaskState.WAITING_FOR_HUMAN_REVIEW, completed["status"]["state"])
        self.assertEqual(1, completed["status"]["challenge_cycle"])
        self.assertNotIn("R3", [item["lineage_label"] for item in completed["status"]["contexts"]])

    def test_security_profile_requires_two_clean_challenges(self) -> None:
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("APPROVE_WITH_MINOR_ISSUES", findings=[{
                "id": "P3-note", "priority": "P3", "title": "Minor note", "evidence": "limited",
                "failure_scenario": "rare", "impact": "minor", "correction": "follow up",
            }], residual_risks=["P3 note"])},
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
        with self.assertRaises(AdapterError):
            self.runtime.resume(task_id)
        self.assertEqual(TaskState.NEEDS_INPUT, self.runtime.status(task_id)["state"])

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
            "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo unknown; exit 0; fi\n"
            "touch unexpected-change\nprintf '%s' "
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

    def test_snapshot_detects_changes_to_an_already_dirty_file(self) -> None:
        readme = self.repository / "README.md"
        readme.write_text("first dirty value\n", encoding="utf-8")
        before = snapshot(self.repository)
        readme.write_text("second dirty value\n", encoding="utf-8")
        self.assertFalse(same_worktree(before, snapshot(self.repository)))

    def test_protocol_schema_constrains_exact_status_tokens(self) -> None:
        self.assertEqual(
            {"APPROVE", "APPROVE_WITH_MINOR_ISSUES", "REQUEST_CHANGES", "BLOCKED"},
            set(result_schema(Protocol.UU_REVIEW)["properties"]["status"]["enum"]),
        )
        self.assertEqual(
            {"APPROVE", "REQUEST_CHANGES", "BLOCKED"},
            set(result_schema(Protocol.UU_SECOND_OPINION)["properties"]["status"]["enum"]),
        )
        schema = result_schema(Protocol.UU_REVIEW, Purpose.INITIAL_REVIEW)
        self.assertNotIn("allOf", schema)
        self.assertNotIn("if", schema)
        self.assertEqual(["P0", "P1", "P2", "P3"], schema["properties"]["findings"]["items"]["properties"]["priority"]["enum"])
        self.assertEqual(0, schema["properties"]["dispositions"]["maxItems"])
        self.assertEqual(
            ["ACCEPTED", "ALREADY_RESOLVED", "BLOCKED", "PARTIALLY_ACCEPTED", "REJECTED"],
            schema["properties"]["dispositions"]["items"]["properties"]["disposition"]["enum"],
        )
        adjudication = result_schema(
            Protocol.UU_REVIEW, Purpose.CHALLENGE_ADJUDICATION, {"challenge-1", "challenge-2"},
        )
        self.assertEqual(2, adjudication["properties"]["dispositions"]["minItems"])
        self.assertEqual(
            ["challenge-1", "challenge-2"],
            adjudication["properties"]["dispositions"]["items"]["properties"]["finding_id"]["enum"],
        )

    def test_observed_malformed_review_tokens_are_rejected(self) -> None:
        malformed = ProtocolResult.from_dict(result(
            "APPROVE",
            findings=[{
                "id": "F1", "priority": "minor", "title": "Dead markup", "evidence": "template",
                "failure_scenario": "none", "impact": "low", "correction": "remove",
            }],
            dispositions=[{"finding_id": "F1", "disposition": "accepted_minor", "evidence": "confirmed"}],
        ))
        with self.assertRaisesRegex(AdapterError, "invalid finding priority"):
            validate_result(Protocol.UU_REVIEW, malformed, Purpose.INITIAL_REVIEW)

    def test_model_policy_uses_role_profiles_and_rejects_unsafe_commands(self) -> None:
        policy = load_policy(self.repository)
        self.assertEqual("sonnet", policy.profile("review").model)
        self.assertEqual("medium", policy.profile("review").effort)
        self.assertEqual("opus", policy.profile("second_opinion").model)
        self.assertEqual("medium", policy.profile("second_opinion").effort)
        self.assertEqual("haiku", policy.profile("summarize").model)
        self.assertIsNone(policy.profile("summarize").effort)
        self.assertTrue(model_satisfies("claude-opus-5", policy.profile("second_opinion")))
        self.assertFalse(model_satisfies("claude-opus-4-1-20250805", policy.profile("second_opinion")))
        self.assertEqual((2, 1, 219), parse_version("2.1.219 (Claude Code)"))
        (self.repository / ".until-useful.toml").write_text(
            '[claude]\nallowed_commands = ["python -m unittest; rm file"]\n', encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "unsafe Claude command"):
            load_policy(self.repository)
        (self.repository / ".until-useful.toml").unlink()
        with self.assertRaisesRegex(ValueError, "narrow Git inspection"):
            load_policy(self.repository, {"allowed_commands": ["git -C elsewhere status"]})

    def test_model_selection_accepts_requested_family_among_auxiliary_usage(self) -> None:
        selected, reported = select_observed_model(
            {"claude-haiku-4-5-20251001": {}, "claude-opus-5": {}},
            ClaudePolicy().profile("second_opinion"),
        )
        self.assertEqual("claude-opus-5", selected)
        self.assertEqual(["claude-haiku-4-5-20251001", "claude-opus-5"], reported)

    def test_model_override_uses_the_selected_family_floor(self) -> None:
        (self.repository / ".until-useful.toml").write_text(
            '[claude]\nmodel = "opus"\nminimum_model = "claude-opus-5"\n', encoding="utf-8",
        )
        policy = load_policy(self.repository, {"model": "haiku", "minimum_model": None})
        self.assertEqual("haiku", policy.model)
        self.assertEqual("claude-haiku-4-5", policy.minimum_model)
        self.assertTrue(all(profile.model == "haiku" for profile in policy.roles.values()))

    def test_role_override_changes_only_the_selected_automated_profile(self) -> None:
        policy = load_policy(self.repository, {"roles": {"review": {"model": "haiku"}}})
        self.assertEqual("haiku", policy.profile("review").model)
        self.assertEqual("opus", policy.profile("second_opinion").model)
        self.assertEqual("haiku", policy.profile("summarize").model)

    def test_full_model_ids_require_and_honor_explicit_pins(self) -> None:
        with self.assertRaisesRegex(ValueError, "require pin_model"):
            load_policy(self.repository, {"model": "claude-opus-5-20260701"})
        policy = load_policy(self.repository, {"model": "claude-opus-5-20260701", "pin_model": True})
        self.assertTrue(policy.pin_model)
        self.assertTrue(model_satisfies("claude-opus-5-20260701", policy))
        self.assertFalse(model_satisfies("claude-opus-5-20260702", policy))

    def test_outdated_claude_blocks_with_update_guidance(self) -> None:
        executable = self.executable(
            "old-claude",
            'if [ "$1" = "--version" ]; then echo "2.1.218 (Claude Code)"; exit 0; fi\nexit 99',
        )
        with self.assertRaisesRegex(AdapterError, r"claude update"):
            ClaudeAdapter(executable=str(executable), enforce_model=True).run(self.review_action(), self.repository)

    def test_doctor_marks_logged_out_claude_as_unready_with_recovery_guidance(self) -> None:
        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, stdout="2.1.219\n", stderr="")
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps({"loggedIn": False, "authMethod": "none"}), stderr="",
            )

        with patch("uu_runtime.cli.shutil.which", return_value="/usr/bin/claude"), \
             patch("uu_runtime.cli.subprocess.run", side_effect=fake_run):
            result = doctor(str(self.database.path), str(self.repository), live=True)

        authentication = next(check for check in result["checks"] if check["name"] == "claude_authentication")
        self.assertFalse(authentication["ok"])
        self.assertFalse(authentication["detail"]["loggedIn"])
        self.assertIn("interactive_login", authentication["guidance"])
        self.assertIn("one-year token", authentication["guidance"]["automation"])

    def test_model_substitution_blocks_before_result_advances(self) -> None:
        executable = self.executable(
            "substituting-claude",
            '''if [ "$1" = "--version" ]; then echo "2.1.220 (Claude Code)"; exit 0; fi
printf '%s' '{"structured_output":{"status":"APPROVE","summary":"ok","report_markdown":"ok","findings":[],"dispositions":[],"checks":[],"residual_risks":[],"title":""},"usage":{},"modelUsage":{"claude-opus-5-20260601":{}}}' ''',
        )
        skill_root = self.root / "substitution-skills"
        (skill_root / "uu-review").mkdir(parents=True)
        (skill_root / "uu-review" / "SKILL.md").write_text("# Review\n", encoding="utf-8")
        with self.assertRaisesRegex(AdapterError, "model mismatch"):
            ClaudeAdapter(
                executable=str(executable), policy=ClaudePolicy(), enforce_model=True, skill_root=skill_root,
            ).run(self.review_action(), self.repository)

    def test_claude_adapter_rejects_malformed_json(self) -> None:
        executable = self.executable("malformed-claude", "printf 'not json'")
        with self.assertRaisesRegex(AdapterError, "malformed JSON"):
            ClaudeAdapter(executable=str(executable)).run(self.review_action(), self.repository)

    def test_claude_adapter_rejects_schema_mismatch(self) -> None:
        executable = self.executable(
            "wrong-schema-claude",
            "printf '%s' '{\"status\":\"REQUEST CHANGES\",\"summary\":\"bad token\"}'",
        )
        with self.assertRaisesRegex(AdapterError, "invalid UU_REVIEW status"):
            ClaudeAdapter(executable=str(executable)).run(self.review_action(), self.repository)

    def test_claude_adapter_timeout_is_exhaustion_pause(self) -> None:
        executable = self.executable("slow-claude", "sleep 1")
        with self.assertRaisesRegex(HarnessExhaustedError, "paused without retry"):
            ClaudeAdapter(executable=str(executable), timeout=0.01).run(self.review_action(), self.repository)

    def test_claude_adapter_token_exhaustion_is_explicit(self) -> None:
        executable = self.executable("exhausted-claude", "echo 'context window exceeded' >&2\nexit 1")
        task_id = self.runtime.start({
            "title": "Exhausted Claude task",
            "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md",
            "risk_profile": "routine",
            "handoff_report": "Initial implementation",
            "adapter": "claude",
            "adapter_config": {"executable": str(executable)},
        })["task_id"]
        with self.assertRaisesRegex(HarnessExhaustedError, "token budget"):
            self.runtime.execute_next(task_id)
        status = self.runtime.status(task_id)
        runs = self.database.all("SELECT status, error_json FROM runs WHERE task_id = ?", (task_id,))
        self.assertEqual(TaskState.NEEDS_INPUT, status["state"])
        self.assertEqual(1, len(runs))
        self.assertEqual("FAILED", runs[0]["status"])
        self.assertIn("HarnessExhaustedError", runs[0]["error_json"])

    def test_claude_adapter_passes_review_profile_and_injects_skill_contract(self) -> None:
        arguments = self.root / "arguments.txt"
        executable = self.executable(
            "current-claude",
            f'''if [ "$1" = "--version" ]; then echo "2.1.219 (Claude Code)"; exit 0; fi
printf '%s\\n' "$@" > "{arguments}"
printf '%s' '{{"structured_output":{{"status":"APPROVE","summary":"ok","report_markdown":"ok","findings":[],"dispositions":[],"checks":[],"residual_risks":[],"title":""}},"usage":{{}},"modelUsage":{{"claude-sonnet-5":{{}}}}}}' ''',
        )
        skill_root = self.root / "skills"
        (skill_root / "uu-review").mkdir(parents=True)
        (skill_root / "uu-review" / "SKILL.md").write_text("# Unique review contract\n", encoding="utf-8")
        adapter = ClaudeAdapter(
            executable=str(executable), policy=ClaudePolicy(), enforce_model=True, skill_root=skill_root,
        )
        run = adapter.run(self.review_action(), self.repository)
        values = arguments.read_text(encoding="utf-8").splitlines()
        self.assertEqual("claude-sonnet-5", run.usage["observed_model"])
        self.assertIn("--model", values)
        self.assertEqual("sonnet", values[values.index("--model") + 1])
        self.assertEqual("medium", values[values.index("--effort") + 1])
        invocation = arguments.read_text(encoding="utf-8")
        self.assertIn("Unique review contract", invocation)
        self.assertNotIn("/uu-review", invocation)
        allowed = values[values.index("--allowedTools") + 1]
        self.assertNotIn(",Bash,", f",{allowed},")
        self.assertIn("Bash(git diff:*)", allowed)

    def test_automated_protocols_route_to_role_specific_models_and_effort(self) -> None:
        skill_root = self.root / "role-skills"
        for name in ("uu-review", "uu-second-opinion", "uu-summarize"):
            (skill_root / name).mkdir(parents=True)
            (skill_root / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        cases = (
            (Protocol.UU_REVIEW, Purpose.INITIAL_REVIEW, "sonnet", "claude-sonnet-5", "medium"),
            (Protocol.UU_SECOND_OPINION, Purpose.CHALLENGE, "opus", "claude-opus-5", "medium"),
            (Protocol.UU_SUMMARIZE, Purpose.FINAL_SUMMARY, "haiku", "claude-haiku-4-5", None),
        )
        for index, (protocol, purpose, alias, observed, effort) in enumerate(cases):
            arguments = self.root / f"role-{index}.txt"
            title = "title" if protocol == Protocol.UU_SUMMARIZE else ""
            executable = self.executable(
                f"role-claude-{index}",
                f'''if [ "$1" = "--version" ]; then echo "2.1.220 (Claude Code)"; exit 0; fi
printf '%s\\n' "$@" > "{arguments}"
printf '%s' '{{"structured_output":{{"status":"{'COMPLETED' if protocol == Protocol.UU_SUMMARIZE else 'APPROVE'}","summary":"ok","report_markdown":"ok","findings":[],"dispositions":[],"checks":[],"residual_risks":[],"title":"{title}"}},"usage":{{}},"modelUsage":{{"{observed}":{{}}}}}}' ''',
            )
            inputs = {"repository_path": str(self.repository), "canonical_plan_path": "docs/uu-test.md"}
            if purpose == Purpose.INITIAL_REVIEW:
                inputs["handoff_report"] = "work"
            action = NextAction(
                ActionOwner.CLAUDE, purpose, protocol, f"00000000-0000-4000-8000-0000000000{index + 10}",
                f"R{index + 1}", purpose == Purpose.CHALLENGE, inputs,
            )
            ClaudeAdapter(
                executable=str(executable), policy=ClaudePolicy(), enforce_model=True, skill_root=skill_root,
            ).run(action, self.repository)
            values = arguments.read_text(encoding="utf-8").splitlines()
            self.assertEqual(alias, values[values.index("--model") + 1])
            if effort:
                self.assertEqual(effort, values[values.index("--effort") + 1])
            else:
                self.assertNotIn("--effort", values)

    def test_runtime_repairs_one_invalid_structured_result_without_tools(self) -> None:
        marker = self.root / "first-call-complete"
        arguments = self.root / "repair-arguments"
        executable = self.executable(
            "repairing-claude",
            f'''if [ "$1" = "--version" ]; then echo "2.1.219 (Claude Code)"; exit 0; fi
printf '%s\n' "$@" >> "{arguments}"
if [ -f "{marker}" ]; then
  printf '%s' '{{"structured_output":{{"status":"APPROVE","summary":"repaired","report_markdown":"repaired","findings":[],"dispositions":[],"checks":[],"residual_risks":[],"title":""}},"usage":{{}},"modelUsage":{{"claude-sonnet-5":{{}}}}}}'
else
  touch "{marker}"
  printf '%s' '{{"structured_output":{{"status":"APPROVE","summary":"bad","report_markdown":"bad","findings":[{{"id":"F1","priority":"minor","title":"bad","evidence":"e","failure_scenario":"f","impact":"i","correction":"c"}}],"dispositions":[{{"finding_id":"F1","disposition":"accepted_minor","evidence":"e"}}],"checks":[],"residual_risks":[],"title":""}},"usage":{{}},"modelUsage":{{"claude-sonnet-5":{{}}}}}}'
fi''',
        )
        skill_root = self.root / "repair-skills"
        (skill_root / "uu-review").mkdir(parents=True)
        (skill_root / "uu-review" / "SKILL.md").write_text("# Review\n", encoding="utf-8")
        task_id = self.runtime.start({
            "title": "Repair task", "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md", "risk_profile": "routine",
            "handoff_report": "draft", "adapter": "claude",
            "adapter_config": {
                "executable": str(executable), "skill_root": str(skill_root), "enforce_model": True,
            },
        })["task_id"]
        completed = self.runtime.execute_next(task_id)
        runs = self.database.all(
            "SELECT status, raw_output FROM runs WHERE task_id = ? ORDER BY sequence_number", (task_id,),
        )
        self.assertEqual(["INVALID_OUTPUT", "COMPLETED"], [item["status"] for item in runs])
        self.assertIn("accepted_minor", runs[0]["raw_output"])
        repair_invocation = arguments.read_text(encoding="utf-8")
        self.assertIn("--tools\n\n", repair_invocation)
        self.assertIn("Edit,Write,NotebookEdit,Bash,Read,Glob,Grep", repair_invocation)
        self.assertEqual(2, repair_invocation.count("--model\nsonnet"))
        self.assertIn("Exact validation diagnostic", repair_invocation)
        self.assertIn("accepted_minor", repair_invocation)
        self.assertEqual(TaskState.READY_FOR_CHALLENGE, completed["status"]["state"])

    def test_empty_observed_model_does_not_replace_recorded_context_model(self) -> None:
        task_id = self.start([])
        action = self.runtime.next_action(task_id)
        task = self.runtime.task(task_id)
        run_id = self.runtime._begin_run(task, action)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE contexts SET model_label = 'claude-sonnet-5' WHERE task_id = ? AND session_id = ?",
                (task_id, action.context_id),
            )
        current = snapshot(self.repository)
        adapter_run = AdapterRun(
            ProtocolResult.from_dict(result("APPROVE")), "{}", "", {"observed_model": ""}, current, current,
        )
        self.runtime._complete_run(task_id, run_id, action, adapter_run)
        context = self.database.require_one(
            "SELECT model_label FROM contexts WHERE task_id = ? AND session_id = ?", (task_id, action.context_id),
        )
        self.assertEqual("claude-sonnet-5", context["model_label"])

    def test_resume_after_crash_starts_pending_informed_repair_not_original_review(self) -> None:
        marker = self.root / "pending-repair-count"
        executable = self.executable(
            "pending-repair-claude",
            f'''if [ "$1" = "--version" ]; then echo "2.1.220 (Claude Code)"; exit 0; fi
printf x >> "{marker}"
printf '%s' '{{"structured_output":{{"status":"APPROVE","summary":"repaired","report_markdown":"repaired","findings":[],"dispositions":[],"checks":[],"residual_risks":[],"title":""}},"usage":{{}},"modelUsage":{{"claude-sonnet-5":{{}}}}}}' ''',
        )
        skill_root = self.root / "pending-repair-skills"
        (skill_root / "uu-review").mkdir(parents=True)
        (skill_root / "uu-review" / "SKILL.md").write_text("# Review\n", encoding="utf-8")
        task_id = self.runtime.start({
            "title": "Pending repair", "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md", "risk_profile": "routine",
            "handoff_report": "draft", "adapter": "claude",
            "adapter_config": {"executable": str(executable), "skill_root": str(skill_root), "enforce_model": True},
        })["task_id"]
        action = self.runtime.next_action(task_id)
        context = self.database.require_one(
            "SELECT id FROM contexts WHERE task_id = ? AND session_id = ?", (task_id, action.context_id),
        )
        bad = result("APPROVE", findings=[{
            "id": "F1", "priority": "minor", "title": "bad", "evidence": "e",
            "failure_scenario": "f", "impact": "i", "correction": "c",
        }])
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, "
                "started_at, finished_at, raw_output, normalized_result_json, error_json, validation_diagnostics_json) "
                "VALUES ('pending-source', ?, ?, 'UU_REVIEW', 'INITIAL_REVIEW', 1, 'INVALID_OUTPUT', ?, ?, ?, ?, ?, ?)",
                (task_id, context["id"], utc_now(), utc_now(), json.dumps(bad), json.dumps(bad),
                 json.dumps({"message": "invalid finding priority: minor"}),
                 json.dumps({"message": "invalid finding priority: minor"})),
            )
        completed = self.runtime.execute_next(task_id)
        self.assertEqual(TaskState.READY_FOR_CHALLENGE, completed["status"]["state"])
        self.assertEqual("x", marker.read_text(encoding="utf-8"))
        repair = self.database.require_one(
            "SELECT repair_of_run_id, repair_prompt_version FROM runs WHERE task_id = ? AND sequence_number = 2",
            (task_id,),
        )
        self.assertEqual("pending-source", repair["repair_of_run_id"])
        self.assertEqual(1, repair["repair_prompt_version"])

    def test_second_invalid_repair_is_preserved_and_cannot_retry(self) -> None:
        marker = self.root / "repair-call-count"
        executable = self.executable(
            "invalid-twice-claude",
            f'''if [ "$1" = "--version" ]; then echo "2.1.220 (Claude Code)"; exit 0; fi
printf x >> "{marker}"
printf '%s' '{{"structured_output":{{"status":"APPROVE","summary":"bad","report_markdown":"bad","findings":[{{"id":"F1","priority":"minor","title":"bad","evidence":"e","failure_scenario":"f","impact":"i","correction":"c"}}],"dispositions":[],"checks":[],"residual_risks":[],"title":""}},"usage":{{}},"modelUsage":{{"claude-sonnet-5":{{}}}}}}' ''',
        )
        skill_root = self.root / "invalid-twice-skills"
        (skill_root / "uu-review").mkdir(parents=True)
        (skill_root / "uu-review" / "SKILL.md").write_text("# Review\n", encoding="utf-8")
        task_id = self.runtime.start({
            "title": "Invalid twice", "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md", "risk_profile": "routine",
            "handoff_report": "draft", "adapter": "claude",
            "adapter_config": {
                "executable": str(executable), "skill_root": str(skill_root), "enforce_model": True,
            },
        })["task_id"]
        with self.assertRaises(AdapterError):
            self.runtime.execute_next(task_id)
        runs = self.database.all(
            "SELECT status, raw_output, normalized_result_json, usage_json FROM runs "
            "WHERE task_id = ? ORDER BY sequence_number", (task_id,),
        )
        self.assertEqual(["INVALID_OUTPUT", "INVALID_OUTPUT"], [item["status"] for item in runs])
        self.assertTrue(all(item["raw_output"] and item["normalized_result_json"] and item["usage_json"] for item in runs))
        self.assertEqual(TaskState.NEEDS_INPUT, self.runtime.status(task_id)["state"])
        with self.assertRaisesRegex(WorkflowError, "BLOCKED"):
            self.runtime.recover_invalid_output(task_id)
        self.assertEqual("xx", marker.read_text(encoding="utf-8"))

    def test_human_input_envelope_routes_preserved_p2_to_revision_verification(self) -> None:
        task_id = self.start([])
        action = self.runtime.next_action(task_id)
        context = self.database.require_one(
            "SELECT id FROM contexts WHERE task_id = ? AND session_id = ?", (task_id, action.context_id),
        )
        payload = result("APPROVE_WITH_MINOR_ISSUES", findings=[
            {"id": "F1", "priority": "P3", "title": "Dead markup", "evidence": "template",
             "failure_scenario": "none", "impact": "cleanup", "correction": "remove"},
            {"id": "F2", "priority": "P2", "title": "Duration cannot be changed", "evidence": "admin UI",
             "failure_scenario": "edit booking", "impact": "incorrect duration", "correction": "support edit"},
        ])
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, "
                "started_at, finished_at, normalized_result_json, error_json, validation_diagnostics_json) "
                "VALUES ('invalid-2', ?, ?, 'UU_REVIEW', 'INITIAL_REVIEW', 1, 'INVALID_OUTPUT', ?, ?, ?, ?, ?)",
                (task_id, context["id"], utc_now(), utc_now(), json.dumps(payload),
                 json.dumps({"type": "StructuredOutputError", "message": "requires only P3 findings"}),
                 json.dumps({"type": "StructuredOutputError", "message": "requires only P3 findings"})),
            )
            connection.execute(
                "UPDATE tasks SET state = 'NEEDS_INPUT', stop_reason = 'invalid after repair' WHERE id = ?", (task_id,),
            )
            self.database.event(
                connection, task_id, "RUN_INVALID_OUTPUT", TaskState.READY_FOR_INITIAL_REVIEW,
                TaskState.NEEDS_INPUT, {"message": "requires only P3 findings"}, "invalid-2",
            )
        provided = self.runtime.provide_input(task_id, "Treat the P2 as request changes")
        envelope = provided["next_action"]
        self.assertEqual("INPUT_RESOLUTION", envelope["purpose"])
        self.assertEqual("P2", envelope["inputs"]["preserved_payload"]["findings"][1]["priority"])
        self.assertIn("requires only P3", json.dumps(envelope["inputs"]["validation_diagnostics"]))
        resolved = self.runtime.record_input_resolution(task_id, {
            "decision": "REVISED", "summary": "Corrected duration editing",
            "report_markdown": "Implemented and tested editable expected_minutes.",
        })
        self.assertEqual(TaskState.READY_FOR_REVISION_VERIFICATION, resolved["state"])
        self.assertEqual("sonnet", resolved["model_policy"]["roles"]["review"]["model"] if resolved["model_policy"] else "sonnet")
        self.assertEqual("RESOLVED", self.database.require_one(
            "SELECT status FROM human_inputs WHERE task_id = ?", (task_id,),
        )["status"])

    def test_provide_input_upgrades_legacy_all_opus_task_to_role_profiles(self) -> None:
        task_id = self.runtime.start({
            "title": "Legacy model task", "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md", "risk_profile": "routine",
            "handoff_report": "draft", "adapter": "claude",
            "adapter_config": {"executable": "claude"},
        })["task_id"]
        legacy = {"model": "opus", "minimum_model": "claude-opus-5", "allowed_commands": ["git diff"]}
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE tasks SET state = 'NEEDS_INPUT', adapter_config_json = ? WHERE id = ?",
                (json.dumps(legacy), task_id),
            )
        provided = self.runtime.provide_input(task_id, "Route preserved P2 to revision")
        profiles = provided["status"]["model_policy"]["roles"]
        self.assertEqual("sonnet", profiles["review"]["model"])
        self.assertEqual("opus", profiles["second_opinion"]["model"])
        self.assertEqual("haiku", profiles["summarize"]["model"])

    def test_input_approve_requires_material_finding_dispositions(self) -> None:
        task_id = self.start([])
        action = self.runtime.next_action(task_id)
        context = self.database.require_one(
            "SELECT id FROM contexts WHERE task_id = ? AND session_id = ?", (task_id, action.context_id),
        )
        payload = result("APPROVE_WITH_MINOR_ISSUES", findings=[
            {"id": "F2", "priority": "P2", "title": "Material issue", "evidence": "code",
             "failure_scenario": "edge", "impact": "failure", "correction": "fix"},
            {"id": "F3", "priority": "P3", "title": "Minor issue", "evidence": "markup",
             "failure_scenario": "maintenance", "impact": "confusion", "correction": "cleanup"},
        ])
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, "
                "started_at, finished_at, normalized_result_json, error_json) "
                "VALUES ('approval-source', ?, ?, 'UU_REVIEW', 'INITIAL_REVIEW', 1, 'INVALID_OUTPUT', ?, ?, ?, ?)",
                (task_id, context["id"], utc_now(), utc_now(), json.dumps(payload),
                 json.dumps({"message": "requires only P3 findings"})),
            )
            connection.execute("UPDATE tasks SET state = 'NEEDS_INPUT' WHERE id = ?", (task_id,))
            self.database.event(
                connection, task_id, "RUN_INVALID_OUTPUT", TaskState.READY_FOR_INITIAL_REVIEW,
                TaskState.NEEDS_INPUT, {}, "approval-source",
            )
        self.runtime.provide_input(task_id, "Review preserved result")
        with self.assertRaisesRegex(WorkflowError, "evidence-backed dispositions"):
            self.runtime.record_input_resolution(task_id, {"decision": "APPROVE", "summary": "reject finding"})
        malformed = {
            "decision": "APPROVE", "summary": "Reject material and acknowledge minor",
            "dispositions": [
                {"finding_id": "F2", "disposition": "REJECTED", "evidence": "Regression passes"},
                {"finding_id": "F3", "disposition": "ACKNOWLEDGED"},
            ],
        }
        stderr = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(malformed))), patch("sys.stderr", stderr):
            exit_code = cli_main([
                "--database", str(self.database.path), "record-input-resolution", "--task", task_id, "--input", "-",
            ])
        self.assertEqual(2, exit_code)
        cli_error = json.loads(stderr.getvalue())
        self.assertEqual("WorkflowError", cli_error["error"])
        self.assertIn("requires finding_id, disposition, and evidence", cli_error["message"])
        self.assertNotIn("Traceback", stderr.getvalue())
        pending = self.database.require_one(
            "SELECT status FROM human_inputs WHERE task_id = ?", (task_id,),
        )
        self.assertEqual("PENDING", pending["status"])
        self.assertEqual(TaskState.WAITING_FOR_CODEX_INPUT_RESOLUTION, self.runtime.status(task_id)["state"])
        with self.assertRaisesRegex(WorkflowError, "invalid APPROVE disposition"):
            self.runtime.record_input_resolution(task_id, {
                "decision": "APPROVE", "summary": "Invalid minor disposition",
                "dispositions": [
                    {"finding_id": "F2", "disposition": "REJECTED", "evidence": "Regression passes"},
                    {"finding_id": "F3", "disposition": "ACKNOWLEDGED", "evidence": "Minor only"},
                ],
            })
        with self.assertRaisesRegex(WorkflowError, "concrete evidence"):
            self.runtime.record_input_resolution(task_id, {
                "decision": "APPROVE", "summary": "Empty minor evidence",
                "dispositions": [
                    {"finding_id": "F2", "disposition": "REJECTED", "evidence": "Regression passes"},
                    {"finding_id": "F3", "disposition": "REJECTED", "evidence": ""},
                ],
            })
        approved = self.runtime.record_input_resolution(task_id, {
            "decision": "APPROVE", "summary": "Finding contradicted by test",
            "dispositions": [{"finding_id": "F2", "disposition": "REJECTED", "evidence": "Regression passes"}],
        })
        self.assertEqual(TaskState.READY_FOR_CHALLENGE, approved["state"])
        stored = self.database.require_one(
            "SELECT disposition, disposition_evidence FROM findings WHERE task_id = ?", (task_id,),
        )
        self.assertEqual("REJECTED", stored["disposition"])

    def test_input_retry_and_failed_decisions_enforce_their_evidence(self) -> None:
        retry_task = self.start([])
        action = self.runtime.next_action(retry_task)
        task = self.runtime.task(retry_task)
        self.runtime._begin_run(task, action)
        interrupted = self.runtime.recover_interrupted(retry_task, "temporary network interruption")
        self.assertEqual(TaskState.NEEDS_INPUT, interrupted["state"])
        self.runtime.provide_input(retry_task, "Authentication and network are restored")
        retried = self.runtime.record_input_resolution(retry_task, {
            "decision": "RETRY", "summary": "Verified prerequisite is restored",
        })
        self.assertEqual(TaskState.READY_FOR_INITIAL_REVIEW, retried["state"])
        self.runtime.stop(retry_task, "retry decision test complete")

        failed_task = self.start([])
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE tasks SET state = 'NEEDS_INPUT' WHERE id = ?", (failed_task,))
        self.runtime.provide_input(failed_task, "Determine whether the approved task is solvable")
        with self.assertRaisesRegex(WorkflowError, "attempted_approaches"):
            self.runtime.record_input_resolution(failed_task, {"decision": "FAILED", "summary": "Cannot continue"})
        failed = self.runtime.record_input_resolution(failed_task, {
            "decision": "FAILED", "summary": "Approved task is impossible within repository scope",
            "attempted_approaches": ["Inspected all configured adapters"],
            "failure_evidence": ["Required provider capability is absent and guidance cannot add it"],
        })
        self.assertEqual(TaskState.FAILED, failed["state"])
        self.assertEqual("FAILED", failed["outcome"])

    def test_input_needs_input_requires_a_focused_question(self) -> None:
        task_id = self.start([])
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE tasks SET state = 'NEEDS_INPUT' WHERE id = ?", (task_id,))
        self.runtime.provide_input(task_id, "Clarify external prerequisite")
        with self.assertRaisesRegex(WorkflowError, "focused question"):
            self.runtime.record_input_resolution(task_id, {"decision": "NEEDS_INPUT", "summary": "still blocked"})
        status = self.runtime.record_input_resolution(task_id, {
            "decision": "NEEDS_INPUT", "summary": "Need one external choice",
            "question": "Which authenticated provider endpoint should this task use?",
        })
        self.assertEqual(TaskState.NEEDS_INPUT, status["state"])

    def test_schema_v1_migrates_to_v2_and_legacy_invalid_becomes_needs_input(self) -> None:
        path = self.root / "legacy.sqlite3"
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE tasks(id TEXT PRIMARY KEY, repository_path TEXT NOT NULL, state TEXT NOT NULL, updated_at TEXT);
            CREATE TABLE runs(id TEXT PRIMARY KEY, task_id TEXT, sequence_number INTEGER, status TEXT,
                error_json TEXT, validation_diagnostics_json_DO_NOT_USE TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY, task_id TEXT, event_type TEXT, details_json TEXT);
            CREATE UNIQUE INDEX one_active_task_per_repository ON tasks(repository_path)
                WHERE state NOT IN ('WAITING_FOR_HUMAN_REVIEW', 'BLOCKED', 'STOPPED');
            INSERT INTO tasks VALUES ('d1c8e617-ac17-4b08-bf10-f900d523b4c7', '/tmp/instrumenthub', 'BLOCKED', 'before');
            INSERT INTO runs(id, task_id, sequence_number, status, error_json) VALUES
                ('bad', 'd1c8e617-ac17-4b08-bf10-f900d523b4c7', 1, 'FAILED',
                 '{"type":"StructuredOutputError","message":"APPROVE_WITH_MINOR_ISSUES requires only P3 findings"}');
            PRAGMA user_version = 1;
        """)
        connection.commit()
        connection.close()
        Database(path).migrate()
        migrated = sqlite3.connect(path)
        self.assertEqual(2, migrated.execute("PRAGMA user_version").fetchone()[0])
        self.assertEqual("NEEDS_INPUT", migrated.execute("SELECT state FROM tasks").fetchone()[0])
        self.assertEqual("INVALID_OUTPUT", migrated.execute("SELECT status FROM runs").fetchone()[0])
        self.assertTrue(migrated.execute(
            "SELECT 1 FROM pragma_table_info('human_inputs') WHERE name = 'guidance'"
        ).fetchone())
        migrated.close()

    def test_portable_manual_skill_frontmatter_has_no_model_or_effort(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        for name in ("uu-plan", "uu-review", "uu-revise", "uu-second-opinion", "uu-summarize"):
            frontmatter = (repository_root / "skills" / name / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
            self.assertNotIn("model:", frontmatter)
            self.assertNotIn("effort:", frontmatter)
        installer = (repository_root / "install.sh").read_text(encoding="utf-8")
        self.assertIn("uu-build:Codex*|uu-input:Codex*", installer)

    def test_legacy_invalid_disposition_blocker_can_be_recovered(self) -> None:
        executable = self.executable(
            "legacy-repair-claude",
            '''if [ "$1" = "--version" ]; then echo "2.1.219 (Claude Code)"; exit 0; fi
printf '%s' '{"structured_output":{"status":"APPROVE","summary":"repaired","report_markdown":"repaired","findings":[],"dispositions":[],"checks":[],"residual_risks":[],"title":""},"usage":{},"modelUsage":{"claude-sonnet-5":{}}}' ''',
        )
        skill_root = self.root / "legacy-skills"
        (skill_root / "uu-review").mkdir(parents=True)
        (skill_root / "uu-review" / "SKILL.md").write_text("# Review\n", encoding="utf-8")
        task_id = self.runtime.start({
            "title": "Legacy task", "repository_path": str(self.repository),
            "canonical_plan_path": "docs/uu-test.md", "risk_profile": "routine",
            "handoff_report": "draft", "adapter": "claude",
            "adapter_config": {
                "executable": str(executable), "skill_root": str(skill_root), "enforce_model": True,
            },
        })["task_id"]
        action = self.runtime.next_action(task_id)
        context = self.database.require_one(
            "SELECT id FROM contexts WHERE task_id = ? AND session_id = ?", (task_id, action.context_id),
        )
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO runs(id, task_id, context_id, protocol, workflow_purpose, sequence_number, status, "
                "started_at, finished_at, error_json) VALUES ('legacy-invalid', ?, ?, ?, ?, 1, 'FAILED', ?, ?, ?)",
                (
                    task_id, context["id"], Protocol.UU_REVIEW, Purpose.INITIAL_REVIEW, utc_now(), utc_now(),
                    json.dumps({"type": "AdapterError", "message": "invalid finding disposition: accepted_minor"}),
                ),
            )
            connection.execute(
                "UPDATE tasks SET state = ?, stop_reason = ? WHERE id = ?",
                (TaskState.BLOCKED, "invalid finding disposition: accepted_minor", task_id),
            )
            self.database.event(
                connection, task_id, "RUN_FAILED", TaskState.READY_FOR_INITIAL_REVIEW, TaskState.BLOCKED,
                {"message": "invalid finding disposition: accepted_minor"}, "legacy-invalid",
            )
        recovered = self.runtime.recover_invalid_output(task_id)
        self.assertEqual(TaskState.READY_FOR_CHALLENGE, recovered["state"])
        self.assertEqual(
            ["FAILED", "COMPLETED"],
            [item["status"] for item in self.database.all(
                "SELECT status FROM runs WHERE task_id = ? ORDER BY sequence_number", (task_id,),
            )],
        )

    def test_duplicate_fresh_challenger_uuid_is_rejected(self) -> None:
        task_id = self.start([{"purpose": "INITIAL_REVIEW", "result": result("APPROVE")}])
        with patch("uu_runtime.engine.new_session_id", return_value="00000000-0000-4000-8000-000000000099"):
            self.runtime.next_action(task_id)
            self.runtime.execute_next(task_id)
            with self.assertRaisesRegex(WorkflowError, "duplicate Claude session UUID"):
                self.runtime.next_action(task_id)

    def test_blocked_codex_result_preserves_run_status_and_pauses(self) -> None:
        finding = {
            "id": "codex-context", "priority": "P1", "title": "Needs correction", "evidence": "test",
            "failure_scenario": "edge", "impact": "failure", "correction": "fix",
        }
        task_id = self.start([
            {"purpose": "INITIAL_REVIEW", "result": result("REQUEST_CHANGES", findings=[finding])},
        ])
        self.runtime.resume(task_id)
        status = self.runtime.record_codex_result(
            task_id,
            result("BLOCKED", summary="Codex context window exhausted", report_markdown="Context exhausted"),
        )
        run = self.database.require_one(
            "SELECT status FROM runs WHERE task_id = ? AND protocol = 'UU_REVISE'", (task_id,),
        )
        self.assertEqual("BLOCKED", run["status"])
        self.assertEqual(TaskState.NEEDS_INPUT, status["state"])
        self.assertIn("context window exhausted", status["stop_reason"])

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
        self.assertEqual(TaskState.NEEDS_INPUT, recovered["state"])
        run = self.database.require_one("SELECT status, repository_after_json FROM runs WHERE id = 'interrupted'")
        self.assertEqual("INTERRUPTED", run["status"])
        self.assertTrue(run["repository_after_json"])

    def test_malformed_fake_result_blocks_task(self) -> None:
        task_id = self.start([{"purpose": "INITIAL_REVIEW", "result": result("NOT_A_STATUS")}])
        with self.assertRaises(AdapterError):
            self.runtime.execute_next(task_id)
        self.assertEqual(TaskState.NEEDS_INPUT, self.runtime.status(task_id)["state"])

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
            "Human review checklist", "Repository status", "UU Summary result",
        ):
            self.assertIn(heading, report)
        self.assertIn("Exact title", report)
        self.assertIn("did not stage, commit, merge, rebase, or push", report)
        self.assertLess(report.rfind("Repository status"), report.rfind("UU Summary result"))
        self.assertTrue(report.rstrip().endswith("- Title: `Exact title`"))


if __name__ == "__main__":
    unittest.main()
