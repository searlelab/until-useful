# Reliable `uu-build` Completion with Current Opus Reviewers

**Canonical plan document:** `docs/uu-build-reliable-completion.md`

## Summary

Make `uu-build` complete reliably under targeted permissions, require an up-to-date Claude Code, use the latest available Opus for every Claude-owned role, invoke protocol contracts deterministically, constrain structured output at generation time, and recover once from schema-only output failures.

Replace the existing canonical plan with this complete revised plan before changing implementation files.

## Key Changes

### Readiness, permissions, and early recovery

- Run `uu-runtime doctor --live --timeout <seconds>` before planning or implementation.
- Check the runtime database, repository, installed skills, authentication, network access, Claude Code version, model resolution, effective tool rules, and a read-only structured-output probe.
- Require Claude Code `2.1.219` or newer initially, because that is the documented minimum for Opus 5. Keep this minimum centralized and update it when a newer model family requires a newer client.
- When the client is too old, block before implementation with the exact remediation `claude update`; do not silently use an older model.
- Register the task immediately after plan approval with `uu-runtime register-plan`, creating `WAITING_FOR_INITIAL_IMPLEMENTATION`. Record initial Codex implementation before entering review.
- Document normal Codex sandboxing and reusable approval limited to the `uu-runtime` executable when supported. Never require global full access or dangerous permission bypasses.
- Treat project tests, local servers, and browser validation as separate task-specific permissions.
- Emit long-call heartbeats on stderr while preserving JSON-only stdout.

### Current-model enforcement

- Default every Claude-owned role to the family alias `opus`: initial review, verification, challenge, adjudication, challenge verification, schema repair, and summarization.
- Pass `--model opus` explicitly on both new and resumed sessions; never inherit the user’s global `"model": "sonnet"` setting.
- Do not configure a fallback model. A capacity, entitlement, restriction, or provider failure must block rather than silently fall back to Sonnet or an older Opus.
- Parse the Claude JSON result’s `modelUsage` field and persist:

  - requested alias;
  - observed concrete model ID;
  - Claude Code version;
  - provider when detectable;
  - whether the model satisfied the configured family floor.

- For the current Anthropic-backed setup, require the observed model to be Opus 5 or newer. Reject Sonnet, Opus 4.x, missing model identity, or an unreported substitution.
- Add model-family floors for every supported alias so future configurations cannot use stale families:

  - `opus`: Opus 5 or newer;
  - `sonnet`: Sonnet 5 or newer;
  - `haiku`: resolve through the current `haiku` alias and validate against the maintained Haiku floor.

- Use aliases for “latest”; allow full model IDs only through an explicit `--pin-model` option. Reports must distinguish a moving alias from a deliberate pin.
- Add `--model`, `--minimum-model`, and `--pin-model` to task registration and recovery interfaces. Normal `uu-build` uses `--model opus` with the maintained minimum.
- Show requested and observed models in `doctor`, `status`, context listings, and final reports.
- Override the old Sonnet model when repairing task `d1c8e617-ac17-4b08-bf10-f900d523b4c7` by resuming session `8ef7b62e-ff10-4f06-a016-9e8d3ea37a84` with `--model opus` after upgrading Claude Code.
- Fresh-session isolation remains mandatory for second opinions. Automated model-family diversity is dropped in favor of the explicit all-Opus policy unless the human requests a different current model.

### Deterministic protocol invocation and schemas

- Stop sending `/uu-review`, `/uu-second-opinion`, and `/uu-summarize` as prompts because their `disable-model-invocation` setting prevents reliable Skill-tool activation.
- Validate and inject the installed `SKILL.md` contract directly into each non-interactive prompt. Keep manual skill invocation disabled and unchanged.
- Build schemas from both protocol and workflow purpose.
- Constrain priorities to `P0`–`P3` and dispositions to `ACCEPTED`, `PARTIALLY_ACCEPTED`, `REJECTED`, `ALREADY_RESOLVED`, or `BLOCKED`.
- Require empty dispositions outside challenge adjudication. Challenge adjudication must cover every challenged finding exactly once.
- Enforce:

  - `APPROVE`: no actionable findings;
  - `APPROVE_WITH_MINOR_ISSUES`: P3 findings only;
  - ordinary `REQUEST_CHANGES`: at least one P0–P2 finding;
  - second-opinion `REQUEST_CHANGES`: at least one P0/P1 finding.

- Keep runtime validation synchronized with schema enums as defense in depth.

### One bounded structured-output repair

- Preserve raw Claude output, parsed payload, validation diagnostics, model identity, session ID, and repository snapshots when validation fails.
- Mark the attempt `INVALID_OUTPUT` rather than discarding it.
- Allow exactly one repair when the completed model call failed only schema/protocol validation.
- Resume the same session using the current required Opus model, disable all repository tools, and ask it to re-emit its completed judgment under the exact schema.
- Never normalize invented values such as `accepted_minor`, `accepted_by_design`, `minor`, or `low` in deterministic code.
- Preserve both attempts. A second invalid result blocks without retry.
- Add `uu-runtime recover-invalid-output --task <id> --model opus` for existing blocked tasks.
- Recover the InstrumentHub task from its recorded pre-failure state and existing R1 session without duplicating the full review.
- Never repair authentication failures, permission denials, timeouts, context exhaustion, repository mutations, tool failures, or ambiguous semantic results.

### Least-privilege tools and documentation

- Add optional `.until-useful.toml` configuration for the model policy and exact allowed reviewer command prefixes.
- Default Claude to read/search tools and narrow Git inspection. Remove generic `Bash`.
- Reject shell operators, substitutions, environment assignments, nested shells, unresolved paths, destructive Git, and undeclared test commands.
- Retain before/after Git snapshots and block on any Claude-owned worktree mutation.
- Document Claude updating, alias versus pinned-model behavior, provider restrictions, model verification, permissions, preflight, resume, invalid-output recovery, interruption recovery, and transcript auditing.
- Explain that no Codex approval dialog may mean the command was already permitted by the active host policy; it does not prove that the workflow has no permission boundary.

## Test Plan

- Simulate Claude Code versions below and above the maintained minimum.
- Verify an outdated CLI blocks before implementation with `claude update` guidance.
- Verify every automated command passes `--model opus`, including resumed sessions and schema repair.
- Feed fake `modelUsage` results for current Opus, stale Opus, Sonnet substitution, missing identity, and explicit pins.
- Verify stale or substituted models block before their output can advance workflow state.
- Reproduce the observed `minor`, `low`, `accepted_minor`, and `accepted_by_design` payload.
- Verify one tool-free repair preserves both attempts and transitions only once; a second malformed result blocks.
- Verify the installed skill contract is injected without invoking Claude’s Skill tool.
- Verify plan registration precedes implementation and existing `start` callers remain compatible.
- Verify heartbeat output stays on stderr and stdout remains valid JSON.
- Verify generic Bash, write tools, destructive Git, and undeclared commands are denied.
- Run the full unit suite and `git diff --check`.
- With explicit approval, run a live smoke proving:

  - the CLI satisfies the minimum;
  - `opus` resolves to current Opus;
  - fresh and resumed sessions retain current-model enforcement;
  - structured-output repair works;
  - review, challenge, and summarization complete;
  - the worktree remains unchanged.

- Recover the existing InstrumentHub task and confirm its repaired review runs on current Opus and proceeds without duplicating the completed audit.

## Assumptions and Defaults

- Automated `uu-build` uses the latest Opus through the `opus` alias.
- Current-model enforcement requires both a sufficiently recent Claude Code and verification of the concrete model returned in `modelUsage`.
- Aliases are preferred because they advance over time; full IDs are explicit pins.
- No fallback to an older model or another family is acceptable.
- One schema-only repair is allowed; semantic normalization and repeated retries are forbidden.
- Manual skills retain `disable-model-invocation: true`.
- Human plan approval, final review, and exclusive Git-history control remain unchanged.
- Browser and local-server permissions remain outside the runtime’s generic permission profile.
