---
name: uu-second-opinion
description: Independently audit an approved changeset from a fresh session. Use only when manually invoked; do not modify the repository.
disable-model-invocation: true
user-invocable: true
---

# UU Second Opinion

Perform a clean-room audit of an approved changeset. Use this rarely as an optional pre-merge sanity check, normally after `uu-review` has approved.

## Setup

- Start in a fresh session and invoke this skill without arguments. Work from the canonical `docs/uu-<task-slug>.md` goal document and the repository state only; do not use worker summaries, prior review reports, or revision narratives.
- If the host supports choosing a model family, prefer one different from the first reviewer. This is a recommendation, not a requirement.
- Locate the canonical plan and changeset independently from repository instructions, status, diffs, untracked files, and history. If either cannot be identified, report `BLOCKED`.

## Rules

- Read repository instructions, the canonical plan, the actual change surface, and necessary surrounding code. Do not edit or write. Never stage, commit, or push; only the human may do so.
- Audit the whole changeset from scratch. Verify implementation claims and behavior in code and tests; prefer focused executable checks to assertions.
- Look for missing plan outcomes, incorrect behavior, regressions, compatibility failures, unsafe edge cases, security or data-loss risks, concurrency defects, and missing meaningful tests. Where practical, ensure a regression test would fail without the fix; otherwise, state why and describe the strongest available validation.
- This report is independent review evidence, not implementation direction. The user must paste it into `uu-review`; do not direct findings to `uu-revise`.

## Report

Lead with `APPROVE`, `APPROVE WITH MINOR ISSUES`, `REQUEST CHANGES`, or `BLOCKED`. Group related findings by priority:

- **P0:** catastrophic risk
- **P1:** blocking correctness or compatibility failure
- **P2:** defect or important missing coverage
- **P3:** limited-impact follow-up

For each finding, give evidence, failure scenario, impact, and correction. Then briefly state the plan audit, checks actually run and outcomes, and residual risks. Use `REQUEST CHANGES` for P0–P2; use `APPROVE WITH MINOR ISSUES` only for P3. End by directing the user to paste this report into `uu-review` for repository-context adjudication before any revision.
