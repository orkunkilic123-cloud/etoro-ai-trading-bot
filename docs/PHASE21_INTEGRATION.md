# Phase 21 — risk observation bridge, limited and blocked for execution

The existing `broker_evidence_gate` now offers a direct, offline mapping from independently reviewed USD account values and exposures to the **existing** `risk.models.AccountSnapshot` structure. It refuses missing evidence, mismatched types, nonpositive equity, impossible available cash, invalid exposures, and observations older than 60 seconds or in the future. It makes **no authenticated requests** and does not create an execution command. This is an internal bridge, not an eToro response-schema parser or proof of the source data.

## API contract / strict release blocker

The official eToro Builders FAQ, Trading product page and March 2026 migration guide explicitly document `POST /api/v2/trading/execution/demo/orders` with `x-api-key`, `x-user-key`, `x-request-id`; examples show `action=open`, `transaction=buy`, `instrumentId`, `orderType=mkt`, `amount` or `units`, and `orderCurrency=usd`. However the current repository's `execution/client.py` uses a **v3** endpoint and v3 request and response assumptions recorded from a prior OpenAPI audit. Public v2 examples do not establish that the v3 contract has compatible fields, status values, broker-side idempotency semantics or order acceptance. **No order command may be enabled** without confirming the *current official operation-level v3 request/response* or deliberately reimplementing and reviewing v2 with exact corresponding lookup semantics. Preserve existing v3 path as disabled code; do not silently switch versions.

Official sources:
- https://builders.etoro.com/faq
- https://builders.etoro.com/products/trading
- https://builders.etoro.com/blog/from-demo-to-production-trading-bot
- Prior repo OpenAPI audit: `docs/API_FINDINGS.md`

## Remaining integration blockers

- Source-of-truth Demo identity proof, documented complete portfolio/position fields, pending orders, FX and cash-flow reconciliation still require broker-supported data. Arbitrary `BrokerEvidence(True)` claims are *not* authoritative and must never originate from agent outputs or raw API success codes. The bridge accepts only **externally independently reviewed and attested** values.
- No trusted broker adapter calls this bridge yet. Its returned `AccountSnapshot` is a risk-input structure, not execution authority. A risk PASS likewise cannot authorize execution.
- Missing verified market-session flags, minimum order contract, quote timestamp/quality, free entitlement, exact per-trade approval UI, and comprehensive new order lifecycle integration. Existing `tests/test_execution.py` covers mocked rejection, partial fill, no retry, duplicates, kill switch, limits and restart recovery, but does not demonstrate real eToro compatibility.
- Preserve current 1% max estimated risk, 3% loss halt, exposure reservations, kill switch, no leverage, Demo-only routes, no autonomous trading. Never retry an ambiguous POST or infer fills from accepted requests.

## Minimum future owner-only verification

1. Independently confirm official current **v3** order operation (or request clarification from eToro support on v2/v3), Demo-only user-key scope and order schema, status lookup and reference/idempotency rules; do not share credentials.
2. In a trusted account session, verify Demo identity, complete portfolio/positions, pending orders/reservations, available cash, fresh quotes, costs and eligible unleveraged underlying asset using documented response fields; no raw data in issues, PRs or prompts.
3. Record a verified UTC daily equity baseline and retain existing risk state. Review kill switch, loss halt, outstanding unknowns and duplicates.
4. Only after separate implementation review, use a trusted owner-operated exact-ticket preview/approval flow with a short expiry and no autonomous capability; any ticket change invalidates approval. No submission is possible from this PR.

This is **partial Phase 21**; do not merge or enable the execution coordinator until the full integration and final-head Ubuntu/Windows CI are independently reviewed.
