from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from uu_runtime.adapters import ClaudeAdapter, new_session_id
from uu_runtime.models import ActionOwner, NextAction, Protocol, Purpose


@unittest.skipUnless(os.environ.get("UU_RUNTIME_CLAUDE_SMOKE") == "1", "set UU_RUNTIME_CLAUDE_SMOKE=1 for live Claude tests")
class ClaudeSmokeTest(unittest.TestCase):
    def test_create_resume_fresh_and_summarize(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.email", "smoke@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.name", "Smoke Test"], check=True)
            (repository / "docs").mkdir()
            (repository / "docs" / "uu-smoke.md").write_text("# Smoke plan\nNo implementation changes are required.\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "smoke fixture"], check=True)
            adapter = ClaudeAdapter(timeout=600)
            review_session = new_session_id()
            base = {"repository_path": str(repository), "canonical_plan_path": "docs/uu-smoke.md"}
            review = adapter.run(NextAction(
                ActionOwner.CLAUDE, Purpose.INITIAL_REVIEW, Protocol.UU_REVIEW,
                review_session, "R1", True, {**base, "handoff_report": "No-op smoke implementation."},
            ), repository)
            self.assertIn(review.result.status, {"APPROVE", "APPROVE_WITH_MINOR_ISSUES", "REQUEST_CHANGES", "BLOCKED"})
            challenge_session = new_session_id()
            challenge = adapter.run(NextAction(
                ActionOwner.CLAUDE, Purpose.CHALLENGE, Protocol.UU_SECOND_OPINION,
                challenge_session, "R2", True, base,
            ), repository)
            self.assertNotEqual(review_session, challenge_session)
            self.assertIn(challenge.result.status, {"APPROVE", "REQUEST_CHANGES", "BLOCKED"})
            summary = adapter.run(NextAction(
                ActionOwner.CLAUDE, Purpose.FINAL_SUMMARY, Protocol.UU_SUMMARIZE,
                review_session, "R1", False, base,
            ), repository)
            self.assertIn(summary.result.status, {"COMPLETED", "NO_CURRENT_CHANGESET", "BLOCKED"})
