# Phase 18 — owner-observed Demo read, offline reconciliation, deployment gate

## Owner observation, 28 October 2026

The owner reports running the existing `etoro-demo check-demo` command in their own GitHub Codespaces session and obtaining the exact success message:

`Demo portfolio GET succeeded. No orders submitted; key scope relies on eToro enforcement.`

This is **owner-reported evidence of one successful authenticated read-only Demo portfolio GET**. It is not independent verification of account identity, API key permission scope, complete portfolio fields, available equity, position mapping, eligibility or any order behavior. No account identifiers, secrets, raw response bodies or balance amounts were received, requested, or saved for this phase. The code in this phase does not make authenticated broker calls.

## Existing implementation audit and limitations

- `DemoClient.portfolio()` is a GET-only allowlisted route, with no redirects and sanitized errors. Existing read-only success is useful but does not independently establish identity; the CLI itself correctly warns that key scope depends on eToro enforcement.
- `demo_cash.normalize_demo_cash` computes a conservative available-cash observation from separately documented P&L `credit`, `ordersForOpen` and `orders` fields. **Do not feed the GET /portfolio raw response into this P&L parser without a verified matching schema.** It always returns `trusted_for_risk=False`.
- Portfolio account identity, position owners, entry and market prices, broker-reserved amounts, currency conversion, total equity, missing pages, stale timestamps, duplicate positions and cash-flow reconciliation remain unverified. A success code cannot set `AccountSnapshot.complete`, `demo=True`, or `cash_flows_reconciled=True` by itself.
- `DemoIdentity` requires external trusted attestation of account/customer IDs and credential binding. No reliable attestation issuer exists; never fabricate IDs or infer Demo scope from a local string.
- Existing `tests/test_execution.py` exercises mocked order lifecycle and recovery, but mocked success cannot prove broker's acceptance or fill semantics. The v2 and v3 Demo order operations coexist in previously reviewed official OpenAPI; real compatibility is still unverified. Keep both execution modes disabled for automatic use.
- Risk remains capped at **1% estimated per trade**, with a **3% UTC daily equity-loss halt**, persisted kill switch, no leverage, no Real routes, exact individual owner approval and no blind POST retries. Approval to write code is never authorization to order.

## Private owner-operated comparison workflow — no new authenticated requests

1. In a trusted private Codespaces session, sign into the eToro interface with the Demo account selected. Do **not** share, screenshot or commit credentials, identifiers or balances.
2. Review the official current API schema for each returned field before labeling any value available cash, equity, quantity or position ID. If undocumented or unsupported, mark the row **UNKNOWN** rather than guessing.
3. Independently view the Demo interface's available cash and open-position count at a similar time. Check for pending orders, reserved funds and recent market movement. If the API portfolio response lacks the same definitions, comparison is **not meaningful**.
4. Use `etoro_demo_bot.owner_comparison.compare_demo_observations` locally *only with independently verified, explicitly supplied observations*. It compares string Decimal available cash and integer position counts; returns only mismatch category names and `verified_for_execution=False`. This helper is not a broker parser, credential reader, exporter, logger or risk adapter.
5. Verify position-by-position instrument, side, units, price/currency, market valuation, order reservations and P&L definitions manually against the interface; until every field is mapped to official response schemas, record **BLOCKED**. Never treat equal counts as evidence of equal positions.
6. Keep findings locally. Only summarize sanitized PASS/BLOCKED counts without raw portfolio data in a future review. Any uncertainty blocks risk admission and virtual trade preparation.

## Separate first controlled virtual trade checklist — future only

1. Confirm the Demo Read-only test and scope. Independently verify identity, complete cash/portfolio/positions, reserved funds and UTC opening equity using current official schemas, plus real eligibility and free market-data access.
2. Obtain formal review of exact v2/v3 submission, status lookup, reconciliation, partial fill, uncertain timeout, minimum notional, fixed stop and one-shot idempotency behavior. Any undocumented or incompatible field blocks execution.
3. Inspect persisted kill switch, daily 3% loss latch, 1% estimated trade-risk check, positions/cash/exposure limits, duplicates and crash recovery. No reset to bypass constraints.
4. Privately select a small virtual amount and eligible liquid **unleveraged underlying long** instrument only after live Demo eligibility and market rules are independently established. **No instrument or order is selected in this PR.**
5. In a separately trusted owner-operated approval interface, present exact Demo account, instrument, action, units, order type, price constraints, protective stop, fees, estimated loss and short expiry. Request explicit approval bound to that one ticket; any change requires new approval.
6. Immediately revalidate before any one-time submission; reconcile acceptance/partial fill/rejection by read-only status lookup. An uncertain outcome must never be retried blindly. No autonomous execution.

## Verification and release

Run offline `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`, `python -m pip check`, `python -m hatchling build` on both Ubuntu and Windows. Treat only the final commit's verified GitHub Actions results as confirmation. Keep PR **draft** until all requested lifecycle tests and trusted normalization are complete. Do not merge or activate trading.
