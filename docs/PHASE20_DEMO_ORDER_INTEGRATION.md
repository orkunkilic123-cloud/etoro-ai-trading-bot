# Phase 20 — first Demo order integration (partial; submission blocked)

The owner-reported successful Demo portfolio GET is read-only evidence, not proof of order permissions, account completeness or usable cash. This phase does not access credentials, call the broker or submit orders. No live or autonomous trading is enabled.

## Official contract findings

Official eToro FAQ, Trading product documentation, and the March 2026 Demo migration guide describe **POST /api/v2/trading/execution/demo/orders**. The existing execution client uses **POST /api/v3/trading/execution/demo/orders**, citing a prior operation-level OpenAPI audit that listed both. Mere documentation coexistence does **not** establish the exact current v3 request/response schema, idempotency retention, broker execution status or permission scope. Consequently, preserve the existing endpoint without modifying routes or enabling an order command. Until exact operation-level schema compatibility is independently verified, **all actual orders are blocked**. Sources: https://builders.etoro.com/faq ; https://builders.etoro.com/products/trading ; https://builders.etoro.com/blog/from-demo-to-production-trading-bot .

## Evidence and integration boundary

The new `broker_evidence_gate.verify_evidence` is an offline, default-deny checklist. It requires independently attested Demo account identity, key scope, reconciled available cash and reservations, complete positions, eligible underlying unleveraged instrument, verified minimum order/quote, current order contract, exact owner approval, existing Risk Manager PASS and absence of unknown prior orders. Even all positive assertions return `may_submit=False`. This is **not** an authoritative broker-data adapter; no undocumented response field has been mapped into `AccountSnapshot` or `DemoIdentity`.

The existing risk engine and manually authorized coordinator already hold a one-shot journal before dispatch and model rejected/partial/unknown outcomes. Their offline tests do not establish real broker behavior. No changes have been made to the 1% estimated per-order trade-risk limit, 3% daily loss latch, emergency kill switch, leverage ban, cash/exposure checks, Demo-only paths or disabled `ExecutionConfig`.

## Owner-operated read-only verification checklist

1. Privately verify in the official eToro portal the **Demo** and **Read** API-key scope and account identity. Never provide keys or screenshots containing them.
2. Run only the existing owner-triggered read-only `etoro-demo check-demo` in your own trusted Codespaces shell; no CI or automated agent execution. Do not run POST requests.
3. In the eToro Demo interface compare independently the current available cash, pending allocations, full positions/instruments/units, quote freshness, order minimums, transaction costs and account identity. Differences or undocumented fields mean **BLOCKED**. The existing portfolio response cannot automatically be fed to the separate P&L cash parser.
4. Verify the **exact latest operation-level** v2/v3 Demo order request, response/status lookup, pricing/stop and retry semantics with eToro official documentation or support. Do not infer that either route is safe merely because an example exists.
5. Record only sanitized pass/fail findings; never commit identifiers or portfolio responses.

## Future first single virtual order — currently blocked

Only after a separate reviewed integration and owner-only interface exist: identify one eligible liquid unleveraged asset; show Demo account, symbol/ID, BUY units/notional, quote timestamp, stop and fees, 1% estimated risk calculation and 3% daily loss state, available cash, position/exposure limits and short expiry. Independently authorize the immutable exact proposal. Check risk, identity, minimum and quote again immediately before one journaled dispatch; reconcile the broker outcome and never blindly retry a timeout. Any altered order needs new approval. No order is selected and no command for dispatch is added here.

## Validation

Run full `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`, `python -m pip check` and `python -m hatchling build` on Ubuntu and Windows. Keep PR draft until final-head CI is green and independent end-to-end account adapter and execution schema audit are completed.
