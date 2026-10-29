# Phase 22 — P&L to Risk integration (partial, execution disabled)

## Official order contract audit, 29 October 2026

Official eToro Builders [Trading](https://builders.etoro.com/products/trading), [FAQ](https://builders.etoro.com/faq), [first bot](https://builders.etoro.com/blog/building-your-first-trading-bot), and [migration](https://builders.etoro.com/blog/from-demo-to-production-trading-bot) pages explicitly show **POST /api/v2/trading/execution/demo/orders** with `x-api-key`, `x-user-key`, unique `x-request-id`, and example fields `action=open`, `transaction=buy`, `instrumentId`, `orderType=mkt`, `amount` or `units`, `orderCurrency=usd`, `leverage=1`. The repository's earlier operation-level OpenAPI audit (`docs/API_FINDINGS.md`) separately documents **POST /api/v3/trading/execution/demo/orders** and the current `execution/client.py` still implements v3. The latest machine-readable OpenAPI document could **not be retrieved for independent field-by-field inspection in this review**. Therefore current v3 order request shape, accepted response schema, statuses and lookup compatibility cannot be certified and a v2 write adapter cannot safely be substituted merely from tutorial examples. **Both variants remain prohibited for the first submission.**

## Actual integration added

`broker_evidence_gate.prepare_pnl_risk_observation()` now composes the existing `normalize_demo_cash()` parser with the Phase 21 risk bridge. The cash parser requires all documented P&L credit, manual orders-for-open and pending orders amounts and conservatively subtracts reservations. Invalid, missing, over-reserved and nonfinite values fail closed. The resulting `AccountSnapshot` is deliberately `complete=False` and `cash_flows_reconciled=False`, even when every external evidence flag is true. It therefore **cannot pass the existing Risk Manager's safety admission** until a separately verified authoritative Demo identity and full portfolio/position adapter exists. It never makes network calls, loads credentials, creates authorization or dispatches orders. This reuses existing modules rather than introducing another checklist.

This integration accepts only inputs explicitly identified as the official P&L response **not** the separate `GET /demo/portfolio` response. It cannot prove account identity, position ownership, fresh valuation, pending execution state or quote provenance. Those are still blocked.

## Precise blockers before first Demo virtual order

1. Obtain authoritative up-to-date operation-level OpenAPI for the **v2 and v3** Demo order endpoints, including exact payload validation, request idempotency, accepted/failed response schema and status/reconciliation lookup. Verify user-key Demo Write scope independently. Do not send a test order until the owner authorizes an exact virtual order.
2. Complete and review trusted authenticated **read-only owner-operated** schema verification for Demo account identity, P&L/portfolio available cash, complete positions, pending orders, market/session/quote freshness, USD valuation and order minimum/stop requirements. Do not share keys, account IDs or raw portfolio responses.
3. Implement source-verified authoritative normalization and connection to the existing Risk Manager, preserving original daily UTC baseline, the 1% risk ceiling, 3% daily loss halt, kill switch, cash/exposure reservations, unleveraged long-only instrument restriction and restart recovery. Never silently mark unverified observations complete.
4. Only then review an isolated owner-only one-order approval and preview interface with exact payload digest and short expiry; recheck risk immediately before one dispatch and reconcile outcomes without automatic retry of uncertain submissions.

**No first-order execution command is provided.** Existing disabled execution code, tests, research and recovery mechanisms remain untouched. This is a partial Phase 22 draft and must not be merged until integration and final-head Ubuntu/Windows CI are reviewed.

## Follow-up local contract review

Retrieved the public operation-level specification without authentication on 29 October 2026:
https://api-portal.etoro.com/api-reference/openapi.json
SHA-256: 549e77e8f37dc167dfb6295e4771faf1f9bb71f62d0e925109cd6aa9a5d299a0

v2: responses ['200', '400', '401', '404', '500', '429']; request {'$ref': '#/components/schemas/TradingDemoAdminApi_UnifiedOrderRequest'}
v3: responses ['202', '400', '401', '403', '404', '500', '429']; request {'$ref': '#/components/schemas/TradingDemoAdminApi_UnifiedOrderRequest'}

Both versions currently coexist. v3 requires stricter settlementType validation and returns 202; v2 returns 200. Both require asynchronous reconciliation via GET /api/v2/trading/info/demo/orders:lookup, using orderId or referenceId. Acceptance is not a fill. No route was switched or enabled. Broker idempotency retention, account entitlements and actual compatibility remain unverified.

The P&L 200 schema is PortfolioResponseWithPnl with clientPortfolio envelope and camel-case mirrorId. Added an offline cash adapter for that verified shape and connected it to the existing incomplete risk snapshot. Decode JSON numbers as Decimal; binary floats are deliberately rejected. Position valuation/identity, mirrored portfolios, complete reservations and cash-flow reconciliation remain unverified; no snapshot is promoted to authoritative. The older explicit normalized-input helper remains supported. Monetary precision is isolated and extreme exponents/duplicate exposures now fail closed.

GitHub-hosted CI remains pending/unavailable because of the owner-reported Actions billing allowance; no workflow or billing workaround was introduced. Local checks are recorded separately.

### Local verification record

29 October 2026, Codex Linux/Python 3.12: complete pytest **900 passed**; Ruff lint and formatting passed; strict mypy passed (115 files); pip check passed; editable installation and hatchling wheel/sdist builds passed. Existing offline intraday CLI benchmark/bootstrap demos completed for both EUR 500 and EUR 1,000 into separate new /tmp directories. These are synthetic engineering outputs, not historical performance evidence. Windows was not run locally. GitHub-hosted CI is pending because of the owner-reported exhausted allowance; no additional run was requested and no workflow changed.

The code is ready for review as a partial, disabled integration improvement, not deployment or first-trade clearance. The shortest safe path remains owner-operated read-only schema/identity and position/cash reconciliation; a separately reviewed current v3 payload/status adapter and uncertain-outcome recovery; then exact one-ticket owner authorization with fresh risk checks. Do not clear or recreate safety state to obtain a pass.
