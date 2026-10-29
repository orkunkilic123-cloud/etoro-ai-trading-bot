# Demo execution contract and lifecycle review

Reviewed 29 October 2026 against the public operation-level OpenAPI snapshot used by
Phase 22: https://api-portal.etoro.com/api-reference/openapi.json . SHA-256:
`549e77e8f37dc167dfb6295e4771faf1f9bb71f62d0e925109cd6aa9a5d299a0`.
No authenticated broker requests or orders were used for this review.

## Selected supported contract

The existing selected route remains exactly
`POST https://public-api.etoro.com/api/v3/trading/execution/demo/orders`.
V2 also exists; it is not a fallback. V3's operation describes open-only orders with
exactly one of amount/units/contracts and one of symbol/instrumentId. Non-MIT orders require
settlementType. The existing implementation uses the reviewed narrow subset:
`action=open`, `transaction=buy`, positive `instrumentId`, `settlementType=real`,
`orderType=mkt`, `leverage=1`, explicit Decimal `units`, `orderCurrency=usd`,
`stopLossType=fixed` and `stopLossRate`. Here `real` is the underlying-asset settlement
inside the Demo account, not the Real account environment.

Response 202 references `UnifiedOrderResponse`: orderId and referenceId matching the persisted
UUID are required by our admission parser before marking pending. The optional token is not
an alternative order ID. Acceptance is asynchronous, never proof of a fill. Unexpected responses,
redirects, malformed acceptance and timeout after a send become unknown and retain reservations.
No POST retries are implemented, including for HTTP errors. The specification calls X-Request-Id
an idempotency GUID, but retention and conflicting-payload semantics remain unverified.

Lookup uses exactly `GET /api/v2/trading/info/demo/orders:lookup`, with one of orderId or
referenceId (the latter is available after a lost open acceptance). `GetOrderInfoResponse`
requires identity/product/request consistency in this application. Position executions use
`positionExecutions[].openingData.units` linked by openingData.orderId, not remainingUnits.
Repeated reads are cumulative snapshots, not increments. A 404 remains unknown.

| Status ID | Interpretation | Terminal |
| --- | --- | --- |
| 1, 2, 11, 12 | Received/placed/waiting/pending trigger; no executions | No |
| 3 | Filled; entire requested unit quantity must be evidenced | Yes |
| 4 | Rejected; zero executions | Yes |
| 5 | Partially filled; strictly between zero and requested units | No |
| 6 | Pending cancellation; may already have partial executions | No |
| 7, 8 | Cancelled/expired; zero executions | Yes |
| 9, 10 | Cancelled/rejected after a partial fill; retains exposure | Yes |

The review fixed a confirmed defect: status 3 previously accepted fewer units than requested
and marked the order terminal/filled. It now fails to unknown through the existing coordinator.
Execution quantities in documented non-executed states also fail closed. Null/malformed nested
status/position objects and boolean/noninteger identity fields produce fixed sanitized errors.
Terminal partial parser results cannot regress to nonterminal partial state. Broker schemas
occasionally contain nullable fields or partial views; rejecting an incomplete response is
intentional and requires later reconciliation, never fabricated execution evidence.

The existing explicit-unit v1 close and close-status routes are retained. Partial close status
continues to require execution rate/time evidence and exact position ownership. Lost close
acceptance without its broker ID remains unresolved: there is no invented reference lookup.
Cancellation submission remains unimplemented; cancellation states can only be observed.

## Existing authorization and recovery reused

The ticket digest binds the account, action, instrument, units, reference price, stop, cost
buffer, currency and optional position. Authorization is explicit, single-use and expires within
five minutes. Changed/expired tickets fail. The existing coordinator rechecks identity, account,
eligibility, risk, kill switch and daily halt before dispatch; it persists a may-have-been-sent
marker before I/O and serializes processes using the risk SQLite transaction. Restart recovery
performs lookup only. Unknown orders block further submission and reservations are never released
by this change. Default ExecutionConfig remains disabled; no execution CLI or approval bypass
was added.

`tests/test_execution_contract_regressions.py` adds contradictory-fill, malformed schema,
partial-cancellation and restart/no-retry regression tests to the existing mocked lifecycle suite.
Existing tests retain timeout-after-send, partial fills, rejection, approval expiry, stale evidence,
kill/daily-loss controls and duplicate-process coverage. All mock credentials are synthetic.

## Remaining first-order blockers

- Public schema compatibility is not account entitlement or owner-verified broker compatibility.
  The authority issuing Demo identity and complete account/cash-flow evidence is still external.
- The market-only request cannot enforce a broker-side maximum entry-price ceiling. Ticket
  reference price and fixed stop are bound to approval, but price gaps remain possible. A future
  bounded-price order needs a separately verified contract; no limit field was invented here.
- Full trusted account/position reconciliation and safe reservation handoff remain separate work.
  No local tombstones or reservation rows are deleted to make a subsequent order pass.
- Actual partial fills, stop installation, reference lookup availability and idempotency retention
  must be independently verified in an owner-operated workflow before order readiness. The next
  owner action is read-only contract/account validation, not a test order.

These changes strengthen offline lifecycle consistency. They do not authorize execution,
activate an autonomous trading mode, or establish first-owner-approved-order readiness.
