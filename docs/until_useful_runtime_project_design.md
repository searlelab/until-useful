# Until Useful Runtime
## Agent-Facing Project Design and Development Plan

## 1. Purpose

Implement a minimal, local, serial runtime for the Until Useful methodology.

The runtime must automate protocol invocation and message passing while preserving:

- existing `uu-*` skill behavior;
- interactive planning;
- canonical Git-tracked plans;
- context continuity and freshness rules;
- reviewer authority;
- adversarial second opinions;
- human approval gates;
- human control of Git history.

The implementation must favor clarity, auditability, and compatibility over generality.

---

## 2. Required external behavior

### Existing commands

Do not alter the user-visible behavior or contracts of:

- `uu-propose`
- `uu-plan`
- `uu-review`
- `uu-revise`
- `uu-summarize`
- `uu-second-opinion`

They must remain independently invocable in manual workflows.

### New command

Add:

```text
uu-build
```

Host forms may include:

```text
/uu-build
$uu-build
```

`uu-build` must:

1. begin with the same planning and initial implementation behavior as `uu-plan`;
2. use the host's interactive planning facilities;
3. create the canonical plan through the existing `uu-plan` protocol;
4. pause for human approval of the settled plan when required;
5. register the task with the runtime;
6. continue through the automated Until Useful workflow;
7. return the final workflow report and `uu-summarize` result;
8. leave all Git staging, committing, merging, and pushing to the human.

Do not redefine `uu-plan` as the automated master command.

---

## 3. Methodology entities

### 3.1 Task

A bounded unit of work associated with one canonical plan.

Required properties:

- task ID;
- repository identity;
- worktree path;
- task slug;
- title;
- canonical plan path;
- risk profile;
- current workflow state;
- creation and update timestamps;
- final disposition.

A task must not silently change canonical scope.

### 3.2 Protocol

One named Until Useful operation:

- `UU_PROPOSE`
- `UU_PLAN`
- `UU_REVIEW`
- `UU_REVISE`
- `UU_SUMMARIZE`
- `UU_SECOND_OPINION`
- `UU_BUILD` as the initiating composite protocol.

A protocol defines:

- required inputs;
- permitted repository mutations;
- expected structured outcomes;
- context policy;
- allowed next transitions.

### 3.3 Context

A harness session with a defined protocol history and authority.

Required context classes:

- `CONSTRUCTIVE`: plan and revise continuity;
- `REVIEW`: authoritative review within a review epoch;
- `FRESH_CHALLENGE`: a clean-room second-opinion context.

### 3.4 Context generation

Contexts use lineage labels such as:

```text
P1, P2, ...
R1, R2, R3, ...
```

`P*` contexts are constructive generations.

`R*` contexts are reviewer or challenger generations.

Persist both a human-readable lineage label and the harness-specific session identifier.

### 3.5 Run

One execution of one protocol in one context.

A run records:

- run ID;
- task ID;
- protocol;
- workflow purpose;
- context ID;
- adapter and harness;
- start/end time;
- status;
- raw output;
- normalized result;
- cleaned report;
- repository snapshot metadata;
- error details;
- token/cost metadata when available.

### 3.6 Revision cycle

A sequence of:

```text
UU_REVIEW → UU_REVISE → UU_REVIEW
```

within one review epoch.

### 3.7 Challenge cycle

A sequence of:

```text
authoritative reviewer approval
→ UU_SUMMARIZE
→ fresh UU_SECOND_OPINION
→ prior-reviewer UU_REVIEW adjudication
→ optional UU_REVISE
→ challenger-context UU_REVIEW verification
```

### 3.8 Review epoch

The interval during which one `R*` context is authoritative for verifying the changeset.

After a challenger verifies accepted challenge-driven corrections, that challenger becomes the new review frontier.

### 3.9 Finding

A normalized review or challenge issue with:

- finding ID;
- source run and context;
- priority;
- title;
- evidence;
- failure scenario;
- impact;
- proposed correction;
- status;
- adjudicating context;
- disposition evidence;
- verifying context;
- final state.

### 3.10 Human gate

A workflow pause requiring explicit human action.

---

## 4. Canonical artifacts

### 4.1 Git-tracked canonical plan

The canonical plan is:

```text
docs/uu-<task-slug>.md
```

It remains the source of truth for engineering intent.

Rules:

- created by `uu-plan` before implementation changes;
- written verbatim once settled;
- not modified by runtime protocols after creation;
- only the human may materially revise it;
- referenced by `uu-summarize`;
- remains in Git as a development breadcrumb.

### 4.2 Runtime provenance

Store runtime provenance in SQLite.

Do not add review, revision, challenge, or workflow reports to Git by default.

The database may store full text or reference external runtime-owned files. Prefer the simplest implementation that provides transactional integrity and easy export.

Required provenance includes:

- raw protocol output;
- cleaned protocol report;
- normalized result;
- context lineage;
- timeline events;
- finding records and dispositions;
- approvals;
- blockers;
- context refreshes;
- repository snapshots;
- final workflow report.

---

## 5. Core workflow states

Use explicit states derived from the `uu-*` methodology.

Recommended states:

```text
CREATED
UU_PROPOSE
UU_PLAN
WAITING_FOR_PLAN_APPROVAL
UU_REVIEW
UU_REVISE
UU_SUMMARIZE_FOR_CHALLENGE
UU_SECOND_OPINION
UU_REVIEW_CHALLENGE_ADJUDICATION
UU_REVISE_CHALLENGE
UU_REVIEW_CHALLENGE_VERIFICATION
UU_SUMMARIZE_FINAL
WAITING_FOR_HUMAN_REVIEW
BLOCKED
CANCELLED
DONE
```

The database should also record:

- active revision cycle number;
- active challenge cycle number;
- current review epoch;
- current constructive generation;
- current review frontier context;
- previous reviewer context used for challenge adjudication.

Do not encode every semantic distinction only in free-form notes.

---

## 6. State transitions

### 6.1 Initial build

```text
CREATED
→ UU_PLAN
→ WAITING_FOR_PLAN_APPROVAL
```

On approval:

```text
WAITING_FOR_PLAN_APPROVAL
→ UU_REVIEW
```

On rejection or material plan change:

```text
WAITING_FOR_PLAN_APPROVAL
→ human-controlled cancellation or restart
```

### 6.2 Initial revision cycle

`UU_REVIEW` normalized outcomes:

```text
REQUEST_CHANGES
→ UU_REVISE

APPROVE
→ UU_SUMMARIZE_FOR_CHALLENGE

APPROVE_WITH_MINOR_ISSUES
→ policy decision:
   - treat as approval with residual issues, or
   - request human judgment

BLOCKED
→ BLOCKED
```

After `UU_REVISE`:

```text
UU_REVISE
→ UU_REVIEW
```

Use the same constructive context and same reviewer context during this cycle unless a refresh is explicitly triggered.

### 6.3 Challenge cycle

After authoritative approval:

```text
UU_SUMMARIZE_FOR_CHALLENGE
→ UU_SECOND_OPINION
```

The second opinion must use a new context and must not receive:

- worker summaries;
- prior reviews;
- revision narratives;
- prior challenge reports.

It may receive:

- canonical plan path;
- repository/worktree identity;
- current repository state;
- a bounded summary only when required by the host invocation model, provided it does not disclose prior reasoning or findings.

Normalized second-opinion outcomes:

```text
APPROVE
→ challenge policy evaluation

REQUEST_CHANGES
→ UU_REVIEW_CHALLENGE_ADJUDICATION

BLOCKED
→ BLOCKED
```

### 6.4 Challenge adjudication

Run `uu-review` in the **prior authoritative reviewer context**.

Inputs include:

- canonical plan;
- repository state;
- second-opinion report;
- current diff and tests.

The prior reviewer must classify every substantive finding:

- accepted;
- partially accepted;
- rejected with evidence;
- already resolved;
- blocked on human decision.

Transitions:

```text
accepted or partially accepted findings
→ UU_REVISE_CHALLENGE

all material findings rejected with evidence
→ challenge policy evaluation

human decision required
→ BLOCKED
```

### 6.5 Challenge revision

Run `uu-revise` in the current constructive context unless context-refresh policy selects a new `P*` generation.

After revision:

```text
UU_REVISE_CHALLENGE
→ UU_REVIEW_CHALLENGE_VERIFICATION
```

### 6.6 Challenge verification

Run `uu-review` in the challenger context that raised the findings.

Transitions:

```text
REQUEST_CHANGES
→ UU_REVISE_CHALLENGE

APPROVE
→ promote challenger context to current review frontier
→ challenge policy evaluation

BLOCKED
→ BLOCKED
```

Do not send challenge-driven fixes only to the old reviewer.

### 6.7 Challenge policy evaluation

Evaluate:

- minimum completed challenge cycles;
- maximum permitted cycles;
- risk profile;
- materiality of recent findings;
- context health;
- human stop/continue decision when policy requires it.

If another cycle is required:

```text
→ UU_SUMMARIZE_FOR_CHALLENGE
→ new UU_SECOND_OPINION context
```

If the workflow may complete:

```text
→ UU_SUMMARIZE_FINAL
→ WAITING_FOR_HUMAN_REVIEW
```

### 6.8 Completion

`UU_SUMMARIZE_FINAL` invokes the existing summarize protocol.

The final state is:

```text
WAITING_FOR_HUMAN_REVIEW
```

The runtime presents:

- commit-title suggestion;
- workflow report;
- human review checklist;
- repository status.

Only an explicit human action may mark the task:

```text
DONE
```

Marking `DONE` does not imply the runtime performed a commit.

---

## 7. Challenge policy

Implement challenge policy as configuration, not scattered conditional logic.

Suggested profiles:

```toml
[risk_profiles.routine]
min_challenges = 1
max_challenges = 1

[risk_profiles.feature]
min_challenges = 1
max_challenges = 2

[risk_profiles.critical]
min_challenges = 1
max_challenges = 3

[risk_profiles.security]
min_challenges = 2
max_challenges = 4
```

Policy should also support:

- stop when no P0/P1 issue is substantiated;
- stop when new findings are outside canonical scope;
- stop when only P2/P3 observations remain and no P0/P1 finding reopens work;
- stop when repeated findings provide no new evidence;
- require human judgment when a correction needs material plan change;
- permit explicit human stop after minimum cycles;
- permit explicit human continuation up to the configured maximum.

Record the stopping reason.

Do not optimize for repeated challenge approvals as the only valid completion criterion.

---

## 8. Context management

### 8.1 Initial contexts

A task normally creates:

```text
P1: UU_PLAN and UU_REVISE
R1: initial UU_REVIEW and initial UU_SUMMARIZE
```

Each challenge creates:

```text
R2, R3, ...: fresh UU_SECOND_OPINION
```

After challenge-driven revision, the challenger context also runs `UU_REVIEW_CHALLENGE_VERIFICATION`.

### 8.2 Persistent sessions

Persist harness session identifiers for:

- current constructive context;
- current review frontier;
- prior reviewer needed for adjudication;
- active challenger.

The runtime must be able to resume after process restart.

### 8.3 Context refresh

Support manual refresh at MVP.

The design should make automated refresh heuristics possible later.

Suggested refresh signals:

- configurable number of completed challenge cycles;
- context size or token threshold when available;
- repeated failure to understand accepted findings;
- explicit reviewer concern that context is stale;
- major repository divergence;
- human request.

When refreshing constructive context `Pn → P(n+1)`, create a compact handoff from durable evidence:

- canonical plan;
- repository state;
- current diff;
- accepted findings;
- latest cleaned reviser report;
- validation evidence;
- unresolved risks.

Do not transfer raw private reasoning or the entire transcript.

### 8.4 Fresh challenge enforcement

Every `UU_SECOND_OPINION` run must use a new context identifier.

Fail closed if the adapter cannot guarantee a fresh context.

---

## 9. Protocol contracts

### 9.1 Input envelope

Every adapter invocation should receive a normalized envelope:

```json
{
  "task_id": "uuid",
  "run_id": "uuid",
  "protocol": "UU_REVIEW",
  "workflow_purpose": "INITIAL_REVIEW",
  "repository_path": "/repo",
  "canonical_plan_path": "docs/uu-task.md",
  "context": {
    "lineage": "R1",
    "session_id": "adapter-specific",
    "fresh": false
  },
  "inputs": {
    "handoff_report": "...",
    "challenge_report": null
  },
  "constraints": {
    "may_edit_repository": false,
    "may_modify_plan": false,
    "may_change_git_history": false
  }
}
```

Do not expose runtime-only metadata to the model unless it helps execute the protocol.

### 9.2 Structured output

Require a machine-readable result alongside the human report.

Example:

```json
{
  "protocol": "UU_REVIEW",
  "status": "REQUEST_CHANGES",
  "summary": "Two blocking findings.",
  "findings": [
    {
      "priority": "P1",
      "title": "Incorrect path normalization",
      "evidence": "...",
      "failure_scenario": "...",
      "impact": "...",
      "correction": "..."
    }
  ],
  "checks": [
    {
      "command": "pytest tests/test_paths.py",
      "result": "failed",
      "details": "..."
    }
  ],
  "residual_risks": []
}
```

Do not route workflow state by parsing arbitrary prose when a structured result can be required.

Keep the full human-readable report for provenance.

### 9.3 Protocol-result vocabularies

Use the existing skill vocabularies.

`UU_REVIEW`:

- `APPROVE`
- `APPROVE_WITH_MINOR_ISSUES`
- `REQUEST_CHANGES`
- `BLOCKED`

`UU_SECOND_OPINION`:

- `APPROVE`
- `REQUEST_CHANGES`
- `BLOCKED`

`UU_SUMMARIZE`:

- commit-title string;
- `NO_CURRENT_CHANGESET`.

`UU_PLAN` and `UU_REVISE` need normalized completion statuses such as:

- `COMPLETED`
- `BLOCKED`
- `FAILED`.

---

## 10. Database design

Use SQLite.

Avoid an ORM in the first implementation unless the repository already standardizes on one.

Recommended tables:

### `tasks`

- `id`
- `title`
- `slug`
- `repository_path`
- `worktree_path`
- `canonical_plan_path`
- `risk_profile`
- `state`
- `revision_cycle`
- `challenge_cycle`
- `review_epoch`
- `constructive_context_id`
- `review_frontier_context_id`
- `created_at`
- `updated_at`
- `completed_at`
- `stop_reason`

### `contexts`

- `id`
- `task_id`
- `lineage_label`
- `context_class`
- `adapter`
- `harness`
- `model_label` when known
- `session_id`
- `parent_context_id`
- `created_at`
- `retired_at`
- `retirement_reason`
- `is_fresh`

### `runs`

- `id`
- `task_id`
- `context_id`
- `protocol`
- `workflow_purpose`
- `sequence_number`
- `status`
- `started_at`
- `finished_at`
- `raw_output`
- `cleaned_report`
- `normalized_result_json`
- `error_json`
- `repository_before_json`
- `repository_after_json`
- `usage_json`

### `findings`

- `id`
- `task_id`
- `source_run_id`
- `priority`
- `title`
- `evidence`
- `failure_scenario`
- `impact`
- `correction`
- `status`
- `adjudication_run_id`
- `disposition`
- `disposition_evidence`
- `verification_run_id`
- `created_at`
- `resolved_at`

### `approvals`

- `id`
- `task_id`
- `gate`
- `decision`
- `actor`
- `notes`
- `created_at`

### `events`

- `id`
- `task_id`
- `run_id`
- `event_type`
- `state_before`
- `state_after`
- `details_json`
- `created_at`

### `reports`

- `id`
- `task_id`
- `report_type`
- `content`
- `created_at`
- `source_run_id`

Use foreign keys and transactions.

Enforce one active run globally for MVP.

---

## 11. Repository safety

Before every mutating protocol run:

- capture `git status --porcelain`;
- capture current branch and HEAD;
- identify pre-existing uncommitted changes;
- record untracked files;
- ensure the worktree matches the task.

After every run:

- capture the same metadata;
- compute the changed surface;
- verify unrelated changes were not removed;
- record the diff or a reference to it.

The runtime and prompts must prohibit:

- `git add`;
- `git commit`;
- `git commit --amend`;
- `git merge`;
- `git rebase`;
- `git push`;
- destructive reset;
- checkout that discards changes;
- branch deletion;
- history rewriting.

The runtime should not rely only on prompt compliance. Where practical, execute workers in an environment or wrapper that blocks prohibited Git commands.

---

## 12. Adapters

Define a narrow adapter interface.

Example:

```python
class HarnessAdapter(Protocol):
    def create_context(self, request: ContextRequest) -> ContextHandle: ...
    def resume_context(self, context: ContextHandle, run: RunRequest) -> RunResult: ...
    def run_fresh(self, run: RunRequest) -> RunResult: ...
    def inspect_context(self, context: ContextHandle) -> ContextStatus: ...
```

Initial adapters:

- Codex;
- Claude Code;
- fake adapter for deterministic tests.

The runtime should not contain model-specific routing logic beyond configuration.

Example mapping:

```toml
[protocols.UU_PLAN]
adapter = "claude"
context_class = "constructive"

[protocols.UU_REVISE]
adapter = "claude"
reuse = "constructive"

[protocols.UU_REVIEW]
adapter = "codex"
reuse = "review_context"

[protocols.UU_SECOND_OPINION]
adapter = "claude"
fresh = true
```

Mappings are examples, not hard-coded defaults.

---

## 13. `uu-build` integration

`uu-build` should be implemented as a skill or command thinly coupled to the runtime.

Responsibilities:

1. validate that it is running inside a repository;
2. initiate the existing `uu-plan` behavior;
3. identify the canonical plan path;
4. capture the implementation handoff;
5. create or attach to a runtime task;
6. request plan approval;
7. hand control to the coordinator;
8. stream or periodically display high-level state changes;
9. return the final report when the runtime reaches `WAITING_FOR_HUMAN_REVIEW`.

Do not duplicate the detailed planning and implementation instructions from `uu-plan` unnecessarily. Reuse or invoke the existing protocol contract to prevent drift.

Manual recovery should remain possible. A user should be able to inspect task state and invoke an existing `uu-*` skill manually if automation fails.

---

## 14. CLI requirements

Minimum commands:

```text
uu-runtime start
uu-runtime status
uu-runtime resume
uu-runtime approve-plan
uu-runtime stop
uu-runtime report
uu-runtime contexts
uu-runtime refresh-context
uu-runtime doctor
```

Possible usage:

```text
uu-runtime status --task <id>
uu-runtime report --task <id> --format markdown
uu-runtime refresh-context --task <id> --constructive
```

Keep the primary developer experience inside `uu-build`; the CLI is for control, inspection, and recovery.

---

## 15. Locking and execution

MVP rules:

- one runtime process may own the database writer lock;
- one active run globally;
- one active task may mutate a repository worktree;
- no parallel protocols;
- subprocess timeouts configurable;
- interrupted runs marked explicitly;
- resumption must be idempotent.

Use a database lock row, filesystem lock, or both.

Never infer that an interrupted mutating run completed successfully.

Require repository inspection before retry.

---

## 16. Reporting

### Per-run report

Store:

- protocol;
- purpose;
- context lineage;
- start/end time;
- normalized result;
- cleaned notes;
- findings;
- checks;
- changed surface;
- residual risk.

### Final workflow report

Generate after final summarize.

Required sections:

1. Task and canonical plan
2. Final status
3. Suggested commit title
4. Timeline
5. Context lineage
6. Revision cycles
7. Challenge cycles
8. Implementation summary
9. Review findings and dispositions
10. Validation performed
11. Context refreshes
12. Residual risks
13. Reason challenge sequence stopped
14. Human review checklist
15. Repository status and explicit no-commit statement

The report must be understandable without reading raw transcripts.

---

## 17. Human gates

Required gates:

### Plan approval

The human approves the settled canonical plan before automated review continuation.

### Product or architecture decision

Any unresolved material intent question pauses the workflow.

### Material plan change

Agents may not revise the canonical plan. Escalate to the human.

### Challenge-policy limit

If unresolved material concerns remain at maximum challenge count, pause.

### Final review

The workflow ends in `WAITING_FOR_HUMAN_REVIEW`.

No automatic commit follows.

---

## 18. Error handling

Classify errors:

- adapter unavailable;
- session missing;
- fresh-context creation failed;
- malformed structured result;
- repository mismatch;
- prohibited Git operation attempted;
- process timeout;
- interrupted mutating run;
- canonical plan missing;
- task state conflict;
- database lock conflict.

On error:

- preserve raw output;
- capture repository state;
- record an event;
- move to `BLOCKED` when safety or state is uncertain;
- provide a specific recovery instruction;
- never guess that a mutation succeeded.

---

## 19. Testing strategy

### Unit tests

- every allowed and forbidden state transition;
- challenge-policy evaluation;
- finding lifecycle;
- context promotion;
- context refresh;
- report generation;
- structured-result validation;
- Git-safety checks.

### Integration tests with fake adapters

Simulate:

- immediate approval;
- multiple revision cycles;
- second-opinion approval;
- challenge finding accepted and fixed;
- challenge finding rejected with evidence;
- challenger verification failure and retry;
- multiple challenge cycles;
- constructive context refresh;
- blocked product decision;
- interrupted mutating run;
- malformed adapter output.

### Real-adapter smoke tests

Use a disposable repository.

Verify:

- session creation and resumption;
- fresh second-opinion context;
- repository mutation only in plan/revise;
- read-only behavior in review/second opinion/summarize;
- recovery after runtime restart;
- no Git history changes.

---

## 20. Implementation milestones

### Milestone 1: Methodology state core

Implement:

- project skeleton;
- SQLite schema and migrations;
- enums and typed entities;
- state-transition engine;
- challenge-policy engine;
- context lineage model;
- event log;
- locking;
- CLI inspection commands.

Do not integrate real harnesses.

Acceptance:

- all transitions tested;
- invalid transitions rejected;
- task can be replayed from events;
- one active run enforced.

Stop for human review.

### Milestone 2: Fake adapter and full workflow simulation

Implement:

- adapter interface;
- deterministic fake adapter;
- structured protocol results;
- revision and challenge cycles;
- context promotion;
- context refresh;
- workflow report generation.

Acceptance:

- end-to-end simulated `uu-build`;
- at least one challenge cycle;
- challenge adjudication and challenger verification;
- final report generated;
- restart/resume tested.

Stop for human review.

### Milestone 3: Repository safety layer

Implement:

- Git snapshots;
- changed-surface tracking;
- prohibited-command controls where feasible;
- interrupted-run recovery;
- worktree identity validation.

Acceptance:

- pre-existing changes preserved;
- prohibited Git actions detected or blocked;
- uncertain mutating runs become `BLOCKED`.

Stop for human review.

### Milestone 4: First real harness adapter

Choose the simplest supported harness.

Implement:

- context create/resume;
- protocol invocation;
- structured-result capture;
- timeout and error handling;
- session persistence.

Acceptance:

- initial review/revise loop works in a disposable repository;
- read/write boundaries respected;
- restart/resume works.

Stop for human review.

### Milestone 5: Second harness adapter

Implement equivalent support for the other primary harness.

Acceptance:

- phase-to-harness mapping is configurable;
- mixed-harness workflow completes;
- second opinion uses a guaranteed fresh context.

Stop for human review.

### Milestone 6: `uu-build`

Implement the new user-facing command.

Acceptance:

- starts with the familiar `uu-plan` experience;
- canonical plan created unchanged;
- runtime task registered;
- human approval gate works;
- automated handoff begins;
- existing `uu-plan` remains unchanged.

Stop for human review.

### Milestone 7: Real repository pilot

Run on a bounded, noncritical task.

Measure:

- manual messages eliminated;
- review cycles;
- challenge cycles;
- human interventions;
- adapter failures;
- context refresh needs;
- final human corrections;
- usefulness of workflow report.

Do not add parallelism or broad integrations during the pilot.

---

## 21. MVP completion criteria

The MVP is complete when a developer can:

1. invoke `uu-build` in Claude Code or Codex;
2. interactively settle a plan;
3. approve the canonical plan;
4. allow the runtime to perform serial review/revise cycles;
5. receive at least the configured minimum fresh second opinion;
6. have challenge findings adjudicated by the prior reviewer;
7. have accepted challenge corrections verified by the challenger context;
8. complete or stop according to an explicit challenge policy;
9. receive a final commit-title suggestion and workflow report;
10. inspect and commit the working tree manually.

Additionally:

- all protocol runs are durable;
- context lineage is visible;
- runtime restart is recoverable;
- no automatic Git history changes occur;
- existing manual skills continue to work.

---

## 22. Explicit non-goals for MVP

Do not implement:

- parallel workers;
- multiple simultaneous worktrees;
- autonomous task selection;
- automatic backlog prioritization;
- semantic/vector memory;
- web dashboard;
- cloud coordinator;
- distributed queue;
- pull-request creation;
- automatic commits;
- automatic model benchmarking;
- dynamic model selection by an LLM;
- generalized user-authored workflow graphs;
- plugin marketplace;
- arbitrary multi-agent chat.

The internal state machine may be data-driven, but the first version should implement the Until Useful methodology, not a universal orchestration language.

---

## 23. Development rules for the implementing agent

- Inspect the existing Until Useful repository before choosing structure.
- Reuse its naming, packaging, command, test, and documentation conventions.
- Keep the runtime small and local.
- Avoid speculative abstractions.
- Separate methodology logic from harness adapters.
- Make state transitions explicit and exhaustively tested.
- Preserve existing skills verbatim unless a reviewed compatibility change is required.
- Do not implement future milestones early.
- Stop after each milestone and provide:
  - behavior implemented;
  - files changed;
  - tests run;
  - unresolved decisions;
  - risks;
  - recommended next milestone.

The implementation itself should follow the Until Useful methodology.
