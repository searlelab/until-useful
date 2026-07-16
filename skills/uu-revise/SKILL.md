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
- Do not edit the canonical plan file after its initial creation; only the human may revise it. Other documentation may change when justified by the approved plan or accepted finding.
- Preserve unrelated changes. Make the smallest coherent correction. Never stage, commit, or push; only the human may do so. Do not rewrite history or use destructive Git operations.

## Corrective implementation

- Inspect repository instructions and the relevant code, tests, configuration, and current changes before deciding whether a finding is real.
- Trace the mechanism to its root cause and preserve the surrounding contract. Prefer the smallest correction that restores the intended invariant; do not mask symptoms, broaden behavior, or refactor adjacent code without justification.
- Reuse the existing architecture, helpers, models, and test infrastructure. Add an abstraction only when the correction cannot remain clear and local without it.
- Continue the established style exactly: use nearby code as the authority for placement, structure, formatting, naming, error handling, and comment style. Do not reformat or modernize unrelated code.
- Add or update regression coverage that would fail before the fix, and keep it deterministic and focused on the defect. Run the closest relevant checks before broader validation.

## Method

1. Identify the changeset and classify every substantive finding: accepted, partially accepted, rejected, already resolved, or blocked by a product decision.
2. Verify the reported mechanism before editing; reproduce it when practical.
3. Implement justified corrections and regression coverage. Complete independent fixes even when another finding needs a product decision.
4. Run targeted checks and warranted broader checks. Re-read the diff for regressions, unintended scope, and deviations from the canonical plan.

## Report

Lead with the result. Group related work; do not repeat the plan or provide a file-by-file diary. Briefly report finding dispositions (with evidence for rejections), behavioral changes and material plan deviations, checks actually run, and unresolved decisions or risks. End with a compact reviewer handoff.
