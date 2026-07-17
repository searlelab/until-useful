---
name: uu-second-opinion
description: Independently audit an approved changeset from a fresh session. Use only when manually invoked; do not modify the repository.
disable-model-invocation: true
user-invocable: true
---

# UU Second Opinion

Perform a bounded clean-room audit of an approved changeset. Use this rarely as an optional pre-merge sanity check for material risks missed by the plan/review/revise loop, normally after `uu-review` has approved.

## Setup

- Start in a fresh session and invoke this skill without arguments. Work from the canonical `docs/uu-<task-slug>.md` goal document and the repository state only; do not use worker summaries, prior review reports, or revision narratives.
- If the host supports choosing a model family, prefer one different from the first reviewer. This is a recommendation, not a requirement.
- Locate the canonical plan and changeset independently from repository instructions, status, diffs, untracked files, and history. If either cannot be identified, report `BLOCKED`.

## Rules

- Read repository instructions, the canonical plan, the actual change surface, and necessary surrounding code. Do not edit or write. Never stage, commit, or push; only the human may do so.
- Audit the whole changeset from scratch, looking specifically for material missed risks: missing plan outcomes, incorrect behavior, severe regressions or compatibility failures, unsafe edge cases, security or data-loss risks, concurrency defects, and missing coverage that leaves such a risk unguarded. Do not hunt for preferences, minor cleanup, or speculative improvements.
- Report `REQUEST CHANGES` only for a substantiated P0/P1 finding with concrete repository evidence, a credible failure scenario, and material impact. Where practical, verify it with a focused executable check; otherwise, state why and describe the strongest available validation.
- Do not report P2/P3 findings on a clean audit. If a P0/P1 finding already requires `uu-review` adjudication, include related lower-priority observations only as clearly labeled, non-reopening input for that same review loop that can be cleaned up if they are easy.
- This report is independent review evidence, not implementation direction. The user must paste it into `uu-review`; do not direct findings to `uu-revise`.

## Report

Lead with `APPROVE`, `REQUEST CHANGES`, or `BLOCKED`. Group any material findings by priority:

- **P0:** catastrophic risk
- **P1:** blocking correctness or compatibility failure
For each P0/P1 finding, give evidence, failure scenario, impact, and correction. If applicable, place P2/P3 observations under **Lower-priority observations for uu-review**; they do not affect the status or independently reopen work. When no P0/P1 finding is substantiated, use `APPROVE` and state that no material missed plan, correctness, compatibility, safety, or security risk was found. Then briefly state the plan audit, checks actually run and outcomes, and residual risks. End by directing the user to paste this report into `uu-review` for repository-context adjudication before any revision.
