# Codex-Orchestrated Until Useful Runtime V1

**Canonical plan document:** `docs/uu-runtime-codex-claude-v1.md`

## Intent

Build a usable first runtime in which the active Codex task remains the constructive `P1` context and deterministic local code manages serial calls to Claude Code for review, fresh second opinions, challenge adjudication/verification, and final summarization.

The runtime automates bookkeeping and message passing. Codex and Claude continue making protocol-level judgments; the human retains plan approval, scope authority, final review, and Git control.

## Current understanding

- Keeping `P1` in the initiating Codex task avoids the unresolved problem of externally creating or resuming a Codex App context.
- The runtime does not need a Codex adapter in V1. The `uu-build` skill runs inside Codex, performs the existing `uu-plan` and `uu-revise` responsibilities, and records their outcomes with the runtime.
- Claude Code provides the V1 external harness:

  - `R1` is a persistent Claude session for initial review, revision verification, and later challenge adjudication.
  - Each second opinion starts in a new Claude session: `R2`, `R3`, and so on.
  - A challenger that raises accepted findings is resumed to verify the Codex correction and becomes the review frontier only after approval.
  - Final `uu-summarize` runs in the current authoritative Claude reviewer context.

- Existing `uu-plan`, `uu-review`, `uu-revise`, `uu-second-opinion`, and `uu-summarize` skills remain independently usable and unchanged.
- `uu-summarize` returns the final commit title. It is not used to seed a fresh challenger; second opinions receive only the canonical plan and repository evidence.
- If the original Codex task is lost or becomes stale, the runtime can generate a compact constructive handoff, but the human must open or select the replacement Codex task. V1 does not control Codex tasks externally.

## Desired direction and scope

### V1 workflow

```text
Codex P1: uu-build → uu-plan behavior → approved plan → initial implementation
  → runtime registers task
  → Claude R1: uu-review
      REQUEST_CHANGES → Codex P1: uu-revise behavior → Claude R1: uu-review
      APPROVE → fresh Claude R2: uu-second-opinion
          APPROVE → challenge-policy evaluation
          REQUEST_CHANGES → Claude R1: uu-review adjudication
              accepted findings → Codex P1: uu-revise behavior
                                → Claude R2: uu-review verification
                                → promote R2 after approval
              all rejected → challenge-policy evaluation
  → optional fresh R3/R4 challenge cycles
  → current Claude review frontier: uu-summarize
  → final runtime report
  → human review and commit
```

### Included

- Add the three supplied design documents verbatim under `docs/` and link them from the README as design intent.
- Add the canonical plan, Python runtime, SQLite provenance, state machine, challenge policy, Claude adapter, deterministic fake adapter, CLI, reports, tests, and Codex-only `uu-build` skill.
- Support restart and resume by task ID, persistent Claude session UUIDs, manual constructive-context refresh, and explicit blockers.
- Snapshot the repository before and after every Claude call and block if a supposedly read-only Claude protocol changes the worktree.
- Update installation and usage documentation for the new Codex-orchestrated workflow.

### Deferred

- Calling Codex through a CLI, SDK, App Server, or task-management API.
- Running `uu-build` from Claude Code or Qwen.
- Automatic creation or selection of replacement Codex tasks.
- Parallel work, multiple worktrees, dashboards, cloud coordination, automatic commits, generalized workflow graphs, and autonomous model selection.
- Automatic context-rot heuristics beyond recorded manual refresh.

## Implementation approach

### 1. Preserve intent and compatibility

- Write this plan verbatim before implementation.
- Copy the supplied files to:

  - `docs/until_useful_runtime_project_design.md`
  - `docs/until_useful_runtime_goals_and_intent.md`
  - `docs/until_useful_runtime_user_stories.md`

- Add README links and clearly distinguish the V1 implementation from future design.
- Do not modify the six existing protocol skill contracts.
- Add `skills/uu-build/SKILL.md` and Codex metadata. The skill must fail clearly if invoked outside Codex V1 rather than pretending another host is supported.

### 2. Runtime core

Create a Python 3.11+ package under `src/uu_runtime` using standard-library facilities wherever practical.

Define:

- Protocols: `UU_REVIEW`, `UU_REVISE`, `UU_SECOND_OPINION`, and `UU_SUMMARIZE`; planning is completed by Codex before runtime registration.
- Workflow purposes distinguishing initial review, ordinary verification, challenge adjudication, challenge revision, challenge verification, and final summarization.
- Context classes `CONSTRUCTIVE`, `REVIEW`, and `FRESH_CHALLENGE`, with `P*` and `R*` lineage labels.
- Typed outcomes matching existing skills.
- Stable finding IDs and dispositions: accepted, partially accepted, rejected with evidence, already resolved, or blocked on human judgment.
- A centralized transition table. Invalid state, purpose, protocol, or result combinations block safely.

`UU_BUILD` remains a composite user workflow, not a protocol executed by a model.

### 3. Persistence and locking

Use SQLite with foreign keys and idempotent schema migrations.

Persist:

- tasks and current workflow state;
- logical Codex constructive generations;
- Claude context UUIDs and review-frontier authority;
- protocol runs, raw emitted output, normalized results, and cleaned reports;
- findings, adjudications, and verifications;
- human approvals and interventions;
- state-transition events;
- repository snapshots;
- final workflow reports.

Use transactional state changes and enforce one active runtime run globally. Store the database outside Git by default, with CLI and environment overrides for testing and recovery.

Do not store private reasoning. “Raw output” means the harness-emitted result available to the caller.

### 4. Claude harness adapter

Implement synchronous Claude CLI execution with:

- a runtime-generated UUID for each new reviewer session;
- explicit resume by UUID for persistent contexts;
- JSON output plus JSON Schema validation;
- configurable timeout and model, defaulting to the user’s configured Claude model;
- captured stdout, stderr, exit status, usage metadata when available, and exact invocation purpose;
- edit/write tools disabled for all Claude V1 roles;
- Git snapshots before and after every invocation.

Protocol routing:

- Initial `R1`: invoke `/uu-review` with the canonical-plan path and Codex implementation handoff.
- Continued `R1`: resume the same UUID for review after Codex revisions.
- Fresh `R(n+1)`: invoke `/uu-second-opinion` with the repository and canonical plan only.
- Challenge adjudication: resume the prior review frontier with the challenger report.
- Challenge verification: resume the challenger with the accepted-finding and Codex-revision handoff.
- Final title: resume the current review frontier and invoke `/uu-summarize`.

A second-opinion invocation must fail closed if its UUID was previously used or if prior worker/reviewer narratives appear in its envelope.

### 5. Codex `uu-build` integration

The `uu-build` skill should reference and follow the existing `uu-plan` and `uu-revise` contracts instead of copying their detailed engineering instructions.

On a new build it must:

1. Perform the familiar interactive planning flow in the current Codex task.
2. Obtain human approval through the normal Codex planning interaction.
3. Write the canonical plan and create the initial implementation using `uu-plan` behavior.
4. Register the repository, plan, risk profile, logical `P1`, and implementation handoff with the runtime.
5. Repeatedly ask the runtime for the next allowed action.
6. Let the runtime execute Claude-owned actions.
7. Apply accepted corrections in the same Codex task using `uu-revise` behavior.
8. Submit a structured Codex completion record containing status, cleaned handoff, checks, and residual risk.
9. Stop at a human gate, blocker, policy completion, or final human-review state.

A resumed invocation accepts or discovers a task ID, verifies repository identity, displays the durable state, and continues without repeating completed calls.

For a manual `P1 → P2` refresh, the runtime generates a compact handoff from the canonical plan, current diff, accepted findings, latest reports, checks, and unresolved risks. The human opens the new Codex task and invokes `uu-build` with that task ID.

### 6. CLI and deterministic routing

Provide machine-readable JSON for orchestration commands and Markdown for human reports.

Minimum commands:

- `uu-runtime start`
- `uu-runtime next`
- `uu-runtime record-codex-result`
- `uu-runtime status`
- `uu-runtime resume`
- `uu-runtime report`
- `uu-runtime contexts`
- `uu-runtime refresh-context`
- `uu-runtime stop`
- `uu-runtime doctor`

Structured Codex results are accepted through stdin to avoid fragile shell quoting.

Challenge-policy defaults:

- routine: 1 minimum, 1 maximum;
- feature: 1 minimum, 2 maximum;
- critical: 1 minimum, 3 maximum;
- security: 2 minimum, 4 maximum.

After the minimum:

- stop after a clean challenge approval;
- stop after all material challenge findings are rejected with evidence;
- continue, up to the maximum, when a challenge produced accepted P0/P1 findings;
- record P3 findings from `APPROVE_WITH_MINOR_ISSUES` as residual issues and continue as approved;
- pause for the human if unresolved material risk remains at the maximum or a correction requires a material plan change.

### 7. Reporting

Generate a final Markdown report containing:

- task identity and canonical plan;
- final workflow state and exact Claude `uu-summarize` result;
- chronological run timeline;
- `P*`/`R*` context lineage;
- revision and challenge cycles;
- findings, dispositions, adjudicators, implementers, and verifiers;
- Codex and Claude checks;
- repository changes detected during each run;
- context refreshes;
- stopping reason and residual risk;
- human review checklist;
- current Git status and explicit confirmation that the runtime did not stage or commit.

## Validation approach

Use a deterministic fake adapter for exhaustive tests without consuming Claude sessions.

Cover:

- initial approval followed by a clean challenge;
- repeated `R1 ↔ P1` revision cycles;
- accepted `R2` challenge findings routed through `R1`, fixed in `P1`, and verified in `R2`;
- challenger verification failure followed by another `P1` correction;
- promotion of `R2` before creation of fresh `R3`;
- challenge findings rejected by the prior frontier with evidence;
- all risk-profile minimum and maximum boundaries;
- `APPROVE_WITH_MINOR_ISSUES`, blockers, malformed JSON, schema mismatch, timeout, and interrupted calls;
- unique fresh challenger UUID enforcement;
- absence of prior narratives in second-opinion envelopes;
- restart and idempotent resume between every transition;
- competing runtime writers;
- `P1 → P2` handoff generation;
- detection of repository mutation by a read-only Claude invocation;
- final report completeness and exact summarize-title preservation.

Add opt-in disposable-repository Claude smoke tests for:

- creating and resuming `R1`;
- creating a genuinely fresh `R2`;
- invoking installed `uu-review`, `uu-second-opinion`, and `uu-summarize`;
- structured-output validation;
- read-only repository behavior.

Verify existing skill files remain byte-for-byte unchanged and no automated test changes Git history.

## Assumptions and reviewer focus

- V1 is deliberately asymmetric: Codex constructs and orchestrates; Claude reviews, challenges, adjudicates, verifies, and summarizes.
- The current Codex task is the durable `P1` context. The database records its logical lineage but does not claim to own or resume the Codex task.
- Claude Code is installed, authenticated, and has the required `uu-*` skills available; `doctor` reports actionable failures otherwise.
- No explicit Claude model is hard-coded. Configuration may select one, while the default follows the user’s Claude CLI setup.
- Repository evidence supplies the canonical plan to every reviewer. It is not duplicated into second-opinion narrative handoffs.
- Independent review should concentrate on state-transition correctness, session reuse versus freshness, challenge adjudication authority, contamination of fresh contexts, safe restart behavior, and whether `uu-build` keeps orchestration mechanical rather than acquiring new judgment.
