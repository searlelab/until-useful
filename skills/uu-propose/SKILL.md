---
name: uu-propose
description: Explore a codebase direction and recommend one concrete problem to plan. Use only when manually invoked; do not implement it.
disable-model-invocation: true
user-invocable: true
---

# UU Propose

Turn the text after the invocation into one evidence-backed problem the user may choose to plan. It may be notes, candidate work, or a broad direction such as performance, reliability, or maintainability.

## Rules

- Inspect the repository before recommending work. Do not edit, stage, commit, or push.
- Recommend one problem, not a roadmap or implementation plan.
- Do not claim product-priority authority. State uncertainty and inferences.
- Do not recommend work already completed by the current changeset.

## Method

1. Read repository instructions, relevant documentation, current changes, history, implementation, and tests.
2. Turn the user's direction into concrete, repository-supported candidates; compare impact, risk, leverage, evidence, and dependency order.
3. Recommend the strongest candidate for the user's consideration.

## Report

Use concise sections: **Problem**, **Why this candidate**, **Evidence**, **Desired outcome**, **Boundaries and risks**, and **Planning prompt**. Cite paths or symbols for material claims. End with a compact proposal ready to paste into `uu-plan`; do not prescribe file-by-file changes.
