# AI provider integration — proposal only

Status: design only; no provider calls, credentials, or trading changes.

## Constraints

- AGENTS.md prohibits chargeable API usage. Promotional OpenAI credits do not authorize use of a metered API. Obtain an explicit policy change before implementation or usage, and never silently spend credits.
- Default all external AI networking off. No credentials in repository, logs, prompts, tests or exceptions. Do not send account identifiers, broker responses or sensitive positions to external models.
- AI may explain offline research evidence and suggest analysis; it may not approve or submit orders, bypass the Risk Manager or alter DEMO-only restrictions.

## Proposed architecture

1. Define a typed analysis-only provider interface and offline deterministic mock for tests.
2. Evaluate a genuinely free, terms-compliant local inference provider (e.g. optional owner-run Ollama) as a fallback. Do not claim zero hardware or electricity cost.
3. Treat OpenAI as an optional, explicitly approved future provider only. Promotional credit is finite and not a guarantee against charges. Require user-configured hard application-side budget, per-request token cap, usage accounting, no automatic paid fallback, and fail-closed behavior; provider-side project limits/alerts are not a substitute for a hard cap.
4. Keep provider responses untrusted; validate schemas, strip sensitive data and separate analysis from execution modules.
5. Offline unit tests for missing credentials, provider errors, exhausted budgets, malformed responses, prompt injection and provider fallback.

## Review blockers

- Explicit approval to amend the no-chargeable-API rule before any metered OpenAI integration.
- Verify the selected local model license, actual free availability and runtime compatibility.
- Inspect current application architecture and existing PRs before implementation; avoid overlapping active branches.
- Run pytest, Ruff, strict mypy and packaging checks before claiming implementation readiness.

No runtime integration is implemented by this proposal.
