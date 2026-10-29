# Phase 22 — offline Demo P&L and reservation normalization

## Scope and acceptance criteria for PR #25

This PR delivers offline normalization only. It does not deliver a complete broker integration,
first-trade readiness, trusted account attestation or an execution command.

Acceptance requires:
- Correct available-cash arithmetic: credit minus manual opening allocations minus pending orders.
- Support for the documented clientPortfolio envelope and mirrorId spelling, retaining the older
  explicitly normalized cash input interface.
- Exact bounded Decimal inputs and isolated monetary arithmetic; rejection of missing, invalid,
  nonfinite, negative, over-reserved or malformed observations and duplicate instrument exposures.
- AccountSnapshot output always complete=False and cash_flows_reconciled=False; actual RiskEngine
  rejection even with all external evidence assertions true.
- No changes to execution, authorization, reconciliation, risk limits, kill switch, network routes,
  credentials, dependencies or CI workflows.
- Passing available local automated checks, with Windows and hosted-CI gaps disclosed separately.

The incomplete broker-dependent work below is outside this PR's merge acceptance criteria.
Merging this offline improvement cannot grant permission to trade. Repository branch protection
and required checks remain binding; this scope change does not bypass those controls.

## Implemented behavior and boundaries

broker_evidence_gate.prepare_pnl_risk_observation composes the cash parser and existing Phase 21
risk observation bridge. normalize_demo_pnl_response handles PortfolioResponseWithPnl's
clientPortfolio envelope and camel-case mirrorId. normalize_demo_cash retains the explicit
normalized input spelling mirrorID. JSON callers must decode numbers as Decimal, not binary
floats. The P&L shape must not be assumed to match a separate portfolio GET response.

Cash normalization subtracts manual ordersForOpen (mirror identifier zero) and all supplied orders.
It does not prove that supplied enumerations are complete or that orders are unique, current,
resolved or owned by the account. Repeated allocations can conservatively understate cash;
missing allocations cannot be detected from these fields alone. Identity, positions, account
currency, equity and timestamps are not authenticated by parsing. Equity/exposures are explicit
caller inputs, not values inferred from undocumented broker fields.

Snapshots stay incomplete and unreconciled regardless of evidence flags. Existing RiskEngine
rejects them before creating a reservation. The parser does not release local reservations,
reconcile uncertain submissions, reset safety state or authorize execution. Planned risk remains
capped at 1%, daily loss halt at 3%, with persistent kill switch and Demo-only restrictions.

## Public schema provenance

Retrieved without authentication on 29 October 2026:
https://api-portal.etoro.com/api-reference/openapi.json
SHA-256: 549e77e8f37dc167dfb6295e4771faf1f9bb71f62d0e925109cd6aa9a5d299a0

The P&L 200 response references PortfolioResponseWithPnl. Both v2 and v3 Demo order creation
operations coexist and reference TradingDemoAdminApi_UnifiedOrderRequest. v2 acceptance is 200;
v3 acceptance is 202 and has stricter settlementType rules. Both describe asynchronous lookup
via GET /api/v2/trading/info/demo/orders:lookup with orderId or referenceId. Acceptance is not a
fill. These findings supersede the initial review's inability to retrieve the specification.
No execution adapter or route was changed from these documentation findings.

## Deferred broker integration — not first-trade ready

A separate reviewed effort must establish authoritative Demo identity and key scope; complete
position valuation, available cash, broker/local reservations and cash-flow reconciliation;
fresh quotes/session/eligibility/minimums and costs; current v3 payload/response/status mapping,
idempotency retention and uncertain-outcome recovery; and an exact-ticket owner approval flow.
Public documentation and synthetic mocks do not establish authenticated compatibility.
Unknown or duplicate prior submissions remain blocked. Never retry an uncertain POST blindly,
clear safety state to obtain a pass, or treat this offline PR as order authorization.

## Local review and validation gaps

Full local Linux/Python 3.12 suite: **902 tests passed**; Ruff lint and formatting, strict mypy
(115 files), pip check, editable installation and wheel/sdist builds passed. The earlier synthetic
intraday benchmark/bootstrap demos completed for EUR 500 and EUR 1,000; these are engineering
fixtures, not market-performance evidence. Regression tests include negative mirror identifiers,
Decimal precision, duplicate exposures and rejection by the actual RiskEngine.

Windows has not been run locally. Hosted checks are unavailable because of the owner's reported
exhausted GitHub Actions allowance; earlier checks were failed/cancelled. No CI rerun, workflow
change or billing workaround is part of this review. These are validation gaps, not passing checks.

Technical recommendation for the narrowed scope: **MERGE**, subject to normal owner review and
repository required-check policy. No remaining confirmed defect was found in the offline scope.
This supersedes the previous DO NOT MERGE recommendation, which evaluated full broker integration
and final-head cross-platform CI as Phase 22 completion requirements. Trading remains disabled.
