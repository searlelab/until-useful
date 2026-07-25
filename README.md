# Iterate *Until Useful*

Until Useful is a portable six-skill manual workflow for open coding-agent sessions:

1. `uu-propose`: explore a user-supplied direction and recommend one problem to plan
2. `uu-plan`: create and execute a repository-grounded plan from a pasted proposal
3. `uu-review`: review another coding agent's work from its pasted summary
4. `uu-revise`: adjudicate pasted review feedback and implement justified fixes
5. `uu-summarize`: return one concise commit title for the current changeset
6. `uu-second-opinion`: independently audit an approved changeset from a fresh session

Two optional Codex-only skills, `uu-build` and `uu-input`, run the scripted pipeline and resolve its human-input gates while a local runtime invokes persistent or fresh Claude Code contexts.

## Interactive-session design
<img align="right" src="docs/uu_loop.png" width=500 style="margin-left: 15px;">

These skills are designed for one person progressing one problem at a time in one repository worktree across multiple agent windows, with only one active worker at a time. They do not launch new agents, use non-interactive execution, stage changes, commit changes, push branches, change the active model, or make approval decisions. `uu-plan` and `uu-revise` may modify implementation files; the other skills are read-only. They are a manual handoff protocol, not an autonomous workflow: the user selects work, adds context to handoffs, interprets reviews, performs final code review, and alone owns staging and committing.

`uu-build` is the explicit exception to manual message passing. It uses Until Useful Runtime to call Claude Code non-interactively, but it preserves the same protocol authority, human gates, serial execution, and prohibition on automated Git history changes. Existing manual commands remain unchanged.

Select the model and reasoning level in the current session. Once settled, `uu-plan` writes its plan verbatim to `docs/uu-<task-slug>.md` before implementing it. That document carries durable task intent through the loop. After its initial creation, only the human may revise the canonical plan; the human must provide any updated plan to the next manual handoff. `uu-review` reads it but never writes repository files. `uu-revise` runs in a separate session with a corrective objective, not as a continuation of `uu-plan`'s private reasoning: it reconstructs context from the canonical plan, repository state and diff, pasted `uu-review` report, and relevant code and tests; it must not modify the plan file, while still being able to update other documentation when the approved work requires it. Pasted worker and reviewer reports carry the evolving implementation and review context.

Use `uu-second-opinion` once, after `uu-review` approves, as a bounded pre-merge sanity check for material risks missed by the plan/review/revise loop. Start a fresh session and invoke it without arguments; give that auditor the canonical goal document and repository state, but not worker summaries, prior reviews, or revision narratives. If available, select a different model family. A clean audit approves the changeset rather than listing nits. If it reports a substantiated P0/P1 issue, paste the report into the original-context `uu-review` session, which adjudicates it and produces the only review output that may be handed to `uu-revise`. After accepted material fixes, run at most one final second opinion; do not automatically repeat the audit after that pass unless the user explicitly reopens it. Session freshness and model choice are procedural recommendations that the skill cannot enforce.

## Invocation

| Workflow | Claude Code | Codex | Qwen Code |
|---|---|---|---|
| Propose | `/uu-propose notes` | `$uu-propose notes` | `/uu-propose notes` |
| Plan | `/uu-plan proposal` | `$uu-plan proposal` | `/uu-plan proposal` |
| Review | `/uu-review agent summary` | `$uu-review agent summary` | `/uu-review agent summary` |
| Revise | `/uu-revise reviewer report` | `$uu-revise reviewer report` | `/uu-revise reviewer report` |
| Summarize | `/uu-summarize` | `$uu-summarize` | `/uu-summarize` |
| Second opinion | `/uu-second-opinion` | `$uu-second-opinion` | `/uu-second-opinion` |
| Automated build (V1) | Not supported | `$uu-build proposal` | Not supported |
| Automated input resolution | Not supported | `$uu-input task-id guidance` | Not supported |

Large summaries, reviews, proposals, and notes can be pasted as multiline text after the invocation.

## Until Useful Runtime V1

V1 is deliberately asymmetric: the current Codex task is the constructive `P1` context, while Claude Code supplies persistent reviewer contexts and fresh second opinions. Install the local CLI in a Python 3.11+ environment, install the skills for Codex and Claude, and check the setup:

```sh
python3 -m pip install .
./install.sh --claude --codex
claude update
uu-runtime doctor --live --timeout 30
```

`uu-build` requires Claude Code 2.1.219 or newer. Automated review and verification use the moving `sonnet` alias at medium effort with a Sonnet 5 floor; fresh second opinions use `opus` at medium effort with an Opus 5 floor; final title generation uses `haiku` with its maintained floor and no effort override. The live doctor probes every profile and verifies the observed concrete models from `modelUsage`. There is no fallback. Full `claude-*` IDs require explicit pins.

Invoke `$uu-build proposal` in Codex for the normal workflow. Runtime state and reports are stored outside Git by default in `~/.local/state/until-useful/runtime.sqlite3`; override that location with `--database` or `UU_RUNTIME_DB`. A new build registers its approved plan before implementation, so the task ID can resume an interrupted initial draft.

### Permissions and recovery

Normal Codex workspace sandboxing is sufficient. When Codex requests approval for runtime state-file access or the Claude network subprocess, prefer a reusable approval limited to the `uu-runtime` executable. Do not enable global full access, Claude `bypassPermissions`, or `--dangerously-skip-permissions`. Project tests, local servers, browsers, and other application-specific tools need their own narrowly scoped approvals. If no approval dialog appears, the active host policy may already permit the command; that does not remove the permission boundary.

Claude reviewers receive read/search tools and narrow Git inspection by default, never edit/write tools or unrestricted Bash. A repository may add exact test-command prefixes in `.until-useful.toml`:

```toml
[claude]
allowed_commands = [
  "git status",
  "git diff",
  "git log",
  "git show",
  "python -B -m unittest",
]

[claude.roles.review]
model = "sonnet"
minimum_model = "claude-sonnet-5"
effort = "medium"

[claude.roles.second_opinion]
model = "opus"
minimum_model = "claude-opus-5"
effort = "medium"

[claude.roles.summarize]
model = "haiku"
minimum_model = "claude-haiku-4-5"
```

Command rules reject shell operators, substitutions, environment assignments, path-qualified executables, nested shells, and write-capable Git subcommands. Browser and server commands intentionally remain outside this profile.

Resume a task with `uu-runtime resume --task <id>`. Reports expose a stable pipeline outcome (`IN_PROGRESS`, `APPROVE`, `NEEDS_INPUT`, `FAILED`, or `STOPPED`) separately from detailed state. If a completed Claude result fails protocol validation, the runtime retains it and makes one informed, tool-free correction using the originating role's profile. A second invalid result becomes `NEEDS_INPUT`. In the original P1 Codex task, invoke `$uu-input <task-id> <guidance>` to revise, retry a resolved prerequisite, approve with evidence-backed dispositions, ask a narrower question, or record an explicit failure.

For Claude-side auditing, use `uu-runtime contexts --task <id>` to find the session UUID and inspect the matching JSONL under `~/.claude/projects/`. Reports record the requested model, observed concrete model, Claude Code version, and effective policy without storing private reasoning.

The CLI also supports recovery and inspection through `register-plan`, `start`, `next`, `record-codex-result`, `provide-input`, `record-input-resolution`, `status`, `resume`, `report`, `contexts`, `refresh-context`, `recover-invalid-output`, `recover-interrupted`, `stop`, and `doctor`. Commands emit JSON for orchestration except the default Markdown report.

### Runtime design intent

The implementation is intentionally narrower than the complete design. These documents record the target methodology and the observations behind it:

- [Agent-facing project design](docs/until_useful_runtime_project_design.md)
- [Goals, intent, and design rationale](docs/until_useful_runtime_goals_and_intent.md)
- [User stories and decision-shaping notes](docs/until_useful_runtime_user_stories.md)
- [Codex/Claude V1 canonical plan](docs/uu-runtime-codex-claude-v1.md)

## Install

From the extracted bundle:

```sh
./install.sh --all
```

Install only selected agents:

```sh
./install.sh --claude --codex
./install.sh --qwen
```

Existing same-named `uu-*` skill folders are refreshed on every installation; unrelated skills are not changed. `uu-build` and `uu-input` are installed only for Codex in V1. Preserve existing `uu-*` skills explicitly:

```sh
./install.sh --all --skip-existing
```

Complete the rename by removing skill folders from the earlier release:

```sh
./install.sh --all --remove-legacy
```

This removes only the five earlier `project-*` folders from the selected agent skill directories. It does not alter unrelated skills.

Personal installation locations:

- Claude Code: `~/.claude/skills/`
- Codex: `~/.agents/skills/` and/or `~/.codex/skills/`
- Qwen Code: `~/.qwen/skills/`

The `uu-` prefix keeps the suite fast to invoke and avoids collisions with built-in skills. The skills use portable `name` and `description` frontmatter. Codex also reads each optional `agents/openai.yaml`, which disables implicit invocation there. The shared instructions tell every agent to use these workflows only after manual invocation.

## Codex and Claude Code compatibility

Each `SKILL.md` uses the portable `name` and `description` frontmatter shared by both hosts. It also sets Claude Code's `disable-model-invocation: true` and `user-invocable: true`, so the skills appear as slash commands but cannot be selected implicitly. Codex uses the equivalent setting in each optional `agents/openai.yaml` file: `policy.allow_implicit_invocation: false`. Keep both declarations: Claude Code uses the frontmatter setting, while Codex uses its platform metadata for invocation policy and desktop UI labels.
