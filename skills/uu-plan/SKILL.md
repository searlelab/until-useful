---
name: uu-plan
description: Plan and implement a repository-grounded proposal. Use only when manually invoked; create the canonical plan, then carry out its approved scope.
disable-model-invocation: true
user-invocable: true
---

# UU Plan

Plan the text after the invocation against the open repository, then implement the approved scope. Treat it as intent; do not broaden or replace it silently.

## Rules

- Derive a concise filesystem-safe `<task-slug>` and, once the plan is settled, write it verbatim to `docs/uu-<task-slug>.md` before changing implementation files.
- Keep that plan unchanged for the work loop. Material plan changes return to the human, who may revise it manually before the next handoff.
- Never stage, commit, or push; only the human may do so. Preserve unrelated changes and do not use destructive Git operations.

## Architecture and implementation

- Inspect repository instructions and the relevant code, tests, configuration, and current changes before deciding where a change belongs.
- Extend the existing architecture: identify the owning module, boundaries, data flow, and integration points; reuse established paths, helpers, models, and test infrastructure before adding abstractions.
- Design the smallest cohesive change that meets the approved outcome. Favor clear responsibilities and local, intention-revealing interfaces over speculative generality or framework rewiring.
- Preserve compatibility and minimize blast radius: change the fewest files, prefer additive changes, and do not alter existing behavior, dependencies, tooling, or unrelated formatting/refactors without explicit approval.
- Follow nearby conventions for placement, formatting, naming, error handling, and comments; update comments when behavior changes.
- Keep behavior and outputs deterministic, including ordering and randomness. Add or update focused, stable regression coverage or deterministic fixture/golden checks when behavior changes.

## Method

1. Identify the outcome, constraints, exclusions, and success criteria.
2. Read repository instructions; inspect relevant implementation, tests, configuration, documentation, current changes, and history.
3. Locate affected paths and integration points. Identify reuse, dependencies, compatibility concerns, migrations, and obsolete assumptions.
4. Resolve uncertainty from repository evidence; ask one focused question only when a product or architectural decision blocks responsible work.
5. Write the settled plan verbatim to the canonical plan document, implement it, and add or update focused validation. Run targeted checks and warranted broader checks, then re-read the diff for unintended scope.

## Report

Start with the title and **Canonical plan document:** `docs/uu-<task-slug>.md`. Use these concise sections:

- **Intent** — outcome and constraints.
- **Current understanding** — relevant evidence and constraints.
- **Desired direction and scope** — related outcomes, boundaries, and exclusions.
- **Implementation approach** — grouped ordered work, including creation of the canonical plan document. Include paths, symbols, compatibility, and verification only when useful.
- **Validation approach** — targeted, broader, and manual checks.
- **Risks, decisions, and reviewer focus** — unresolved decisions, assumptions, failure modes, and what needs independent scrutiny.

Then report the implementation result, behavior changed, files changed, checks actually run, and unresolved decisions or risks. Distinguish observations from inferences. Avoid unrelated cleanup and atomic checklists for compound work.
