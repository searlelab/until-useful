from __future__ import annotations

import json

from .database import Database, utc_now
from .git_state import snapshot


def render_report(database: Database, task_id: str, *, persist: bool = False) -> str:
    task = database.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not task:
        raise ValueError(f"unknown task: {task_id}")
    contexts = database.all(
        "SELECT lineage_label, context_class, harness, model_label, session_id, created_at, retired_at, retirement_reason "
        "FROM contexts WHERE task_id = ? ORDER BY created_at, lineage_label", (task_id,),
    )
    runs = database.all(
        "SELECT r.*, c.lineage_label FROM runs r LEFT JOIN contexts c ON c.id = r.context_id "
        "WHERE r.task_id = ? ORDER BY r.sequence_number", (task_id,),
    )
    findings = database.all(
        "SELECT external_id, priority, title, status, disposition, disposition_evidence, source_run_id, "
        "adjudication_run_id, verification_run_id FROM findings WHERE task_id = ? ORDER BY created_at, id",
        (task_id,),
    )
    runs_by_id = {run["id"]: run for run in runs}
    events = database.all(
        "SELECT event_type, state_before, state_after, details_json, created_at FROM events "
        "WHERE task_id = ? ORDER BY id", (task_id,),
    )
    try:
        git = snapshot(task["repository_path"]).to_dict()
    except RuntimeError as error:
        git = {"error": str(error)}

    lines = [
        f"# Until Useful workflow report: {task['title']}",
        "",
        "## Task and canonical plan",
        "",
        f"- Task ID: `{task_id}`",
        f"- Repository: `{task['repository_path']}`",
        f"- Canonical plan: `{task['canonical_plan_path']}`",
        f"- Risk profile: `{task['risk_profile']}`",
        "",
        "## Final status",
        "",
        f"- State: `{task['state']}`",
        f"- Suggested commit title: `{task['final_title'] or 'not available'}`",
        f"- Stop reason: {task['stop_reason'] or 'workflow still active'}",
        "",
        "## Timeline",
        "",
    ]
    if events:
        for event in events:
            transition = ""
            if event["state_before"] or event["state_after"]:
                transition = f" ({event['state_before'] or '—'} → {event['state_after'] or '—'})"
            lines.append(f"- {event['created_at']} — `{event['event_type']}`{transition}")
    else:
        lines.append("- No events recorded.")

    lines.extend(["", "## Context lineage", ""])
    for context in contexts:
        status = f"retired: {context['retirement_reason']}" if context["retired_at"] else "active/retained"
        lines.append(
            f"- `{context['lineage_label']}` — {context['context_class']}, {context['harness']}, "
            f"session `{context['session_id'] or 'host-owned'}`; {status}"
        )

    lines.extend([
        "",
        "## Revision and challenge cycles",
        "",
        f"- Revision cycles: {task['revision_cycle']}",
        f"- Completed challenge cycles: {task['challenge_cycle']}",
        f"- Current review epoch: {task['review_epoch']}",
        "",
        "## Implementation summary",
        "",
    ])
    codex_runs = [run for run in runs if run["protocol"] == "UU_REVISE"]
    if codex_runs:
        for run in codex_runs:
            lines.append(f"- {run['cleaned_report'] or 'Codex revision completed without a cleaned report.'}")
    else:
        lines.append("- The initial Codex implementation required no recorded revision cycle.")
    lines.extend([
        "",
        "## Protocol runs and validation",
        "",
    ])
    for run in runs:
        normalized = json.loads(run["normalized_result_json"] or "{}")
        checks = normalized.get("checks", [])
        lines.append(
            f"- #{run['sequence_number']} `{run['workflow_purpose']}` in `{run['lineage_label'] or 'unknown'}`: "
            f"{run['status']} / {normalized.get('status', 'no normalized status')}"
        )
        for check in checks:
            lines.append(f"  - Check: {json.dumps(check, sort_keys=True)}")

    lines.extend(["", "## Findings and dispositions", ""])
    if findings:
        for finding in findings:
            source = runs_by_id.get(finding["source_run_id"], {})
            adjudication = runs_by_id.get(finding["adjudication_run_id"], {})
            verification = runs_by_id.get(finding["verification_run_id"], {})
            implementer = "not applicable"
            if finding["disposition"] in {"ACCEPTED", "PARTIALLY_ACCEPTED"}:
                lower = adjudication.get("sequence_number", 0)
                upper = verification.get("sequence_number", 10**9)
                revision = next((
                    run for run in runs
                    if run["protocol"] == "UU_REVISE" and lower < run["sequence_number"] < upper
                ), None)
                implementer = revision["lineage_label"] if revision else "not recorded"
            lines.append(
                f"- `{finding['external_id']}` {finding['priority']} — {finding['title']}; status `{finding['status']}`, "
                f"disposition `{finding['disposition'] or 'pending'}`"
            )
            lines.append(
                f"  - Raised by `{source.get('lineage_label', 'unknown')}`; adjudicated by "
                f"`{adjudication.get('lineage_label', 'not adjudicated')}`; implemented by `{implementer}`; "
                f"verified by `{verification.get('lineage_label', 'not verified')}`."
            )
            if finding["disposition_evidence"]:
                lines.append(f"  - Evidence: {finding['disposition_evidence']}")
    else:
        lines.append("- No findings recorded.")

    refreshes = [event for event in events if event["event_type"] == "CONTEXT_REFRESHED"]
    lines.extend(["", "## Context refreshes", ""])
    if refreshes:
        for event in refreshes:
            detail = json.loads(event["details_json"])
            lines.append(f"- `{detail.get('from')}` → `{detail.get('to')}`: {detail.get('reason')}")
    else:
        lines.append("- No constructive-context refreshes.")

    residual: list[str] = []
    for run in runs:
        normalized = json.loads(run["normalized_result_json"] or "{}")
        residual.extend(normalized.get("residual_risks", []))
    lines.extend(["", "## Residual risk and stopping reason", ""])
    lines.append(f"- Challenge sequence stopped because: {task['stop_reason'] or 'not stopped'}")
    if residual:
        lines.extend(f"- {item}" for item in dict.fromkeys(residual))
    else:
        lines.append("- No residual risks were recorded by protocol results.")

    lines.extend([
        "",
        "## Human review checklist",
        "",
        "- Inspect the canonical plan and complete working-tree diff.",
        "- Confirm accepted findings were corrected and verified in the recorded contexts.",
        "- Review residual risks and any checks that were skipped or limited.",
        "- Stage and commit only after completing human review.",
        "",
        "## Repository status",
        "",
        "```json",
        json.dumps(git, indent=2, sort_keys=True),
        "```",
        "",
        "The Until Useful Runtime did not stage, commit, merge, rebase, or push changes.",
    ])
    report = "\n".join(lines) + "\n"
    if persist:
        with database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO reports(task_id, report_type, content, created_at) VALUES (?, 'FINAL_WORKFLOW', ?, ?)",
                (task_id, report, utc_now()),
            )
    return report
