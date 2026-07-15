---
name: uu-revise
description: Adjudicate review feedback and revise the current changeset. Use only when manually invoked; verify each finding and test justified fixes.
disable-model-invocation: true
user-invocable: true
---

# UU Revise

Revise the current changeset from the pasted review and user notes. A review finding is a hypothesis, not an instruction.

## Rules

- Read repository instructions, the relevant `docs/uu-<task-slug>.md` plan, affected code, and tests before editing.
- Do not edit the canonical plan file. Other documentation may change when justified by the approved plan or accepted finding.
- Preserve unrelated changes. Make the smallest coherent correction. Do not commit, push, rewrite history, or use destructive Git operations.

## Method

1. Identify the changeset and classify every substantive finding: accepted, partially accepted, rejected, already resolved, or blocked by a product decision.
2. Verify the reported mechanism before editing; reproduce it when practical.
3. Implement justified corrections and regression coverage. Complete independent fixes even when another finding needs a product decision.
4. Run targeted checks and warranted broader checks. Re-read the diff for regressions, unintended scope, and deviations from the canonical plan.

## Report

Lead with the result. Group related work; do not repeat the plan or provide a file-by-file diary. Briefly report finding dispositions (with evidence for rejections), behavioral changes and material plan deviations, checks actually run, and unresolved decisions or risks. End with a compact reviewer handoff.
