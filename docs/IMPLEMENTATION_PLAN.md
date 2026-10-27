# eToro DEMO bot: findings and proposed implementation

Status: Phase 1 foundation and the two explicitly requested read-only adapters implemented by user authorization. No orders or authenticated broker requests have been made during implementation. See WINDOWS_SETUP.md for setup and limitations.

## Evidence and limitations

The repository contains README.md and a Python-oriented .gitignore, but no application, dependencies, tests or CI. Python 3.12 and Git are available. GitHub read access was verified previously and the checkout was clean before documentation work.

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
| 2: read-only adapter | Phase 0 schemas; user-configured credentials only for later integration | Mock success/error/pagination/rate-limit cases; verify demo identity, cash and positions with read-only integration; no mutation requests |
| 3: analysis and proposals | Validated data sources, normalized instruments and portfolio | Missing/stale data rejection; deterministic proposals; backtests with costs, slippage, no lookahead and held-out evaluation |
| 4: risk and approvals | Versioned limits, portfolio reconciliation and durable state | Boundary/property tests for cash, exposure and Decimal sizing; reject leverage/shorts; changed, expired, replayed or wrong-account approvals fail |
| 5: demo execution | Separately approved implementation; documented demo mutations and ambiguity handling | Fake-transport tests for real-path rejection, redirects, concurrency, crash recovery and partial fills; any actual DEMO order requires its own explicit authorization |
| 6: supervised demo operation | Previous gates passed; operational limits and documented recovery | Sustained observation, reconciliation drift checks, kill-switch drills and restart tests; measured behavior before expanding scope |

Candidate dependencies: standard-library sqlite3, decimal, logging and zoneinfo; httpx for transport; pydantic for schemas; pytest and hypothesis for testing. These are proposals, not installed or pinned yet. Add data-science libraries only when justified. No paid AI/API services or cloud database is required. Local-model resource and license needs must be assessed before adoption.

Principal risks: documentation/access restrictions, demo/live route confusion, shared credentials, stale or delayed free quotes, incompatible instrument types, API changes and rate limits, duplicate submissions, partial fills, race conditions, model hallucinations and backtest overfitting. Mitigate respectively through phase gates, transport allowlists, least privilege, freshness rules, verified metadata, contract tests, reconciliation, durable state, serialized execution, deterministic risk boundaries and held-out evaluation. DEMO outcomes do not establish live execution quality.

## Approval boundary

The user authorized Phase 1 plus Demo portfolio and market-rates retrieval. The implementation includes environment configuration, a two-route GET allowlist, timeouts, bounded retries, conservative pacing, sanitized errors, mocked security tests and offline CI. No execution, strategy selection or autonomous trading is implemented. Future phases require separate approval; coding approval never authorizes orders. Real credential access remains untested. The credential-scope declaration is not independent verification of opaque keys: Demo binding must be checked in key management and enforced by eToro.
