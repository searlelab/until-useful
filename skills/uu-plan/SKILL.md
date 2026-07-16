---
name: uu-plan
description: Create a repository-grounded implementation plan from a proposal. Use only when manually invoked; do not implement it.
disable-model-invocation: true
user-invocable: true
---

# UU Plan

Plan the text after the invocation against the open repository. Treat it as intent; do not broaden or replace it silently.

## Rules

- Use native Plan mode when available. If its mode state is visible and not Plan mode, ask the user to switch. Otherwise remain read-only and say so.
- Do not edit, create artifacts, or write the plan to disk. Never stage, commit, or push; only the human may do so.
- Derive a concise filesystem-safe `<task-slug>` and state `docs/uu-<task-slug>.md` as the canonical plan path.
- The first implementation step must tell the worker to create that file verbatim from the approved plan before changing code. It stays unchanged for the work loop; material plan changes return to the human, who may update it manually before the next handoff.

## Method

1. Identify the outcome, constraints, exclusions, and success criteria.
2. Read repository instructions; inspect relevant implementation, tests, configuration, documentation, current changes, and history.
3. Locate affected paths and integration points. Identify reuse, dependencies, compatibility concerns, migrations, and obsolete assumptions.
4. Resolve uncertainty from repository evidence; ask one focused question only when a product or architectural decision blocks a responsible plan.

## Report

Start with the title and **Canonical plan document:** `docs/uu-<task-slug>.md`. Use these concise sections:

- **Intent** — outcome and constraints.
- **Current understanding** — relevant evidence and constraints.
- **Desired direction and scope** — related outcomes, boundaries, and exclusions.
- **Implementation approach** — grouped ordered work; step one creates the canonical plan document. Include paths, symbols, compatibility, and verification only when useful.
- **Validation approach** — targeted, broader, and manual checks.
- **Risks, decisions, and reviewer focus** — unresolved decisions, assumptions, failure modes, and what needs independent scrutiny.

Distinguish observations from inferences. Avoid unrelated cleanup and atomic checklists for compound work.
