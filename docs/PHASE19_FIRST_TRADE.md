# Phase 19 — offline first Demo trade safety review (partial)

**Status:** Preparation only. This phase does not enable orders or supply an execution command. All broker network activity, authenticated calls, and order submission are forbidden during development. Owner-reported Demo portfolio GET success in Phase 18 is read-only evidence, not execution clearance.

## Contract findings

Official eToro [Trading API guidance](https://builders.etoro.com/products/trading), [FAQ](https://builders.etoro.com/faq) and [first-bot example](https://builders.etoro.com/blog/building-your-first-trading-bot) show `POST /api/v2/trading/execution/demo/orders`. The existing code implements `POST /api/v3/trading/execution/demo/orders`, originally documented in the reviewed operation-level OpenAPI `docs/API_FINDINGS.md`. Both v2 and v3 appeared in that prior OpenAPI audit; their exact request and response compatibility remains **unverified against an authenticated broker**. This phase neither switches endpoint versions nor infers validity from examples. **No order may be submitted until v3 contract, payload, acceptance and reconciliation semantics are independently verified.**

The existing `DemoExecutionClient` has a strict Demo-only allowlist and `DemoIdentity` checks, while `ExecutionConfig.enabled` defaults false. RiskEngine retains 1% maximum estimated stop-based trade risk, 3% daily equity-loss halt, exposure limits, durable kill switch, no leverage and reservations. Existing mocked `tests/test_execution.py` covers one-shot dispatch, duplicate prevention, uncertain/partial outcomes, restart recovery, stale data and authorization. No modification to the order coordinator, routes or policy is included in this PR.

## First trade preparation safety model

`etoro_demo_bot.first_trade_preparation.prepare_first_demo_trade(TradeEvidence())` is **pure offline** and defaults to blocking every prerequisite: independently verified Demo identity, fresh complete account, reconciled cash and positions, fresh quotes, instrument eligibility, broker minimum, verified v3 operation contract, trusted owner approval interface, existing Risk Manager PASS, kill switch, daily-loss halt and no unresolved duplicates/unknown orders. A true flag is merely an externally asserted claim; this tool has no broker attestation provider. Even if every flag is true, `execution_authorized` remains false.

## Owner-facing exact order summary — requirements, not a selected order

Before a future order, a separately reviewed trusted interface must show Demo account identity, symbol and instrument ID, underlying/settlement, BUY long only, quantity, notional USD, market/limit type, quote timestamp and maximum acceptable execution price, fixed stop and stop gap assumptions, conservative fees/slippage, estimated stop-based loss in USD and percent equity, per-instrument/aggregate exposures, available cash, minimum order amount, one-time approval digest and expiry. It must verify all values again immediately before any dispatch. **No instrument, amount, price or ticket is selected by this phase.**

## Minimum future owner actions

1. Verify Demo-specific read permissions, account identity, positions, pending orders and available cash privately against the eToro interface; no keys, identifiers or response bodies should be copied to GitHub or chat.
2. Independently inspect the latest official operation-level v3 Demo order schema and exact execution/status response contracts; confirm account capabilities, free access, minimum unit/notional, unleveraged underlying classification and current quotes.
3. Review existing risk DB and daily baseline without resetting it. Check kill switch, 3% halt, 1% estimated trade risk, cash and exposure reservations, uncertain orders and restart recovery.
4. Request an independent review of the owner-operated approval interface. Approve only a particular immutable Demo ticket with short expiry, never generic permission to run a bot. A changed quote, size, instrument, account or stop needs new approval.
5. Only in a separately authorized future release, allow one Demo-only dispatch after final admission checks; follow its status via read-only reconciliation, never blindly retry a timeout. **This PR contains no owner-operated order command**, because current compatibility and trusted account attestation are not ready.

## Verification

Run Python 3.12+ offline `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`, `python -m pip check` and `python -m hatchling build` with existing locked development dependencies. Verify Ubuntu and Windows GitHub Actions on the **final head SHA**. Until then, CI and overall phase completion remain unverified. Keep this PR draft; do not merge or activate trading.
