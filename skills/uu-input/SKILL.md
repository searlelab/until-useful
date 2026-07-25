---
name: uu-input
description: Resume a scripted uu-build task that needs human guidance, in its original Codex implementation task.
---

# Until Useful Input Resolution

Use only as the Codex-only companion to `$uu-build`. This skill does not change the portable manual Until Useful workflow.

Invocation: `$uu-input <task-id> <guidance>`.

1. Confirm this is the original P1 Codex task. Run `uu-runtime status --task <task-id>` and verify its `repository_path` is the current repository. Never claim the runtime can locate, create, or reopen a Codex task.
2. Pipe the human guidance verbatim to `uu-runtime provide-input --task <task-id> --input -`.
3. Read `uu-runtime next --task <task-id>`. Treat its `INPUT_RESOLUTION` envelope as authoritative evidence: canonical plan, preserved payload, diagnostics, triggering run, and allowed decisions.
4. Decide `REVISED`, `RETRY`, `APPROVE`, `NEEDS_INPUT`, or `FAILED`:
   - `REVISED`: apply the portable `uu-revise` contract to warranted corrections, validate them, and include a revision report.
   - `RETRY`: only after a prerequisite or interruption is demonstrably resolved.
   - `APPROVE`: include an evidence-backed disposition for every preserved P0–P2 finding.
   - `NEEDS_INPUT`: include one focused question.
   - `FAILED`: include attempted approaches and evidence that more input cannot resolve the approved task.
5. Pipe the JSON decision to `uu-runtime record-input-resolution --task <task-id> --input -`.
6. If the result is `IN_PROGRESS`, continue `$uu-build`; otherwise report the outcome and detailed state separately.

Do not stage, commit, push, merge, rebase, or rewrite Git history.
