---
name: uu-summarize
description: Write one concise commit title for the current changeset. Use only when manually invoked; do not modify or commit anything.
disable-model-invocation: true
user-invocable: true
---

# UU Summarize

Inspect repository instructions, the canonical `docs/uu-<task-slug>.md` plan, the current staged and unstaged changes, untracked files, relevant reviewed range, and recent commit subjects. Choose the primary behavioral outcome.

Return exactly one imperative, specific commit-title line ending with ` re: docs/uu-<task-slug>.md`: no Markdown, quotes, list, explanation, or period. Keep the complete line under 90 characters plus the length of the task slug. Use a conventional-commit prefix only when the repository consistently does. Do not edit, stage, commit, or push.

If no identifiable current changeset exists, return exactly: `No current changeset to summarize`
