# Until Useful Runtime
## User Stories and Decision-Shaping Notes

## Purpose

This document captures the user observations, workflow habits, and practical constraints that directly shaped the design of Until Useful Runtime.

It is not a replacement for:

- the human-facing goals and intention document;
- the agent-facing project design;
- the individual `uu-*` skill contracts.

Instead, it records the reasons behind the design in a form similar to user stories. These stories should be used during implementation, review, and future prioritization to make sure the runtime solves the workflow the team actually uses rather than an imagined generic multi-agent workflow.

The central theme is:

> The project is automating message passing between established Until Useful protocols while preserving the contexts, review authority, and human judgment that make the process effective.

---

# 1. Preserve the Existing Workflow

## User story: Keep `/uu-plan` unchanged

**As a developer already using Until Useful,**  
I want `/uu-plan` to continue behaving exactly as it does today,  
so that automation does not disrupt a familiar and trusted workflow.

### Notes that shaped this decision

The team is already comfortable invoking `uu-plan` manually. It provides a strong interactive planning experience in both Claude Code and Codex, including question-and-answer planning before implementation.

Changing `uu-plan` into an automatic end-to-end workflow would move existing users' cheese and blur the distinction between manual and automated operation.

### Resulting design decision

Add a new command:

```text
uu-build
```

`uu-build` should initially mimic `uu-plan`, including interactive planning and creation of the first implementation draft, and then continue through the automated Until Useful workflow.

`uu-plan` remains independently usable and unchanged.

### Acceptance criteria

- Existing `uu-plan` behavior and output remain compatible.
- Existing users do not need to change their workflow.
- `uu-build` begins with the same planning and first-draft behavior as `uu-plan`.
- The automatic continuation is opt-in through `uu-build`.
- Manual use of every existing `uu-*` command remains possible.

---

## User story: Reuse the existing `uu-*` branding

**As a team member,**  
I want the automation to use the same short `uu-*` naming and Until Useful identity,  
so that it feels like an extension of the current method rather than a new platform.

### Notes that shaped this decision

The `uu-` prefix is fast to type and already familiar. Until Useful is the project and methodology name. The runtime should not introduce a competing vocabulary for ordinary users.

### Resulting design decision

- Continue to use `uu-*` for commands.
- Use **Until Useful Runtime** for the execution engine.
- Treat the existing skills as the public methodology.
- Avoid presenting the system primarily as a generic "multi-agent orchestrator."

### Acceptance criteria

- User-facing commands and reports use Until Useful terminology.
- Internal abstractions do not leak unnecessary agent-framework jargon.
- A current Until Useful user can understand the automated workflow without learning a new methodology.

---

# 2. Automate Message Passing, Not Judgment

## User story: Stop acting as the courier

**As the human supervising the work,**  
I want the runtime to move plans, summaries, reviews, and revision notes between contexts,  
so that I do not have to manually copy and paste every handoff.

### Notes that shaped this decision

The current manual workflow is effective, but the human performs repetitive administrative work:

- copying the plan or implementation notes to review;
- copying review findings to revise;
- returning revision notes to review;
- passing the review summary to a fresh second opinion;
- returning second-opinion findings to the reviewer for adjudication.

This message passing is the main activity the project should automate.

### Resulting design decision

The runtime is a deterministic coordinator. It should:

- know the active task and phase;
- invoke the correct protocol in the correct context;
- pass only the evidence appropriate for that handoff;
- record the result;
- route the next phase according to the methodology;
- stop when human judgment is needed.

### Acceptance criteria

- A normal `uu-build` workflow can proceed without manual copy-and-paste handoffs.
- Every automated handoff is inspectable.
- The human can pause, inspect, and resume the workflow.
- The runtime never substitutes its own model judgment for an explicit methodology transition.

---

## User story: Remain the final decision-maker

**As the human owner of the repository,**  
I want automation to stop at consequential decisions,  
so that I remain responsible for scope, architecture, and Git history.

### Notes that shaped this decision

The desired system is human-led. The human is intentionally the bottleneck for:

- approving the plan;
- deciding whether a material scope change is justified;
- resolving product or architecture questions;
- deciding when additional adversarial review has declining value;
- performing final code review;
- staging and committing the changes.

### Resulting design decision

Required human gates include:

- settled-plan approval;
- unresolved product or architecture decisions;
- material changes to the canonical plan;
- unresolved findings at policy limits;
- final review and commit.

### Acceptance criteria

- The runtime never stages, commits, merges, rebases, pushes, or publishes.
- A material plan change cannot be made silently by an agent.
- The final state is waiting for human review, not automatic completion.
- Human decisions are recorded in workflow provenance.

---

# 3. Model Contexts, Not Generic Agents

## User story: Preserve constructive continuity

**As a developer using a planning and implementation context,**  
I want `uu-plan` and later `uu-revise` work to continue in the same constructive context when practical,  
so that the worker retains repository understanding and implementation history.

### Notes that shaped this decision

In the observed workflow:

- `P1` built the plan and first code draft.
- Later `uu-revise` work continued in `P1`.
- This preserved knowledge of architecture, earlier choices, test strategy, and implementation details.

The "agent" in this workflow is therefore not simply a model identity. It is a protocol operating inside a context with a particular history.

### Resulting design decision

Create persistent constructive contexts:

```text
P1, P2, P3, ...
```

A constructive context normally runs:

- `uu-plan`;
- `uu-revise`;
- later challenge-driven `uu-revise` work.

### Acceptance criteria

- The runtime persists the constructive context's harness session identifier.
- Revision runs reuse the current constructive context by default.
- Context lineage is visible in reports.
- The runtime can recover and resume the context after restart when the harness permits it.

---

## User story: Preserve independent review

**As a reviewer,**  
I want a context separate from the planning and implementation context,  
so that I can evaluate repository evidence without inheriting the worker's assumptions.

### Notes that shaped this decision

The primary reviewer used a distinct `R1` context. It accumulated review continuity while remaining separate from `P1`.

The reviewer should treat worker summaries as leads rather than evidence and should inspect:

- the canonical plan;
- the actual diff;
- repository code;
- tests;
- executable checks.

### Resulting design decision

Create persistent reviewer contexts:

```text
R1, R2, R3, ...
```

Each reviewer context is authoritative within a review epoch.

### Acceptance criteria

- Initial review does not run in the constructive context.
- Reviewer reports identify the context lineage used.
- The reviewer verifies material claims from repository evidence.
- Review authority is explicit rather than inferred from whichever model last responded.

---

## User story: Start every second opinion fresh

**As a developer requesting adversarial audit,**  
I want every `uu-second-opinion` run to begin in a new context,  
so that it is not anchored by prior approval or revision narratives.

### Notes that shaped this decision

The second-opinion protocol is valuable precisely because it does not share the earlier review consensus.

In practice:

- `R2` began fresh after `R1` approved;
- later `R3` began fresh after `R2` approved;
- each new context developed an independent defect theory.

Fresh contexts tend to find new issues aggressively. That is both their strength and the reason challenge cycles must be bounded.

### Resulting design decision

Every second opinion creates a new reviewer context generation.

The runtime must not reuse an existing second-opinion context.

### Acceptance criteria

- The adapter creates a new context/session for every second opinion.
- If freshness cannot be guaranteed, the run fails closed.
- The second opinion does not receive prior worker summaries, review reports, or revision narratives.
- Context lineage clearly distinguishes `R1`, `R2`, `R3`, and later generations.

---

# 4. Make Every Proposed Change Pass Through Review

## User story: Review the reviewer's proposed changes

**As the owner of the approved scope,**  
I want findings from a second opinion to be adjudicated before implementation,  
so that the adversarial auditor cannot expand scope or direct changes unilaterally.

### Notes that shaped this decision

A particularly important property of the current method is:

> Every agent has a reviewer, including the second opinion.

A second opinion is intentionally aggressive and may raise valid defects, but it may also:

- misunderstand the plan;
- propose changes beyond approved scope;
- identify already-resolved behavior;
- elevate preferences into defects.

Therefore its output is evidence, not direct implementation direction.

### Resulting design decision

Second-opinion findings follow this route:

```text
fresh second opinion
  → prior authoritative reviewer
  → adjudication
  → accepted findings to uu-revise
```

They never go directly from `uu-second-opinion` to `uu-revise`.

### Acceptance criteria

- Every substantive second-opinion finding receives a recorded disposition.
- Rejected findings include concrete evidence.
- Accepted findings are tied to the review run that adjudicated them.
- `uu-revise` receives only accepted or partially accepted findings.
- The workflow report shows who raised, adjudicated, implemented, and verified each material finding.

---

## User story: Let the challenger verify its own defect theory

**As a reviewer who found a previously missed material issue,**  
I want to verify the resulting correction in my own context,  
so that the reviewer most focused on that failure mode confirms the fix.

### Notes that shaped this decision

In the observed workflow:

- `R1` had already concluded that the changeset was acceptable.
- `R2` found new issues.
- `R1` assessed whether those issues were legitimate and in scope.
- `P1` implemented the accepted corrections.
- The corrected changeset was then reviewed in `R2`, not only in `R1`.

This avoids asking the previously satisfied reviewer to be the sole verifier of a defect it missed.

### Resulting design decision

Use the rule:

> The prior reviewer adjudicates the challenge; the challenger verifies accepted challenge-driven revisions.

After successful verification, the challenger becomes the new review frontier.

### Acceptance criteria

- Challenge-driven revisions are routed to the challenger context for verification.
- The prior reviewer is retained for adjudication provenance.
- After approval, the challenger becomes the authoritative reviewer for the next epoch.
- The transition is represented explicitly in workflow state and reports.

---

# 5. Treat Review as Cycles and Epochs

## User story: Continue review and revision until accepted

**As a developer,**  
I want `uu-review` and `uu-revise` to iterate within stable contexts,  
so that corrections can converge without rebuilding context every turn.

### Notes that shaped this decision

The initial workflow repeats:

```text
P1 revise
↔
R1 review
```

until `R1` accepts.

This is a **revision cycle** within one **review epoch**.

### Resulting design decision

Model revision cycles explicitly:

- one constructive context;
- one reviewer context;
- repeated review/revise runs;
- one recorded cycle count;
- clear approval or blocker outcome.

### Acceptance criteria

- Revision cycle numbers are stored.
- The same `P*` and `R*` contexts are reused during a normal revision cycle.
- Each cycle's findings and dispositions are traceable.
- The runtime detects and escalates non-converging cycles.

---

## User story: Start a new review epoch after challenge-driven correction

**As the workflow owner,**  
I want a successful challenger to become the new review frontier,  
so that later work is judged from the context most aware of the newly discovered risks.

### Notes that shaped this decision

After `R2` verifies the challenge-driven correction, another second opinion should begin in `R3`, with findings returning to `R2`.

This creates a moving sequence:

```text
R1 → R2 → R3 → ...
```

Each context is authoritative for its own review epoch.

### Resulting design decision

Promote a challenger context after it approves the correction arising from its findings.

### Acceptance criteria

- The current review frontier is stored on the task.
- The previous reviewer remains available for historical provenance.
- The next second opinion's findings return to the current frontier for adjudication.
- Reports display review epochs and frontier changes clearly.

---

# 6. Bound Adversarial Review by Risk and Value

## User story: Always receive at least one independent challenge

**As a developer using `uu-build`,**  
I want at least one fresh second opinion before completion,  
so that an approved changeset receives an independent adversarial audit.

### Notes that shaped this decision

The desired default workflow should not stop after only the initial reviewer approves.

At least one clean-room challenge is a defining part of the automated Until Useful process.

### Resulting design decision

Default:

```text
minimum challenge cycles = 1
```

The minimum should be configurable by risk profile.

### Acceptance criteria

- `uu-build` cannot complete before the configured minimum is met.
- The final report records how many challenge cycles ran.
- A human override is explicit and recorded rather than implicit.

---

## User story: Avoid endless fresh reviewers

**As the human supervising the workflow,**  
I want the number of second opinions to reflect task risk,  
so that the process does not chase increasingly marginal or out-of-scope concerns forever.

### Notes that shaped this decision

Fresh second-opinion contexts are likely to find something because they are instructed to challenge the work aggressively.

Repeated challenges are more useful when:

- the project or subsystem is new;
- the change is large;
- the task is security-sensitive;
- correctness, safety, or data integrity is critical.

Repeated challenges are less useful for routine bounded work once findings become speculative or drift from the canonical plan.

### Resulting design decision

Use risk profiles with configurable minimum and maximum challenge counts.

Possible profiles:

- routine;
- feature or new subsystem;
- critical correctness;
- security or safety.

Stop conditions may include:

- only low-priority observations remain;
- new findings lack concrete evidence;
- findings drift beyond the canonical plan;
- a repeated concern introduces no new evidence;
- a proposed correction requires a material plan change;
- the configured maximum is reached;
- the human accepts the residual risk.

### Acceptance criteria

- Challenge policy is configuration, not hidden prompt behavior.
- The stopping reason is recorded.
- The final report explains why the challenge sequence ended.
- The human can continue or stop within policy limits.
- The runtime escalates rather than silently exceeding the maximum.

---

# 7. Manage Context Rot Explicitly

## User story: Refresh a stale constructive context

**As a developer working through several challenge cycles,**  
I want the runtime to support replacing a stale `P1` context with a fresh `P2`,  
so that continuity does not eventually become a liability.

### Notes that shaped this decision

The constructive context accumulates useful implementation history, but eventually it can rot.

Refreshing after every second opinion would create too much churn. In practice, refresh is more useful every few challenge cycles or when behavior shows that the context is stale.

### Resulting design decision

Support context generations and explicit constructive-context refresh.

The first implementation should support manual refresh. Later versions may add heuristics.

### Acceptance criteria

- A human can request `P1 → P2`.
- Refresh preserves the canonical plan and current repository state.
- The handoff includes accepted findings, latest revision notes, validation evidence, and unresolved risks.
- The full old transcript is not required.
- The workflow report records the refresh and its reason.

---

## User story: Compact state instead of replaying everything

**As a refreshed worker context,**  
I want a concise durable handoff,  
so that I can recover the current task state without inheriting all prior conversational noise.

### Notes that shaped this decision

Context refresh should be a controlled compaction operation, not an attempt to duplicate private reasoning.

The durable evidence is more valuable than a complete transcript.

### Resulting design decision

Construct refresh handoffs from:

- canonical plan;
- current repository state and diff;
- accepted findings;
- current review frontier;
- latest cleaned reports;
- tests and checks;
- unresolved risks.

### Acceptance criteria

- Refresh handoffs are reproducible from stored provenance and repository state.
- Raw private chain-of-thought is not required.
- The refreshed context can identify the approved scope and current correction target.
- The human can inspect the handoff.

---

# 8. Separate Canonical Intent from Runtime Provenance

## User story: Keep planning breadcrumbs in Git

**As a future maintainer,**  
I want the canonical plan to remain in the repository,  
so that I can recover the original intent behind a changeset.

### Notes that shaped this decision

The `docs/uu-<task-slug>.md` plan is a useful development breadcrumb.

It belongs beside the code because it explains:

- intended outcome;
- boundaries;
- exclusions;
- planned architecture;
- validation approach;
- reviewer focus.

### Resulting design decision

The canonical plan remains Git-tracked and human-controlled.

### Acceptance criteria

- `uu-plan` creates the canonical plan before implementation changes.
- Automated protocols do not materially rewrite it.
- The commit-title suggestion references the plan according to `uu-summarize`.
- The plan remains usable independently of the runtime database.

---

## User story: Keep operational reports out of Git

**As a repository maintainer,**  
I want review, revise, challenge, and workflow reports stored outside Git by default,  
so that operational provenance does not clutter the product repository.

### Notes that shaped this decision

Review and challenge reports are valuable for runtime history but are not necessarily permanent product artifacts.

Storing them in SQLite implicitly distinguishes them from repository documentation.

### Resulting design decision

SQLite stores or references:

- review reports;
- revise reports;
- challenge reports;
- workflow reports;
- timeline events;
- context lineage;
- findings and dispositions;
- approvals;
- runtime errors.

Reports should remain exportable.

### Acceptance criteria

- Runtime reports are durable across restarts.
- They do not appear as repository changes by default.
- A human can export a report as Markdown or plain text.
- The database clearly references the canonical Git-tracked plan.

---

# 9. Record a Report from Every Step

## User story: Understand what happened without reading transcripts

**As the human performing final review,**  
I want a cleaned report from every protocol and a consolidated final report,  
so that I can understand the workflow without reconstructing it from raw session history.

### Notes that shaped this decision

The desired report should include:

- what loops ran;
- when they ran;
- high-level changes;
- important review findings;
- corrections made;
- remaining problem areas;
- suggested human review focus;
- the final consistent commit title.

The timeline is especially valuable.

### Resulting design decision

Every protocol run records:

- raw output;
- normalized result;
- cleaned report;
- start/end time;
- context;
- checks;
- repository state;
- findings;
- errors.

The final workflow report synthesizes this history.

### Acceptance criteria

The final report includes:

- task and canonical plan;
- final status;
- suggested commit title;
- chronological timeline;
- context lineage;
- revision cycles;
- challenge cycles;
- high-level implementation summary;
- finding dispositions;
- validation performed;
- residual risk;
- human review checklist;
- reason the workflow stopped;
- explicit statement that no commit was made.

---

## User story: Keep commit titles consistent

**As the human preparing the final commit,**  
I want the result of `uu-summarize`,  
so that commit titles remain consistent with the existing Until Useful convention.

### Notes that shaped this decision

`uu-summarize` is intentionally narrow: it returns exactly one concise commit-title line tied to the canonical plan.

The runtime should preserve that contract rather than replacing it with a general prose summary.

### Resulting design decision

Use `uu-summarize` for the final commit-title suggestion and store it as a distinct final output.

### Acceptance criteria

- The runtime returns the exact `uu-summarize` result.
- The title is clearly separated from the workflow report.
- The runtime does not commit the title automatically.
- A missing changeset is handled using the existing summarize contract.

---

# 10. Use Protocol Outcomes for Deterministic Routing

## User story: Make the automation understandable

**As a developer debugging the runtime,**  
I want database states and transitions to use the familiar `uu-*` phases,  
so that the automated workflow maps directly to the manual process.

### Notes that shaped this decision

Generic states such as "planner," "coder," and "reviewer" obscure the actual methodology.

The clearer abstraction is:

- protocol;
- context;
- run;
- outcome;
- next transition.

### Resulting design decision

Use explicit states such as:

```text
UU_PLAN
UU_REVIEW
UU_REVISE
UU_SECOND_OPINION
UU_REVIEW_CHALLENGE_ADJUDICATION
UU_REVIEW_CHALLENGE_VERIFICATION
UU_SUMMARIZE_FINAL
WAITING_FOR_HUMAN_REVIEW
```

### Acceptance criteria

- Database state names are recognizable to Until Useful users.
- A task timeline can be understood without knowing implementation internals.
- The runtime does not ask an LLM to decide which protocol acts next.
- Invalid transitions are rejected by code.

---

## User story: Let protocols declare outcomes, not arbitrary routing

**As the methodology maintainer,**  
I want each protocol to produce a defined result vocabulary,  
so that the runtime can route deterministically without interpreting free-form prose.

### Notes that shaped this decision

The protocols already expose meaningful outcomes:

- `APPROVE`;
- `APPROVE WITH MINOR ISSUES`;
- `REQUEST CHANGES`;
- `BLOCKED`;
- completed implementation;
- completed revision;
- commit-title string.

It is useful for protocols to know their possible outcomes, but the overall methodology should own what those outcomes mean in a particular cycle.

### Resulting design decision

- Protocol contracts define valid result types.
- The methodology state machine maps result plus workflow purpose to the next phase.
- Human-readable reports remain available, but routing uses normalized results.

### Acceptance criteria

- The runtime validates structured protocol results.
- Ambiguous or malformed outcomes block safely.
- The same `uu-review` outcome can route differently depending on whether it is an initial review, challenge adjudication, or challenge verification.
- Workflow rules are centralized and exhaustively tested.

---

# 11. Keep Execution Serial

## User story: Work on one thing at a time

**As the human supervising repository changes,**  
I want one active worker in one worktree,  
so that state, review responsibility, and failures remain understandable.

### Notes that shaped this decision

The goal is not a swarm. The human remains the bottleneck by design.

Parallel work would add:

- conflicting edits;
- incompatible decisions;
- harder review;
- less predictable cost;
- more complex recovery.

### Resulting design decision

MVP constraints:

- one repository per task;
- one worktree;
- one active protocol run;
- no parallel workers;
- no distributed scheduler.

### Acceptance criteria

- The runtime enforces one active run.
- Concurrent mutation of the same worktree is blocked.
- Recovery logic can identify the last active run.
- Parallelism is explicitly outside MVP scope.

---

# 12. Keep Harness and Model Choices Replaceable

## User story: Use the best harness for each phase

**As a workflow maintainer,**  
I want to map protocols to Claude Code, Codex, or future harnesses,  
so that the methodology can evolve as model strengths change.

### Notes that shaped this decision

The team has observed different strengths across frontier models and harnesses.

The runtime should not define the methodology in terms of one provider.

### Resulting design decision

Separate:

```text
phase
protocol
adapter
harness
model
context
```

The runtime executes a protocol. Configuration chooses the adapter and harness.

### Acceptance criteria

- Protocol-to-adapter mapping is configurable.
- Context lineage does not depend on vendor name.
- The database may record the actual model and harness for provenance.
- Replacing a harness does not require redesigning the workflow state machine.

---

# 13. Completion Story

## User story: Return to a trustworthy, reviewable changeset

**As the human who will commit the work,**  
I want `uu-build` to finish with a reviewed working tree and an audit trail,  
so that I can focus my effort on final judgment rather than workflow administration.

### Expected final experience

The user invokes:

```text
/uu-build <proposal>
```

The user participates in the interactive planning process and approves the plan.

The runtime then performs the configured serial workflow.

The user eventually receives:

- the Git-tracked canonical plan;
- the completed working-tree changes;
- final reviewer approval or a clear blocker;
- at least the configured minimum fresh challenge;
- a record of every revision and challenge cycle;
- a cleaned workflow report;
- residual risks and human review focus;
- the exact `uu-summarize` commit-title suggestion;
- confirmation that no Git history was changed.

### Acceptance criteria

The runtime is successful when it reduces manual message passing while preserving or improving:

- context independence;
- implementation continuity;
- scope control;
- review accountability;
- adversarial scrutiny;
- human authority;
- repository safety;
- traceability.

---

# 14. Development Prioritization Guidance

When implementation choices conflict, prioritize them in this order:

1. Preserve human control and repository safety.
2. Preserve protocol and context semantics.
3. Preserve compatibility with existing `uu-*` commands.
4. Make workflow state durable and recoverable.
5. Make provenance understandable.
6. Remove manual message passing.
7. Improve convenience and presentation.
8. Add extensibility only after a real need is demonstrated.

Do not trade the first five priorities for a more autonomous or generalized system.

---

# 15. Questions to Revisit After the MVP

These decisions should be informed by real pilot use rather than solved speculatively:

- How many challenge cycles produce useful risk reduction for each task class?
- Which signals best indicate constructive-context rot?
- How frequently should a constructive context be refreshed automatically?
- Should `APPROVE WITH MINOR ISSUES` complete automatically or require human acknowledgment?
- Which parts of workflow provenance should be retained indefinitely?
- Should reports be exportable automatically for critical tasks?
- When, if ever, should isolated parallel worktrees be introduced?
- Which additional protocols would add value without weakening the methodology?
- Which local or open models are strong enough for lower-risk roles?
- What metrics best predict that the runtime is improving development quality rather than merely adding review volume?

These are future policy questions. They should not delay a simple serial MVP.

---

# Closing principle

The user observations behind this project consistently point to the same conclusion:

> Until Useful Runtime should preserve the right context for each protocol, pass evidence through a disciplined review chain, and stop when additional automation no longer improves the approved changeset.

The runtime is successful when the team recognizes its existing workflow—only with the message passing, bookkeeping, and provenance handled for them.
