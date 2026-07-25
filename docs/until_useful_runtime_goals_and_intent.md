# Until Useful Runtime
## Goals, Intent, and Design Rationale

## Executive summary

Until Useful is an established, human-led software development methodology built around a small set of explicit `uu-*` protocols:

- `uu-propose`
- `uu-plan`
- `uu-review`
- `uu-revise`
- `uu-summarize`
- `uu-second-opinion`

The methodology already works. Its weakness is operational rather than conceptual: a person must manually move plans, implementation notes, reviews, revisions, and second-opinion findings between coding-agent contexts.

**Until Useful Runtime** will automate that message passing while preserving the workflow, context boundaries, authority model, and human approval points that make Until Useful trustworthy.

The central design principle is:

> **Automate coordination, not judgment.**

The runtime should make the current method easier to operate, not turn it into an autonomous agent swarm or replace human technical leadership.

---

## What we are building

We are building a small, serial execution engine for the Until Useful methodology.

The runtime will:

- begin an automated workflow through a new `uu-build` command;
- preserve the familiar interactive planning experience of `uu-plan`;
- launch each Until Useful protocol in the correct coding-agent context;
- pass the right evidence and reports to the next protocol;
- maintain durable workflow state and context lineage;
- enforce review, challenge, and human-approval rules;
- record what happened at every step;
- stop with a reviewed changeset, a consistent commit-title suggestion, and a human-readable workflow report.

The runtime will not write software by itself. Existing coding harnesses such as Claude Code and Codex will continue to perform repository inspection, planning, implementation, testing, review, and revision.

The runtime coordinates those harnesses. It does not replace their internal tool-use loops.

---

## What we are not building

The initial project is not:

- a new coding model;
- a replacement for Claude Code, Codex, or other coding harnesses;
- a parallel agent swarm;
- a general-purpose workflow engine;
- an autonomous product manager;
- an automatic Git committer or merger;
- an unattended deployment system;
- a new user interface that requires the team to abandon the existing `uu-*` commands.

This restraint is intentional. The project should solve the specific coordination problem the team already experiences.

---

## Preserve the current workflow

The existing commands remain unchanged.

In particular, `uu-plan` must continue to work exactly as it does today. It plans repository-grounded work, writes the canonical plan document, creates the initial implementation, validates it, and returns a reviewer handoff.

To avoid moving anyone's cheese, automation is introduced through one new command:

## `uu-build`

`uu-build` begins with the same interactive planning and first-implementation behavior as `uu-plan`, including the strong question-and-answer planning interfaces available in Claude Code and Codex.

After the initial implementation, `uu-build` continues through the rest of the Until Useful workflow automatically.

A user who prefers manual handoffs can continue using the existing skills. A user who wants the runtime to manage the handoffs can invoke `uu-build`.

The new automation therefore extends the methodology without breaking or redefining it.

---

## The Until Useful workflow

The complete manual workflow is:

| Workflow | Command | Input | Output | Context history |
|---|---|---|---|---|
| Propose | `uu-propose` | Half-formed ideas or a broad direction | A complete proposal suitable for `uu-plan` | Always a new context |
| Plan | `uu-plan` | Complete proposal details | Canonical plan, first code draft, and reviewer handoff | Proposal context or a new constructive context |
| Review | `uu-review` | Worker, reviser, or challenge notes | Approval, requested changes, or a blocker | Persistent reviewer context within its review epoch |
| Revise | `uu-revise` | Adjudicated review findings | Corrective code revision and reviewer handoff | Continues the constructive plan/revise context |
| Summarize | `uu-summarize` | Repository and canonical plan | One consistent commit-title suggestion | Current authoritative reviewer context |
| Second opinion | `uu-second-opinion` | Canonical plan and repository state, without prior narratives | Independent approval or material challenge findings | Always a fresh context |

The automated path is:

```text
uu-build
  → interactive planning and initial implementation
  → human plan approval
  → review/revise cycles
  → reviewer approval
  → summarize
  → fresh second opinion
  → prior-reviewer adjudication of challenge findings
  → accepted revisions
  → challenger verification
  → optional additional challenge cycles
  → final summarize
  → workflow report
  → human review and commit
```

The exact ordering of intermediate summaries may be optimized by the implementation, but every second opinion must receive a clean, bounded handoff that does not contaminate its fresh context with prior review narratives.

---

## The key abstraction: context, not agent identity

In Until Useful, an "agent" is best understood as:

> **A protocol operating inside a context with a defined history, purpose, and authority.**

The same model or harness can behave differently depending on the context it inhabits.

A typical task may use:

- `P1`: the initial plan and revise context;
- `R1`: the initial independent review context;
- `R2`: the first fresh adversarial context;
- `R3`: a later fresh adversarial context;
- `P2`: a refreshed constructive context if `P1` becomes stale.

These labels describe context lineage, not vendor identities.

The model and harness are replaceable implementation details. The context boundary is part of the methodology.

---

## Constructive contexts

A constructive context begins with `uu-plan` and continues through `uu-revise`.

Its strengths are continuity and implementation knowledge. It remembers:

- the approved intent;
- repository discoveries;
- architectural choices;
- implementation details;
- tests already considered;
- prior accepted corrections.

Its weakness is context rot. After enough work, it may carry stale assumptions, become anchored to earlier choices, or lose clarity as its history grows.

The runtime should preserve constructive continuity by default, but it must support deliberate context refresh when continuity becomes harmful.

---

## Reviewer contexts

A reviewer context is independent from the constructive context.

It does not accept worker summaries as proof. It uses the canonical plan, repository state, actual diff, tests, and executable evidence to judge the changeset.

A reviewer context is authoritative within a **review epoch**.

Within that epoch, it:

- assesses the implementation against the canonical plan;
- requests justified corrections;
- reviews revisions;
- adjudicates findings raised by the next fresh second opinion;
- produces the clean summary used to seed that challenge.

Separating review from implementation reduces self-confirmation and preserves independent judgment.

---

## Revision cycles

A revision cycle operates inside one review epoch:

```text
constructive context Pn
  → reviewer context Rn
  → REQUEST CHANGES
  → uu-revise in Pn
  → uu-review in Rn
  → repeat until approved or blocked
```

The reviewer identifies defects and defines the justified correction boundary.

The constructive context verifies each finding, implements accepted corrections, adds focused tests, and returns the result.

The same reviewer context then evaluates the revised changeset.

This cycle preserves both:

- constructive continuity in `Pn`;
- evaluative continuity in `Rn`.

---

## Challenge cycles

A second opinion is not another ordinary review. It is a bounded, clean-room, adversarial audit.

After `Rn` approves the current changeset:

1. A summary is produced from the authoritative reviewer context.
2. `uu-second-opinion` starts in a fresh context `R(n+1)`.
3. The fresh context independently audits the canonical plan and repository state.
4. Any material findings return to `Rn` for adjudication.
5. `Rn` decides whether the findings are real, relevant, already resolved, or require human judgment.
6. Accepted findings are sent to the constructive context through `uu-revise`.
7. The resulting revision is verified by `R(n+1)`, the context that developed the new defect theory.
8. Once `R(n+1)` approves, it becomes the new review frontier.
9. Another second opinion, if warranted, starts in a new context `R(n+2)`.

This division of authority is intentional:

> **The prior reviewer adjudicates a challenge; the challenger verifies accepted challenge-driven revisions.**

The second opinion never sends implementation instructions directly to `uu-revise`.

Every proposed change has a reviewer.

That includes changes suggested by the adversarial auditor.

---

## Why challenge cycles must be bounded

A fresh auditor is structurally encouraged to find new issues. This is valuable, but it also means an endless sequence of fresh contexts may continue producing increasingly marginal concerns.

The methodology therefore treats challenge cycles as risk-reduction passes, not proof that no imaginable issue remains.

The runtime should support configurable challenge policies.

Suggested defaults:

| Risk profile | Minimum challenge cycles | Typical maximum |
|---|---:|---:|
| Routine bounded change | 1 | 1 |
| New feature or subsystem | 1 | 2 |
| High-impact correctness work | 1 | 3 |
| Security, safety, or data-integrity work | 2 | 4 |

These are policy defaults, not universal guarantees.

The human may stop further challenge cycles when:

- the configured minimum has been completed;
- the current review frontier approves;
- new findings are speculative, stylistic, or low impact;
- findings repeatedly move beyond the canonical plan;
- a proposed correction would require a material plan change;
- the same disagreement recurs without new evidence;
- further challenge has declining value relative to task risk;
- residual risk is explicitly accepted by the human.

The system should report why the challenge sequence stopped.

---

## Context refresh and context rot

Persistent contexts are valuable, but they are not permanent.

The runtime should track context generations and support controlled refresh.

A constructive context may be refreshed when:

- several challenge cycles have elapsed;
- the practical context limit is approaching;
- it repeatedly misunderstands accepted findings;
- its repository understanding has become stale;
- implementation direction has materially changed;
- the human requests a reset.

A refreshed constructive context should receive durable evidence, not the entire old conversation:

- the canonical plan;
- current repository state and diff;
- accepted review findings;
- latest revision handoff;
- unresolved risks;
- relevant test evidence.

This is a state-compaction operation, not an attempt to preserve every prior thought.

Reviewer contexts rotate naturally through challenge cycles. The new challenger becomes the review frontier after it verifies accepted challenge-driven revisions.

---

## The canonical plan remains in Git

The canonical `docs/uu-<task-slug>.md` plan is the durable statement of approved engineering intent.

It belongs in the repository because it:

- records what the change was intended to accomplish;
- preserves boundaries and exclusions;
- supports later archaeology;
- gives reviewers a stable contract;
- can be referenced by the resulting commit;
- remains useful after runtime provenance has been archived or deleted.

Only the human may materially revise the canonical plan after its initial creation.

The runtime must not silently rewrite intent to match the implementation.

---

## Workflow provenance belongs outside Git

Review reports, revision reports, challenge reports, context identifiers, timestamps, routing decisions, and runtime errors are operational provenance.

They should be stored in SQLite rather than added to the repository by default.

This keeps Git focused on:

- canonical intent;
- source code;
- tests;
- relevant product documentation.

SQLite should contain or reference:

- task state;
- protocol runs;
- context lineage;
- normalized outcomes;
- raw reports;
- cleaned reports;
- finding dispositions;
- approvals;
- timelines;
- challenge-policy decisions;
- runtime failures;
- final workflow reports.

Reports should be exportable when a human needs to share or archive them.

---

## Deterministic workflow, autonomous work

The runtime should never ask a model which protocol should act next.

Protocol outcomes are structured:

- `APPROVE`
- `APPROVE WITH MINOR ISSUES`
- `REQUEST CHANGES`
- `BLOCKED`
- implementation completed
- revision completed
- no current changeset

The Until Useful methodology maps those outcomes to allowed transitions.

For example:

```text
uu-review + REQUEST CHANGES
  → uu-revise

uu-review + APPROVE during a revision cycle
  → summarize and second opinion

uu-second-opinion + REQUEST CHANGES
  → prior reviewer adjudication

uu-review adjudication + accepted findings
  → uu-revise

uu-review or uu-second-opinion + BLOCKED
  → human intervention
```

The harness remains autonomous inside each protocol run. The routing between runs remains deterministic.

---

## Human authority

The human remains the technical owner of the work.

The runtime must stop for human judgment when:

- the plan or scope needs approval;
- repository evidence cannot resolve a product or architectural decision;
- a material plan change is required;
- a protocol reports `BLOCKED`;
- challenge cycles reach policy limits with unresolved risk;
- the final changeset is ready for inspection;
- a commit, merge, push, or release action is proposed.

The runtime must never automatically:

- stage changes;
- commit;
- amend;
- rebase;
- merge;
- push;
- publish;
- discard unrelated work;
- rewrite repository history.

The human should no longer act as a message courier, but should continue to act as architect, adjudicator of product intent, and release manager.

---

## Workflow reports

Every protocol run should create a durable run record.

At completion, the runtime should generate a cleaned, human-readable workflow report.

The report should include:

### Identity

- task title and identifier;
- repository and worktree;
- canonical plan path;
- start and completion times;
- configured risk profile.

### Timeline

- protocol runs in chronological order;
- contexts used;
- approvals and blockers;
- revision and challenge cycles;
- context refresh events;
- human interventions.

### Implementation summary

- high-level behavior changed;
- important architectural choices;
- files or components materially affected;
- tests and checks run;
- important plan deviations approved by the human.

### Review history

- findings raised;
- priorities;
- finding dispositions;
- which context raised each finding;
- which context adjudicated it;
- which context verified the correction.

### Residual risk

- unresolved concerns;
- skipped or limited checks;
- assumptions;
- areas requiring careful human inspection;
- reason the challenge sequence stopped.

### Final outputs

- `uu-summarize` commit-title suggestion;
- final review state;
- human review checklist;
- explicit statement that Git history remains unchanged.

The report should answer not only "what changed?" but also:

> **How did the workflow establish confidence in this changeset?**

---

## User experience

The automated workflow should feel familiar.

A developer starts in Claude Code or Codex and invokes:

```text
/uu-build <proposal>
```

or the host-specific equivalent.

The experience should begin like `uu-plan`, including interactive clarification where needed.

After plan approval, the runtime performs the serial workflow.

The developer may inspect progress, but should not have to copy reports between windows.

At completion, the developer receives:

- the reviewed working-tree changes;
- the canonical plan;
- the suggested commit title;
- the workflow report;
- a concise checklist for final human review.

Existing manual `uu-*` commands remain available at every stage.

---

## Design principles

### Preserve the methodology

Automation must faithfully execute the existing Until Useful process.

### Do not move anyone's cheese

Existing commands and manual workflows remain intact.

### Context boundaries are part of correctness

Freshness, continuity, and authority must be explicit.

### Every change has a reviewer

Challenge findings are adjudicated before implementation and verified afterward.

### Serial before parallel

One repository, one worktree, and one active worker are sufficient.

### Canonical intent is durable

The plan remains Git-tracked and human-controlled.

### Provenance is inspectable

Operational history is recorded outside Git and can be exported.

### Routing is deterministic

Models perform protocol work; code enforces workflow transitions.

### Human judgment is a feature

The system should expose consequential decisions rather than automate them away.

### Expansion must be evidence-driven

Additional models, protocols, parallelism, and integrations should be added only when real use demonstrates a need.

---

## What success looks like

Until Useful Runtime succeeds when:

- existing users recognize the workflow immediately;
- `/uu-plan` continues to behave exactly as before;
- `/uu-build` removes manual message passing;
- the correct context is used for every protocol;
- at least the configured minimum adversarial audit occurs;
- challenge-driven changes are adjudicated and independently verified;
- review cycles terminate for clear, recorded reasons;
- the human receives an understandable account of what happened;
- no Git history changes without human action;
- the system reduces coordination burden without reducing trust.

The intended outcome is not autonomous software development.

It is disciplined, inspectable software development with less clerical work.

---

## North star

> **Most coding automation tries to automate code production. Until Useful Runtime automates the disciplined movement of work through planning, implementation, review, revision, independent challenge, and human judgment—until the result is useful.**
