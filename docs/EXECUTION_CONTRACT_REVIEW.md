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

The same snapshot also documents `orderType=limitIOC` and `limitRate` in
`TradingDemoAdminApi_UnifiedOrderRequest`. The previous implication that no official bounded-price
create field exists was incorrect. This is a documented create capability, not an enabled
application contract: the lookup/eligibility gaps below still prevent complete verified support.

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

## Recovery and concurrency corrections

The follow-up recovery review reproduced and corrected these defects offline:

- Recovery previously sorted by creation order. Because all status reads share a persistent
  cooldown, the first still-pending order could consume every available poll indefinitely.
  Recovery now prioritizes the least recently journalled order; successful and uncertain polls
  move it to the back. Locally throttled reads append no event. The existing event sequence
  preserves rotation across restart without a new schema, polling sleep or quota reset.
- Another worker could discover an unknown order between preparation and final dispatch.
  The final serialized dispatch transaction now rechecks other `submitted`/`unknown` orders
  before any network mutation. Only this ticket's own durable submitted marker is excluded.
  A rejected dispatch retains both reservations and consumes no additional order request.
- Recovery previously trusted the stored ticket JSON without comparing its immutable digest or
  owner. It now verifies the SHA-256 of the exact stored canonical bytes and agreement among
  ticket account, order-row account and safety-store account before lookup. Drift or malformed
  JSON becomes `unknown` with a fixed reason. Last-known executed units, broker status and
  reservations remain intact. This detects inconsistent local evidence; it is not protection
  against an administrator deliberately rewriting both journal data and its checksum.
- Close reconciliation previously counted any non-null `occurred` value as execution evidence.
  `OrderForClosePositionInfoResponse.occurred` is explicitly nullable `date-time`, described as
  UTC. It now requires a parseable timezone-aware timestamp no later than the coordinator's
  observation clock, plus positive execution rate and units. A direct parser caller must supply
  an aware observation time before close execution can be accepted. There is no invented
  submission-time lower bound: the proposal quote timestamp is not a submission timestamp.
  Positive rate/units without a timestamp fail closed instead of silently becoming zero
  execution under a terminal rejection/cancellation. An entirely absent execution tuple remains
  compatible with the documented unexecuted-position view.

`tests/test_execution_recovery_regressions.py` covers persistent fair polling including uncertain
responses, the inter-transaction uncertainty race, ticket/account drift, preservation of prior
partial execution, malformed/incomplete close evidence and blocked unintegrated mutations.
No authorization constructor, risk limit, reservation release or execution default changed.

## Verified extension capabilities and precise integration boundaries

All facts below are from the same public OpenAPI URL and checksum above. They are source-contract
observations, not authenticated entitlement or compatibility claims.

| Official operation/schema | Verified behavior | Why it remains outside executable tickets |
| --- | --- | --- |
| `POST /api/v3/trading/execution/demo/orders`; `TradingDemoAdminApi_UnifiedOrderRequest.orderType`, `.limitRate` | `limitIOC` executes immediately at `limitRate` or better, or cancels if unavailable; `limitRate` is required and positive; deviation exceeding 10% of current market price is rejected. `triggerRate` must be omitted and non-MIT settlement must be supplied. | `GetOrderInfoResponse.type` still documents only `mkt`/`mit`, and its published properties contain no submitted `limitRate` echo. `InstrumentEligibility` has `allowMitOrders`, but no IOC eligibility field. These are concrete create-versus-lookup/eligibility gaps; this application does not guess the IOC lookup type, infer IOC permission from MIT permission, or label an unverified reconciliation path supported. Existing tickets remain market-only. |
| Same v3 create operation, `orderType=mit` | A trigger activates execution **at market price**; it is not a guaranteed entry-price limit. V3 requires `settlementType` omitted for MIT because the platform resolves it. | A trigger cannot enforce the ticket's maximum execution price, and omitted/platform-resolved settlement does not provide the application's required positive underlying-only admission proof. MIT is not substituted for IOC. |
| `DELETE /api/v3/trading/execution/demo/orders/{orderId}` | A 202 acknowledges a cancellation request, not cancellation. `CancelOrderResponse.orderId` identifies the target; `referenceId` is documented as always empty and does not echo the request UUID. Poll the existing lookup: 6 remains pending; 7/9 confirms cancellation, possibly after partial execution. Already closed/cancelled operations are described as idempotent. | The current immutable ticket/approval model supports open or close only. Cancellation needs its own fresh exact-target authorization and durable mutation intent; a consumed opening approval cannot authorize it. No cancellation dispatch/automatic retry is added. The existing parser already observes the documented cancellation states. |
| `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}` | A 200/token means request received. The operation explicitly says not to resend after a lost response; poll `GET /api/v1/trading/info/demo/close-orders/{orderId}` until terminal and preserve any executed quantity. | The same distinct cancellation authorization/journal integration is absent. The route stays outside the exact transport allowlist. |
| `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}` | The documented recovery handle is the returned `orderForClose.orderID`; explicit `UnitsToDeduct` is supported. | Unlike v3 open prose, this operation does not promise request-header-to-lookup-reference recovery. The close-status schema's nullable external `referenceID` does not establish that mapping. Lost acceptance without the broker order ID remains a manual reconciliation blocker. |

The bounded-price create schema discovery is actionable evidence for a future contract extension,
but does not justify changing authorization shape, guessing broker responses or activating a
partly integrated order type. Cancellation is a verified broker capability with unfinished local
authorization integration, not an undocumented endpoint. No extra endpoint was allowlisted merely
to increase coverage.

## Remaining first-order blockers

- Public schema compatibility is not account entitlement or owner-verified broker compatibility.
  The authority issuing Demo identity and complete account/cash-flow evidence is still external.
- The currently implemented market-only request cannot enforce a broker-side maximum entry-price
  ceiling. Ticket reference price and fixed stop are bound to approval, but price gaps remain
  possible. Official IOC create fields exist; complete verified eligibility, lookup and immutable
  authorization integration are still required before adding bounded-price execution.
- Full trusted account/position reconciliation and safe reservation handoff remain separate work.
  No local tombstones or reservation rows are deleted to make a subsequent order pass.
- Actual partial fills, stop installation, reference lookup availability and idempotency retention
  must be independently verified in an owner-operated workflow before order readiness. The next
  owner action is read-only contract/account validation, not a test order.

These changes strengthen offline lifecycle consistency. They do not authorize execution,
activate an autonomous trading mode, or establish first-owner-approved-order readiness.
