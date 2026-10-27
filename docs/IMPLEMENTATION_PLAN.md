# eToro DEMO bot: findings and proposed implementation

Status: Phase 1 read-only foundation and Phase 2 Risk Management Foundation and Phase 3 opt-in Demo execution coordinator implemented by user authorization. Phase numbering follows the latest requested scope; the original read-only adapter phase is included in Phase 1. No orders or authenticated broker requests have been made during implementation. See WINDOWS_SETUP.md for setup and limitations.

## Evidence and limitations

The initial repository contained only README.md and a Python-oriented .gitignore. It now contains the read-only client, offline risk engine, pinned dependencies, tests and CI. Python 3.12 and Git are available. GitHub read access was verified previously and the checkout was clean before documentation work.

Reference reviewed: https://github.com/Jakeschincariol/trader-skill (README on main). Its useful pattern is analysis → screening → sizing → risk → approved broker ticket, with offline fixtures and environment-based credentials. It describes Alpaca/IBKR integrations, not proof of eToro API behavior. Its optional permission to enable leverage is expressly excluded here. No reference scripts were installed or run.

Official API documentation was successfully retrieved on 2026-10-27 from https://api-portal.etoro.com and https://builders.etoro.com. See [API_FINDINGS.md](API_FINDINGS.md) for verified endpoints, request schemas, response references, quota groups and source URLs. Earlier network-blocked findings are superseded.

Authentication is verified as x-api-key + x-user-key + UUID x-request-id. User keys are environment-bound: a single user key cannot serve both Demo and Real according to the current portal. Actual existing credentials are unverified: this instance reports no configured bindings or ETORO-named environment variables; no secret files or values were read.

Verified API base: https://public-api.etoro.com. Initial portfolio route: GET /api/v1/trading/info/demo/portfolio; price route: GET /api/v2/market-data/rates. Future creation route: POST /api/v3/trading/execution/demo/orders, asynchronous with explicit idempotency and lookup reconciliation. These are documented capabilities, not tested account access.

Strict Demo enforcement combines Demo-bound credentials, exact route allowlisting and no live fallback. Require leverage=1 and eligibility-confirmed settlementType=real on Demo requests: here real means underlying-asset settlement, not a real-money account. Exclude auto-settlement MIT orders initially. Unified close is currently unsupported despite its schema enum; use the separately documented v1 Demo close route only in a later authorized phase.

The overview says 60 reads/minute; current market-data operation descriptions specify a shared 120/minute quota. Start conservatively below 60 across that group and honor runtime quota headers. Demo execution shares 20/minute; portfolio and order lookup have separate shared 60/minute groups. Eligibility has a dedicated 20/minute limit.

Phase 0 public documentation review is complete, with unresolved account access, pricing/eligibility, quota discrepancy and idempotency edge cases recorded in API_FINDINGS.md. Foundation coding remains subject to explicit approval; account-dependent gaps gate integration and execution, rather than offline scaffolding. Add tests for exact route rejection, Demo scope, settlement versus environment semantics, conditional request fields, quota pooling, 202-versus-fill state, reference-ID reconciliation and delayed/partial market data.

## Proposed architecture

Use a Python package `src/etoro_demo_bot/`, with typed domain models and dependency injection. Initial operation is observe-and-propose only. Autonomous execution remains prohibited without exact-order approval.

| Module | Responsibility |
| --- | --- |
| config | Validate environment configuration; fixed DEMO mode; secret-safe representation |
| domain | Decimal money, UTC timestamps, instrument IDs, portfolio snapshots, proposals and approvals |
| broker/etoro | Sole broker boundary; verified authentication, explicit method/path allowlist, demo identity checks, bounded read retries and response validation |
| market_data | Free source adapters, freshness, provenance, symbol-to-instrument mapping and trading calendars |
| analysis | Features and explainable market assessments; optional future local AI with no broker credentials or execution capability |
| strategies | Deterministic strategy interfaces and a versioned selection policy; produce proposals only |
| portfolio | Reconciled cash, positions, pending orders and reserved exposure |
| risk | Position/order/exposure limits, cash buffer, drawdown stops, no leverage, instrument checks and stale-data rejection |
| approvals | Explicit, expiring, single-use approval tied to a canonical order digest and account |
| execution | Future demo-only state machine; final validation, durable intent, submission and reconciliation |
| storage | Local SQLite for non-secret state, audit records and idempotency ledger; schema migrations |
| orchestration | Bounded scheduling, single execution owner, recovery and kill switch |
| cli/observability | Read-only status/proposals by default; structured redacted logs and health reporting |

Flow: market observations + portfolio → analysis → strategy → sizing/risk → immutable proposal → explicit approval → repeated account/risk checks → demo execution → reconciliation. Models and external content cannot create approvals, alter limits or invoke broker transport.

## Safety design

Use an exact allowlist of verified HTTPS hosts, methods and demo route templates; disable redirects and arbitrary base-URL overrides. Shared read-only instrument routes require explicit classification. No real-money order paths or live switch are included. Unknown account mode fails closed. If no reliable demo isolation can be established, execution remains unavailable.

Only unleveraged long positions in verified eligible instruments are in scope. Validate instrument properties and API order semantics together; reject unknown metadata. Closing may only reduce an existing holding. Count pending orders and reserved cash in exposure checks. A risk PASS cannot authorize an order.

Persist intent before submission. On timeouts or crashes, reconcile using documented IDs before further action; do not blindly resubmit. If the API cannot resolve ambiguity safely, require manual resolution. A kill switch blocks new submissions; it does not implicitly authorize cancellation or liquidation. Every mutation, including closing or cancellation, requires explicit authorization.

## Credentials and local storage plan

Use process environment variables injected by the user's secure local launcher or OS credential manager. Use ETORO_API_KEY for x-api-key and ETORO_USER_KEY for x-user-key; generate a UUID x-request-id for each logical request (persist the order request ID for reconciliation). Never ask for values in chat.

Prefer no plaintext credential file. If the user later chooses a local `.env`, it must be untracked, permission-restricted (0600), outside shared/synced storage and loaded explicitly. Existing `.gitignore` excludes exactly `.env`, but other names such as `.env.local` are not guaranteed ignored; verify exclusion before creating anything. An example file would contain empty placeholders only, after implementation approval. Environment variables are not encryption and remain visible to suitably privileged local processes.

Store no credentials in SQLite, logs, reports, command arguments, fixtures or AI context. Redact authentication headers and exception bodies. Test redaction using synthetic sentinel strings, never real secrets. No credentials are needed for planning or offline tests.

## Roadmap and gates

| Phase | Deliverable and dependencies | Required tests / exit criteria |
| --- | --- | --- |
| 0: official API verification | Applied documentation network access; official auth and demo capability matrix; free-access/eligibility confirmation | Every proposed route and credential requirement has an official citation; unresolved isolation blocks execution design |
| 1: approved foundation | Explicit coding approval; Python 3.12 project, typed configuration, locked dependencies and offline CI | Config fails closed; secret redaction; no live mode; reproducible install |
| 2: risk management foundation | Offline Decimal risk rules; transactional SQLite kill switch, daily baseline/halt and reservations | 1% trade risk, 3% daily loss, no leverage; capacity/input checks, duplicate and restart/concurrency tests; execution disabled |
| 3: Demo execution engine | Exact manual authorization, risk integration, broker eligibility, durable journal and asynchronous reconciliation | Mocked opening/closing, timeouts, partial fills, restart recovery and security; execution disabled by default |
| 4: market scanner | Verified market-data discovery/history, indicators, transparent scores, budget/cost screening and caching | Mocked contracts, indicator references, data expiry, quota and safety tests; no execution |
| 5: strategy engine | Deterministic scanner-to-proposal rules, point-in-time evidence, earnings awareness, risk handoff and decision journal | Intraday/swing, look-ahead, affordability, conflict/duplicate, risk integration and exit-advice tests; no execution |
| 6: independent backtesting | Point-in-time replay, unchanged strategy/risk checks, simulated fills, benchmarks and chronological evaluation | Deterministic timing/gap/cost/risk tests; reproducible labelled reports; real-data validation still required |

Candidate dependencies: standard-library sqlite3, decimal, logging and zoneinfo; httpx for transport; pydantic for schemas; pytest and hypothesis for testing. These are proposals, not installed or pinned yet. Add data-science libraries only when justified. No paid AI/API services or cloud database is required. Local-model resource and license needs must be assessed before adoption.

Principal risks: documentation/access restrictions, demo/live route confusion, shared credentials, stale or delayed free quotes, incompatible instrument types, API changes and rate limits, duplicate submissions, partial fills, race conditions, model hallucinations and backtest overfitting. Mitigate respectively through phase gates, transport allowlists, least privilege, freshness rules, verified metadata, contract tests, reconciliation, durable state, serialized execution, deterministic risk boundaries and held-out evaluation. DEMO outcomes do not establish live execution quality.

## Approval boundary

The user authorized Phase 1 plus Demo portfolio and market-rates retrieval. The implementation includes environment configuration, a two-route GET allowlist, timeouts, bounded retries, conservative pacing, sanitized errors, mocked security tests and offline CI. No execution, strategy selection or autonomous trading is implemented. Future phases require separate approval; coding approval never authorizes orders. Real credential access remains untested. The credential-scope declaration is not independent verification of opaque keys: Demo binding must be checked in key management and enforced by eToro.

## Phase 2 implementation

See [RISK_MANAGEMENT.md](RISK_MANAGEMENT.md) for the implemented models, formulas, UTC baseline rules, deterministic decision codes, persistent kill switch and reservation lifecycle. Risk inputs are explicitly supplied; no credential access, broker calls or order execution were added. A PASS reserves local capacity but is not order approval. Read-only API normalization, actual account eligibility, external cash-flow reconciliation, continuous equity monitoring and reservation reconciliation remain prerequisites for future integration. Reservations intentionally have no automatic expiry or release API in this foundation.

## Phase 3 implementation and deployment gates

See [DEMO_EXECUTION.md](DEMO_EXECUTION.md). The coordinator supports only verified Demo opening/closing and status endpoints, with explicit expiring ticket approval, Demo identity evidence, unchanged risk limits and durable single-dispatch journaling. The original read-only client remains unchanged. Autonomous execution is disabled and no actual orders were placed. API credential scope/identity attestation, trusted portfolio normalization, an approval UI, sustained reservation release, safe close recovery without an order ID and account-specific integration are unresolved deployment prerequisites. Phase 3 is verified with mocks, not production account access.

## Phase 4: market scanner implementation

Phase 4 now follows the user's market-scanner scope. See [MARKET_SCANNER.md](MARKET_SCANNER.md) for official source provenance, exact endpoints, typed provider interfaces, completed-bar indicators, transparent scoring, EUR budget/cost screens, async batching, persistent quota/cache state and deterministic tests. No dependencies or trading permissions changed. Network scanning defaults off; autonomous execution remains disabled and no orders were placed.

Remaining integration work: trusted unleveraged-product/currency evidence; exchange calendars and history/volume comparability; fresh FX and account-specific fee/free-access evidence; shared quotas across legacy and scanner clients; downstream strategy stop/size selection and complete portfolio/risk review. Scores never grant risk approval. API portal re-fetch returned 403; the prior official schema was re-inspected and that provenance is recorded. These gaps block unattended broker-backed use, not offline testing. Original later-phase approval/portfolio/reconciliation work remains deferred.


## Phase 5: strategy engine implementation

See [STRATEGY_ENGINE.md](STRATEGY_ENGINE.md). Three deterministic long-only strategies consume scanner features with independently timestamped source bars. They produce immutable, expiring proposals; a separate explicit call performs the unchanged RiskEngine review and capacity reservation. Position monitoring produces advice only. Defaults contain no take-profit cap or daily trade quota. Decision journaling persists rejection/miss/proposal/risk/exit events and duplicate claims across restarts.

No broker endpoints, permissions, credentials or dependencies changed. Remaining gates include independently validated strategy performance, historical point-in-time data and revisions, trusted earnings/calendar/product/quantity-step/FX/cost evidence, position risk monitoring, reservation reconciliation, and human approval integration. Learning may propose reviewed versioned changes; it cannot modify production rules or risk controls automatically. Autonomous execution remains disabled.


## Phase 6: independent backtesting implementation

See [BACKTESTING.md](BACKTESTING.md). Offline chronological replay uses the existing strategies, ExitMonitor and RiskEngine, with new isolated simulation state only. It models EUR 500/1,000 funding, later-quote partial fills, costs, gaps, cash constraints, daily halts and durable duplicate protection. Reports include benchmarks, undefined-metric handling, data/source/configuration digests and provenance. Training-only selection freezes plans before validation/test; walk-forward test windows are disjoint.

No trustworthy historical archive is available or claimed. Bundled inputs are labelled synthetic, including eligibility, liquidity, sessions and earnings evidence. Real-data validation, corporate actions, multi-instrument allocation and independently calibrated fills remain outstanding. Simulation reservation retirement is not a production release API. Existing trading permissions, credential handling, risk limits and disabled autonomous execution remain unchanged.

### Phase 7 — historical evidence foundation

Implemented provider-neutral daily/hourly import contracts, Alpha Vantage raw daily parser,
ECB reference parser, immutable SQLite evidence caching, NYSE 2026 session validation,
quality checks, point-in-time split adjustment and an explicit Phase 6 replay gate.
[Research, observed coverage and limitations](HISTORICAL_DATA.md) distinguish downloaded
observations from verified replay evidence. Local public IBM audit is reproducible; ECB
recorded integration fixture is attributed and licensed for reuse.

**Remaining:** independent real-data validation and strategy/benchmark comparisons are blocked;
no trustworthy full quote/FX/eligibility/earnings/action bundle was obtained. Daily-only data
cannot be substituted into existing hourly strategies. Future daily strategy semantics or a
licensed intraday source require explicit design and tests. Intraday vendor adapter, expanded
calendar coverage, corporate-action portfolio accounting, delisted universe coverage and
historical event vintages remain dependencies. No execution or risk policy changes.

### Phase 8 — hourly qualification; acquisition and real studies blocked

[Provider review](INTRADAY_DATA.md): Yahoo automated-use permission unverified; Alpha Vantage
intraday premium; Stooq access/terms unresolved; Alpaca requires account/feed review and private
authentication; Dukascopy automated collection requires consent and underlying-equity suitability
is unverified. No qualifying 6–12 month hourly stock/ETF archive was obtained.

Implemented offline normalized-hourly cache import, configurable coverage policy, exact session
grid checks, point-in-time warm-up for all three strategies and predeclared chronological windows,
readiness manifests and a coverage gate into the unchanged verified replay path. No remote
provider adapter or real return figures are claimed. Real runs for EUR 500/1,000 remain blocked.

Next dependencies: licensed exports or separately authorized free account integration; feed,
corporate-action and calendar review; then an explicit offline hourly fill/expiry/funding contract
compatible with available observations. Do not manufacture quotes or weaken production risk.
