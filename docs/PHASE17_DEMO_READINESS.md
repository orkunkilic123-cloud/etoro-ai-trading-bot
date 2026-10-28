# Phase 17 — eToro Demo first-read readiness (partial, offline)

**No authenticated requests or orders were executed to prepare this phase.** This document is a checklist, not proof of broker access or permission to execute. The existing execution coordinator stays disabled and the permanent 1% estimated trade-risk / 3% daily equity-loss halt, kill switch, Demo-only routing and no-leverage rules remain unchanged.

## Official API source review (28 October 2026)

- https://api-portal.etoro.com/getting-started/authentication specifies a Demo-specific key environment and Read vs Write permissions. Requests use `x-api-key`, `x-user-key` and a unique UUID `x-request-id`.
- https://builders.etoro.com/get-started documents the `GET /api/v1/trading/info/demo/portfolio` read and eToro's account verification prerequisite.
- https://builders.etoro.com/faq documents `POST /api/v2/trading/execution/demo/orders`, while the existing repo `docs/DEMO_EXECUTION.md` cites a previously reviewed OpenAPI specification with **v3** for opening orders. **Version discrepancy is unresolved** until the owner independently verifies the currently published operation-level OpenAPI specification and contract. Do not guess or switch routes; no orders.
- Existing `DemoClient` has exact-path, GET-only read access for Demo portfolio and the existing rates route, with no redirects; `etoro-demo check-demo` makes an actual authenticated portfolio GET and is **not invoked by automated tests**. Its confirmation string does not prove identity or key scope.
- The repository does not implement a trusted normalization/attestation service for account snapshots, positions, costs, fresh quotes, cash-flow reconciliation or an approval UI. This phase must not mark these verified from a mere success status code.
- The existing API reference/recorded route contract may differ from publicly presented quickstart examples; only operation-level current specifications and validated response shapes qualify for implementation changes.

## Offline evidence model

`etoro_demo_bot.demo_readiness.assess(DemoEvidence(...))` returns explicit blockers. All evidence defaults false; it does **not** access keys, files, network or broker clients. A read-only readiness assessment needs independently confirmed official contract, Demo read-scope key and Demo identity. Trade preparation additionally needs complete portfolio, reconciled available cash, eligible unleveraged instrument, fresh quote, costs, daily opening equity and kill-switch review. Even all true **never authorizes execution**. This tool relies on externally verified attestations: supplying `True` does not create evidence.

## Minimum owner actions for the FIRST authenticated READ-ONLY Demo test

1. In the official eToro account portal, verify the retail account is approved and the API feature is available free under current account terms.
2. Generate a **Demo / Read-only** key (never Real and never Write), verify its permissions and required scope in the official portal; optionally restrict source IP and expiry. Keep the keys solely in private local environment variables, not GitHub, ChatGPT, issues, CI or logs.
3. Locally configure the existing `ETORO_API_KEY`, `ETORO_USER_KEY`, `ETORO_ENVIRONMENT=demo`, `ETORO_DEMO_KEY_CONFIRMED=true` in a private shell/session. The confirmation is a human statement, not automatic broker attestation.
4. Review the official portfolio contract and confirm the `GET /api/v1/trading/info/demo/portfolio` operation remains supported and Demo-scoped.
5. **Separately opt in** and run `etoro-demo check-demo` manually on a trusted machine. This is an authenticated portfolio GET; never run this as part of automated development, CI, or an agent.
6. Privately review API outcome, account identity and completeness; do not paste account data, secrets, tracebacks or sensitive balances to the repository. A 200 response alone is not verified cash, market data or trading eligibility. Record only sanitized pass/fail evidence for later independent review.

No owner action is needed to run the **offline automated tests**. There is no authenticated read-only smoke workflow running by default.

## Separate checklist — FUTURE owner-approved virtual trade (NOT READY)

- Reconcile eToro's current execution OpenAPI version, response/status semantics, rate limits, order minimums, quote/price contracts and uncertain-submission idempotency; settle the v2/v3 conflict without guessing.
- Build an authenticated, independently trusted Demo identity attestor and complete portfolio/position/available-cash normalizer. Validate pending orders, reservations, fees, quotes, market hours and instrument/stop eligibility for a demonstrably unleveraged underlying long asset.
- Establish a verified UTC opening-equity baseline, reconcile external cash flows, inspect the persistent kill-switch and 3% daily halt, verify the 1% estimated trade risk and risk/position/exposure/cash ceilings. Do not reset persistent safety state to make an order pass.
- Review restart recovery, timeouts, status lookup, duplicate tombstones, ambiguous submissions, partial fills and reservation release. A transport timeout or 404 **must never cause an automatic retry**. The existing coordinator conservatively retains reservations after terminal events; manual reconciliation is currently a blocker for sustained use.
- On a trusted owner-operated interface, prepare a **small virtual amount** and **verified eligible liquid unleveraged instrument** only after market rules, stop loss, units, minimum order size and costs are known; this checklist does not select one.
- Show the **exact immutable Demo ticket** (account, instrument, side, units, order type, price constraints, fixed stop, expected fees and max estimated risk, expiry) and independently seek explicit human approval for that specific order. Approval to implement this phase is never order approval.
- Reverify Demo-bound credentials, portfolio, quote age, cash, risk, kill switch, expiry and any change to ticket immediately before a single dispatch. Persist dispatch state before network I/O. Do not execute without an additional, separate future authorization and controlled operational review.
- Observe broker acknowledgement, partial/complete fill or rejection using read-only reconciliation. Unknown outcome remains blocked and requires manual handling. Never infer a fill from HTTP acceptance.

## Validation

Automated coverage added: default-deny evidence, required read scope, all-attestations-without-order-authority, invalid input and type checks. These are **mock-free pure-function** tests; no live eToro credentials, transport or requests. Run `python -m pytest tests/test_demo_readiness.py`, then `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`, `python -m pip check`, and packaging checks on both Ubuntu and Windows. CI success must be checked from GitHub Actions before review. Other Phase 17 requested work (full end-to-end connection adapter and authenticated contracts) is **not implemented** and remains gated.

## Follow-up: official route reconciliation and offline cash observation

The official eToro [Trading product](https://builders.etoro.com/products/trading) and [Demo migration guide](https://builders.etoro.com/blog/from-demo-to-production-trading-bot) publish **v2 Demo order** examples. The repo's 27 October operation-level OpenAPI audit (docs/API_FINDINGS.md) explicitly lists **both v2 and v3 Demo opening operations**. This is a version coexistence issue, not proof of an invalid v3 route. Exact v3 wire compatibility and permissions have **not** been independently exercised; therefore preserve the existing implementation, keep execution disabled, and prohibit authenticated orders. Neither v2 nor v3 is permitted for a first owner read-only test.

The official [available-cash guide](https://api-portal.etoro.com/guides/calculate-available-cash) documents `credit - (manual ordersForOpen + all orders)` using GET `/api/v1/trading/info/demo/pnl`. A pure offline helper `normalize_demo_cash` evaluates this formula using synthetic dictionaries, requiring complete enumerations and valid nonnegative Decimal amounts. It explicitly returns `trusted_for_risk=False`; **it cannot establish verified account ownership, complete positions, margin exclusions or cash-flow reconciliation**. No P&L GET route has been added to the production broker client's allowlist, and no authenticated read was conducted. Official [equity guidance](https://api-portal.etoro.com/guides/calculate-equity) is available, but requires independently verified invested capital and unrealized P&L; that account/risk mapping is deliberately unimplemented.

The repo already contains mocked lifecycle coverage in `tests/test_execution.py`; no new broker-status assumptions or order path were introduced. Real identity, portfolio and positions normalization remain blocked rather than treating untrusted raw objects as authoritative. Automated tests must verify all additions on both platforms; only confirmed green checks count.
