# Iterate *Until Useful*

Until Useful is a portable six-skill manual workflow for open coding-agent sessions:

1. `uu-propose`: explore a user-supplied direction and recommend one problem to plan
2. `uu-plan`: create and execute a repository-grounded plan from a pasted proposal
3. `uu-review`: review another coding agent's work from its pasted summary
4. `uu-revise`: adjudicate pasted review feedback and implement justified fixes
5. `uu-summarize`: return one concise commit title for the current changeset
6. `uu-second-opinion`: independently audit an approved changeset from a fresh session

An optional seventh Codex-only skill, `uu-build`, keeps planning and revisions in the active Codex task while a local runtime invokes persistent or fresh Claude Code contexts for review, adversarial challenge, adjudication, verification, and final summarization.

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

Large summaries, reviews, proposals, and notes can be pasted as multiline text after the invocation.

## Until Useful Runtime V1

V1 is deliberately asymmetric: the current Codex task is the constructive `P1` context, while Claude Code supplies persistent reviewer contexts and fresh second opinions. Install the local CLI in a Python 3.11+ environment, install the skills for Codex and Claude, and check the setup:

```sh
python3 -m pip install .
./install.sh --claude --codex
uu-runtime doctor
```

Invoke `$uu-build proposal` in Codex for the normal workflow. Runtime state and reports are stored outside Git by default in `~/.local/state/until-useful/runtime.sqlite3`; override that location with `--database` or `UU_RUNTIME_DB`.

The CLI also supports recovery and inspection through `start`, `next`, `record-codex-result`, `status`, `resume`, `report`, `contexts`, `refresh-context`, `recover-interrupted`, `stop`, and `doctor`. Commands emit JSON for orchestration except the default Markdown report.

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

Existing same-named `uu-*` skill folders are refreshed on every installation; unrelated skills are not changed. `uu-build` is installed only for Codex in V1. Preserve existing `uu-*` skills explicitly:

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
