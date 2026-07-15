---
name: uu-review
description: Review a coding agent's changes against the canonical plan. Use only when manually invoked; do not modify the repository.
disable-model-invocation: true
user-invocable: true
---

# UU Review

Review the current changeset against its canonical `docs/uu-<task-slug>.md` plan. Treat pasted worker summaries and user notes as leads, not evidence.

## Rules

- Read repository instructions, the canonical plan, and the actual change surface. Do not edit, write, stage, commit, or push.
- Identify the changeset from context, status, diffs, untracked files, and history. If necessary, ask for the plan path or commit/range.
- Verify material worker claims and plan outcomes in code and tests. Prefer focused executable checks to assertions.
- Review only the intended changeset and necessary surrounding code. Report actionable issues, not preferences.

## Check

Look for missing plan outcomes, incorrect behavior, regressions, compatibility failures, unsafe edge cases, security or data-loss risks, concurrency defects, and missing meaningful tests. Ensure a regression test would fail without the fix. Use broader checks only when the change warrants them.

## Report

Lead with `APPROVE`, `APPROVE WITH MINOR ISSUES`, `REQUEST CHANGES`, or `BLOCKED`. Group related findings by priority:

- **P0:** catastrophic risk
- **P1:** blocking correctness or compatibility failure
- **P2:** defect or important missing coverage
- **P3:** limited-impact follow-up

For each finding, give evidence, failure scenario, impact, and correction. Then briefly state the plan/summary claim audit, checks actually run and outcomes, and residual risks. Use `REQUEST CHANGES` for P0–P2; use `APPROVE WITH MINOR ISSUES` only for P3.
