# Phase 3: manually authorized Demo execution engine

This is an opt-in library coordinator with mocked verification, not an enabled trading service. `ExecutionConfig.enabled` defaults to false. There is no autonomous authorization mode, execution CLI, scheduled trader or credential loader in this package. Coding approval is not order authorization. No authenticated API calls or orders were made during development.

## Architecture and authorization boundary

The existing `DemoClient` remains read-only. The new `execution` package separates immutable tickets/identity evidence, broker transport, eligibility validation, journal, coordinator and broker-status parsing. RiskEngine gained `evaluate_in_transaction` so a risk check and its reservation can commit in the same safety transaction as journal updates; its 1%/3%/leverage and capacity rules are unchanged.

Each Ticket includes the exact account, action, instrument, units, reference price, stop, cost buffer, optional position ID and explicitly confirmed asset currency. Only USD-priced underlying assets are supported. `Ticket.digest` binds the complete immutable ticket. A trusted human interface must call `authorize` with the exact digest, `explicit_user_authorization=True` and a timezone-aware expiry at most five minutes away. The coordinator also requires `ExecutionConfig(enabled=True)` and fresh DemoIdentity evidence. This per-order approval is consumed once before dispatch and cannot be replayed. A risk PASS alone is not authorization. The attached fixed stop and market-price behavior must be shown as part of the user's ticket approval.

`DemoIdentity` is an explicit external attestation from a trusted key-management/account-verification layer, bound to the exact credentials by a SHA-256 digest, local account identity, broker account ID, customer ID and expiry. Unknown, mismatched or expired evidence is rejected by coordinator and transport. Opaque API keys cannot be decoded for environment; the official docs supply no standalone key-scope introspection endpoint. **No attestation issuer or automatic account-ID mapping is implemented.** A caller must not fabricate this evidence from a label such as `ETORO_ENVIRONMENT=demo`. Verified Demo key-management metadata and authoritative account identity are prerequisites to future non-mocked use. eToro's documented server-side key binding remains another safety boundary.

These Python objects are trusted application interfaces, not a sandbox against malicious code with access to process memory, private transport methods or SQLite. Do not expose authorization, configuration or evidence constructors to an autonomous model. A secure human approval UI and trusted data adapter remain integration work.

## Official routes and supported payloads

Source: https://api-portal.etoro.com/api-reference/openapi.json, re-read 2026-10-27. Authentication: https://api-portal.etoro.com/core/getting-started/authentication. Detailed schema notes are in API_FINDINGS.md.

| Method and exact route | Purpose |
| --- | --- |
| POST `/api/v2/trading/info/demo/eligibility` | Non-executing account-specific instrument preflight |
| POST `/api/v3/trading/execution/demo/orders` | Asynchronous opening, 202 accepted |
| POST `/api/v1/trading/execution/demo/market-close-orders/positions/{positiveInteger}` | Close explicit units of a verified position, 200 submitted |
| GET `/api/v2/trading/info/demo/orders:lookup` | Exactly one `orderId` or `referenceId` query |
| GET `/api/v1/trading/info/demo/close-orders/{positiveInteger}` | Closing status and executed units |

Only HTTPS public-api.etoro.com is used. Paths are matched exactly, with positive-integer-only dynamic IDs. Redirects, absolute URL overrides, trailing/encoded path variants, Real routes, transfers and unrelated mutations are rejected. There is no cancellation submission or stop-edit API; cancelled states are observed through reconciliation.

Opening sends `action=open`, `transaction=buy`, `instrumentId`, `settlementType=real`, `orderType=mkt`, `leverage=1`, explicit `units`, `orderCurrency=usd`, `stopLossRate` and `stopLossType=fixed`. Decimal quantities are serialized as exact JSON numbers without binary-float conversion. Here settlement `real` means the underlying asset in the **Demo** account. Take-profit, trailing stops, MIT/limit orders, shorts, margin and futures are not implemented. Fixed attached stops are explicitly documented and account eligibility must allow them.

Closing uses the separately verified v1 endpoint and explicit `InstrumentID`/`UnitsToDeduct`; it never omits units to infer a full close. Unified v3 `action=close` remains unsupported according to its operation prose despite schema enum values. Fresh PositionEvidence must verify account ownership, instrument, position ID, available units and underlying long/unleveraged status. Partial closing also requires the broker's partial-close permission.

## Risk and eligibility preflight

Fresh normalized AccountSnapshot, Proposal and (for closes) PositionEvidence are supplied by a trusted adapter; no raw API normalization layer is added here. Demo identity, complete portfolio valuation, cash-flow reconciliation, fresh realtime prices and a verified UTC daily baseline remain mandatory. Partial/unknown account data must not be marked complete. The coordinator fetches eligibility for the exact instrument and validates:

- `minPositionExposure`, configuration `minPositionAmount`, `maxUnitsPerOrder`;
- opening/closing and partial-close permissions;
- whole/fractional quantities, units sizing and unit-based assets;
- a non-potential `real`/`long` configuration containing leverage 1;
- attached stop support and minimum/maximum stop percentages of allocated margin (unleveraged USD case).

Positive `additionalBufferPercent` is blocked: its exact funds-reservation convention needs more clarification; it is not guessed. No paid market-data entitlement is assumed.

All requests, including closes, run the existing risk engine and reserve capacity. Closes deliberately use the existing conservative hypothetical-long risk/capacity checks and cannot bypass the kill switch, daily halt, 1% cap or balance constraints. This may reject a risk-reducing close when capacity/cash is tight. A separately reviewed reduce-only risk policy is required before improving close availability; this implementation does not weaken limits to accomplish that.

## Durable dispatch and restart protocol

`install_journal(store)` explicitly adds execution tables to the existing risk DB without resetting its baseline, kill switch or reservations. Keep one safety DB per Demo account, shared by every evaluator/coordinator. Schema creation is idempotent; missing/corrupt/locked state is never silently recreated. Protect DB/parent directory with OS permissions and keep it out of Git.

1. Persist `proposed` with immutable ticket digest and a generated UUID request reference.
2. Record explicit expiring approval for that exact ticket.
3. Under SQLite `BEGIN IMMEDIATE`, validate approval/identity, eligibility and full risk, then reserve capacity and commit `risk-approved`.
4. Recheck approval, consume it and commit `submitted` **before** any mutation can leave the process. This marker means dispatch may have occurred, not broker acceptance.
5. Under a new serialized safety transaction, recheck identity, expiry, eligibility, freshness, kill/daily/capacity/duplicate state. Exclude only this ticket's existing reservation while rerunning identical risk rules, then restore/update it atomically. Dispatch exactly once with the persisted UUID; never retry a POST.
6. Record `pending` on a structurally valid matching acceptance, or `unknown` on ambiguous dispatch. A known failed final preflight records rejected without dispatch.
7. Reconcile through GET; never interpret 200/202 submission responses as fills.

Concurrent submissions of one ticket do not send twice. An unresolved submitted/unknown order blocks new submissions. A crash after the submitted marker (even before the network write) produces read-only recovery, not a retry. A failed DB commit after network activity leaves the durable submitted marker and request UUID available for recovery. A stranded risk-approved entry is not automatically resumed; it requires manual review. Recovery does not manufacture authorization or clear the kill switch.

The final safety check and bounded HTTP dispatch hold the SQLite write lock. A kill committed before admission prevents dispatch; a kill cannot retract an already admitted/in-flight HTTP request. Concurrent safety operations may return a lock error while a request is in flight and must be treated as unsuccessful, not silently acknowledged. Transport timeouts are 5 seconds to connect and 15 seconds for other operations. Storage failure always blocks further dispatch.

## Reconciliation and capacity accounting

The lifecycle is proposed → risk-approved → submitted → pending → filled/partially-filled/rejected/cancelled, with unknown for uncertainty. Status mappings are taken from official schemas. IDs 9/10 mean terminal cancellation/rejection **after a partial fill**; they retain partially-filled state, terminal=true, broker status ID and executed units. Status 8 (expired) maps to cancelled with broker status preserved. Unknown IDs, contradictory quantities, wrong account/instrument/order identity, stop mismatch or regressing executed quantity become unknown. Terminal records are not regressed by later polls.

Open executions use `positionExecutions[].openingData.units`, not remaining position units; close executions use `positions[].units` only when execution time/rate are present. Totals are snapshots, not increments, so repeated polls cannot double count. Broker error text is discarded. Opening lookup can recover using persisted X-Request-Id as referenceId when the acceptance was lost. Close lookup requires the returned orderID; a lost close acceptance with no ID cannot be recovered by an invented reference lookup and stays unknown for manual reconciliation. A 404 is not evidence that a POST did not execute.

Reservations remain held for all outcomes, including partial/terminal fills and rejects. Duplicate tombstones are not deleted. This conservatively preserves the Phase 2 accounting and may double count broker-visible exposure. Automatic capacity release/reconciliation is **not** implemented: before sustained production use, add a reviewed broker-position handoff and durable duplicate tombstones so capacity can be released without reopening replay races. A close position is not automatically eligible for another close after a previous journalled attempt.

## Rate limits, logs and Windows validation

Persistent per-account quota timestamps serialize calls across processes: separate execution, eligibility and lookup groups, conservatively paced at least three seconds apart. RateLimit reset and Retry-After cooldowns extend that delay. No sleeps or automatic mutation retries occur; an early mutation call fails closed, while a locally throttled status poll preserves the last known state. Recovery can be invoked again later for remaining pending/unknown records. Other applications using the same key still consume shared broker quota.

Structured coordinator logs contain only fixed event names and lifecycle states. Credentials, account identifiers, quantities, prices, broker error bodies and ticket contents are not logged. Do not enable HTTP wire/debug logging or traceback-local dumping; third-party logging configuration is outside this library's control. Full ticket data is persisted locally for recovery and must be treated as private account data.

On Windows, use the existing setup guide and run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_execution.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

These use synthetic credentials and MockTransport only. There is intentionally no execution-enabling environment variable or CLI command. The existing `check-demo` CLI remains read-only. Do not use real credentials to run tests.

## Remaining production integration limits

Actual account permissions, Demo scope evidence, identity mapping, normalized snapshots/position ownership, market-price fills and API semantics remain untested against eToro. No authoritative live attestation provider, approval UI, portfolio reconciler, background polling service or autonomous trader is connected. A market stop bounds estimated risk, not realized losses under gaps/slippage; a market order has no guaranteed entry-price ceiling. Idempotency retention and conflicting UUID payload behavior are undocumented, so POST retry remains prohibited even though v3 documents an idempotency UUID. The close timeout gap and conservative reservation/close policies require operator review. These are deliberate deployment gates; mocked test success alone is not a production-readiness claim.
