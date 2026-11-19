# Domain Docs

The shared domain language for the Qwen chat stack lives in the hub repo, `alstomli/llm-inference-server`.

## Before exploring, read these

- **Shared glossary**: `GLOSSARY.md` in `llm-inference-server`. With a sibling checkout it is at `../llm-inference-server/GLOSSARY.md`; otherwise read [it on GitHub](https://github.com/alstomli/llm-inference-server/blob/main/GLOSSARY.md). It covers system-wide terms (profile, alias, adapter, acceptance…).
- **Shared ADRs**: `docs/adr/` in `llm-inference-server`. Read the ones that touch the area you're working in.

If any of these files don't exist, **proceed silently**. The `/domain-modeling` skill creates them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the glossary. Don't drift to synonyms the glossary explicitly avoids. If a concept you need is missing, note the gap for `/domain-modeling` rather than inventing language.

## Flag ADR conflicts

If your output contradicts an existing ADR, say so explicitly rather than silently overriding it.
