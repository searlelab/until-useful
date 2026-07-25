# Scripted `uu-build` Outcomes, Human Input, and Role-Based Claude Models

## Intent

Repair only the automated `uu-build` pipeline and Until Useful Runtime. Do not change the behavior, status vocabulary, model selection, or contracts of the main manual `uu-plan`, `uu-review`, `uu-revise`, `uu-second-opinion`, or `uu-summarize` workflows.

The InstrumentHub report is not approved: its Claude call succeeded, but its automated result contains a P2 finding under `APPROVE_WITH_MINOR_ISSUES`. The pipeline must surface that preserved judgment for planner revision instead of reporting generic `BLOCKED` or forcing `APPROVE`.

## Pipeline outcomes and interfaces

- Add pipeline outcomes independent of detailed runtime state:

  - `IN_PROGRESS`: automation can continue.
  - `APPROVE`: the automated loop completed and awaits final human review.
  - `NEEDS_INPUT`: the scripted pipeline requires human guidance or an external prerequisite.
  - `FAILED`: the pipeline cannot responsibly complete within scope or runtime integrity was lost.
  - `STOPPED`: explicitly stopped by the human.

- Add runtime states `NEEDS_INPUT`, `WAITING_FOR_CODEX_INPUT_RESOLUTION`, and `FAILED`. Retain `BLOCKED` only for stored-task compatibility.
- Keep manual skill output contracts unchanged. The runtime’s non-interactive wrapper maps manual `BLOCKED` results and pipeline exceptions into the new pipeline outcomes.
- Add `$uu-input <task-id> <guidance>` as a Codex-only companion to `$uu-build`. It is not part of the portable manual workflow and is skipped for Claude and Qwen installations.
- Add runtime commands:

  - `uu-runtime provide-input --task <id> --input -`
  - `uu-runtime record-input-resolution --task <id> --input -`

- Input-resolution decisions are `REVISED`, `RETRY`, `APPROVE`, `NEEDS_INPUT`, or `FAILED`.

  - `REVISED` records corrections and routes to verification.
  - `RETRY` restores the prior action only for a resolved prerequisite or interruption.
  - `APPROVE` requires evidence-backed dispositions for preserved P0–P2 findings.
  - `NEEDS_INPUT` requires a focused question.
  - `FAILED` requires attempted approaches and evidence that more input would not resolve the approved task.

## Implementation changes

### Pipeline state and human-input flow

- Write this plan verbatim before changing implementation files; keep `docs/uu-build-reliable-completion.md` unchanged.
- Derive public outcomes from runtime state without changing the manual workflow:

  - `WAITING_FOR_HUMAN_REVIEW` → `APPROVE`.
  - Exhausted repair, missing choice, authentication/permission/model prerequisite, context exhaustion, or bounded correction loop → `NEEDS_INPUT`.
  - Explicit pipeline failure, worktree mutation, corrupt transition, or runtime integrity failure → `FAILED`.
  - Human stop → `STOPPED`.

- Add an `INPUT_RESOLUTION` Codex action containing the canonical plan, human guidance, preserved payload, validation diagnostics, triggering run, and allowed decisions.
- Persist human input and planner resolution in a dedicated table and timeline events.
- `$uu-input` must run in the original P1 Codex task, verify the task/repository pairing, record the human note, apply `uu-revise` when warranted, and record the planner’s resolution.
- Never claim the runtime can locate, create, or reopen a Codex task.

### Structured-output recovery

- Treat enums, required fields, and simple array bounds as generation constraints. Do not claim Claude Code enforces cross-field conditional schemas.
- Keep runtime cross-field validation authoritative.
- Pass the original payload, exact validation error, offending fields, automated status rules, and relevant injected manual skill contract into the single tool-free repair prompt.
- Use generic “protocol result” wording so repair also works for summary and adjudication.
- Record every schema-invalid attempt as `INVALID_OUTPUT`, including the final invalid repair. Preserve payload, diagnostics, model identity, snapshots, source run, and repair-prompt version.
- Permit exactly one informed repair per source judgment. A second invalid result becomes `NEEDS_INPUT`; it does not receive another automatic retry.
- Route the existing InstrumentHub task to `NEEDS_INPUT` during migration. Its preserved P2/P3 judgment becomes the `$uu-input` envelope instead of triggering another Claude repair.

### Automated model profiles

- Apply model profiles only to non-interactive `uu-runtime` calls. Do not add `model` or `effort` frontmatter to the manual skills.

- Use these pipeline defaults:

  - Automated `UU_REVIEW`: current `sonnet` alias, Sonnet 5-or-newer floor, `medium` effort.
  - Automated `UU_SECOND_OPINION`: current `opus` alias, Opus 5-or-newer floor, `medium` effort.
  - Automated `UU_SUMMARIZE`: current `haiku` alias and maintained Haiku floor, with no effort override.
  - Structured repair inherits the originating automated protocol’s profile.

- Initial review, revision verification, challenge adjudication, and challenge verification use Sonnet. Fresh second opinion uses Opus. Final title generation uses Haiku.
- Pass `--model` explicitly for every automated new or resumed session. Pass `--effort medium` for Sonnet and Opus roles. Never configure fallback.
- Configure profiles under `[claude.roles.review]`, `[claude.roles.second_opinion]`, and `[claude.roles.summarize]`.
- Add role-specific runtime/doctor overrides for model, minimum model, pinning, and optional effort. Retain existing global flags as backward-compatible all-role overrides.
- Persist requested role, alias or pin, requested effort when applicable, observed models, provider, and floor result per run.
- Context listings summarize all profiles/models used because an Opus challenge context may later use Sonnet for verification.
- Make live doctor probe every automated profile.

### Migration, reporting, and documentation

- Migrate the runtime database to schema version 2:

  - Add human-input and repair-provenance storage.
  - Recreate the active-task index so `NEEDS_INPUT` and `FAILED` are terminal.
  - Map legacy `BLOCKED` tasks to public outcome `NEEDS_INPUT`.
  - Backfill recognizable schema failures and the InstrumentHub repair provenance without discarding evidence.

- Update only runtime-oriented documentation plus `uu-build` and the new `uu-input` skill. Leave the five portable manual workflow contracts unchanged.
- Reports must show:

  - Pipeline outcome and detailed state separately.
  - Whether a Claude call completed versus whether its result passed protocol validation.
  - Preserved findings from invalid results.
  - Validation diagnostics and required human action.
  - Requested and observed model profiles.

- Catch database integrity errors in the CLI JSON envelope.
- Do not replace a recorded context model with an empty observation.
- Install `uu-build` and `uu-input` only for Codex.

## Validation approach

- Test every pipeline outcome, including successful `APPROVE`, bounded-loop `NEEDS_INPUT`, explicit `FAILED`, legacy `BLOCKED`, and human `STOPPED`.
- Verify the manual skill files and their frontmatter remain unchanged except for unrelated pre-existing changes.
- Reproduce the InstrumentHub payload and verify:

  - The repair receives the exact diagnostic and prior payload.
  - A second invalid result becomes `NEEDS_INPUT`.
  - The report displays the preserved P2 and P3.
  - `$uu-input` routes the P2 to Codex revision and Sonnet verification.

- Test every input-resolution decision, audit event, finding disposition, invalid transition, and retry restriction.
- Test migration from the current schema and a fixture matching task `d1c8e617-ac17-4b08-bf10-f900d523b4c7`.
- Verify automated routing:

  - Review roles → `sonnet --effort medium`.
  - Second opinion → `opus --effort medium`.
  - Summary → `haiku` without `--effort`.
  - Repair → originating role’s profile.

- Test aliases, maintained floors, substitutions, pins, multi-model usage, and backward-compatible global overrides.
- Add regression tests for stderr-only heartbeats, JSON CLI errors, empty model labels, report wording, and active-task indexing.
- Run the full suite and `git diff --check`.
- With explicit approval, run live automated Sonnet review/repair probes, a Haiku summary probe, and one Opus second-opinion smoke.
- After migration, instruct the user to open the original InstrumentHub P1 task and invoke:

  `$uu-input d1c8e617-ac17-4b08-bf10-f900d523b4c7 "Treat the preserved P2 as REQUEST_CHANGES, revise it, and address the P3 cleanup if safe."`

## Assumptions and reviewer focus

- The main portable UU workflow remains manual, model-agnostic, and behaviorally unchanged.
- `NEEDS_INPUT` and `FAILED` are scripted-pipeline concepts.
- Do not relabel the InstrumentHub judgment `APPROVE`; its P2 requires revision or an evidence-backed rejection.
- Moving aliases are preferred; full IDs remain explicit pins.
- Haiku is the automated summarizer because the title task is short and deterministic.
- Preserve all current prior-plan and unrelated changes; never stage, commit, push, or rewrite history.
