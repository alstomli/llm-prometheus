# Issue tracker: GitHub (hub in llm-inference-server)

This repo does **not** use its own GitHub Issues. Issues, specs and tickets for the whole Qwen chat stack live in the hub tracker, **`alstomli/llm-inference-server`**. Tickets whose code lands here carry the label `repo:llm-prometheus`.

The full conventions (sub-issues, cross-repo blocking edges, wayfinding) are in the hub's [`docs/agents/issue-tracker.md`](https://github.com/alstomli/llm-inference-server/blob/main/docs/agents/issue-tracker.md). With a sibling checkout, that file is at `../llm-inference-server/docs/agents/issue-tracker.md`.

## Rules for this repo

- Pass `--repo alstomli/llm-inference-server` to every `gh issue` command, because `gh` would otherwise infer this repo.
- **Read a ticket**: `gh issue view <n> --repo alstomli/llm-inference-server --json number,title,body,labels,comments`.
- **List this repo's open tickets**: `gh issue list --repo alstomli/llm-inference-server --label repo:llm-prometheus --state open`.
- **PRs here close hub tickets by full reference**: `Closes alstomli/llm-inference-server#<n>`.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## When a skill says "publish to the issue tracker"

Create the issue in `alstomli/llm-inference-server` with the `repo:llm-prometheus` label.

## When a skill says "fetch the relevant ticket"

Read it from `alstomli/llm-inference-server` as above.
