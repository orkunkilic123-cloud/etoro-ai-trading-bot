# Autonomous cloud readiness audit (2026-10-30)

## Verified in repository
- `AGENTS.md` restricts the project to eToro DEMO and requires exact order approval. Autonomous order execution is forbidden by current policy.
- `src/etoro_demo_bot/alpaca/__init__.py` declares read-only Alpaca market data; no account/order transport.
- `docs/ORB_RESEARCH.md` implements proposal-only 15-minute ORB. It explicitly does not authorize orders or implement automatic exits.
- `docs/DEMO_EXECUTION.md` describes opt-in manual eToro demo coordinator, not autonomous Alpaca trading.

## Critical distinction
The owner reports a successful Alpaca OCO trade in a separate workflow. This does **not** establish that the GitHub repository contains the code or credentials for that workflow. Do not infer execution readiness from that trade.

## Remaining engineering tasks, in dependency order
1. Confirm whether autonomous **Alpaca PAPER** trading should be a separate application/module and update the project policy with narrowly scoped, reviewed paper-only permission. Preserve the prohibition on live trading.
2. Define Alpaca paper broker adapter with explicit host allowlist, account verification, read-only reconciliation, typed orders/fills and client-generated idempotency IDs. Mock network in tests.
3. Persist broker state and decisions in SQLite with transactional claims, crash recovery and uncertain-submit reconciliation. No blind resubmission.
4. Create NYSE-aware session loop, with DST/holidays/early-close handling and complete-bar freshness checks. Existing reviewed calendar only covers 2026; later dates require updates.
5. Implement risk-checked paper entry, protective broker order verification, partial-fill handling and deterministic end-of-day flattening. Halt entries on any mismatch; alert on unconfirmed close.
6. Implement daily reports, heartbeat and operator alerting. Ensure no sensitive values in logs.
7. Run offline unit/integration/fault tests, then multi-session Alpaca PAPER validation before enabling any unattended scheduling.
8. Install and harden VPS only after provisioning, then start disabled service in observe-only mode. Explicitly verify PAPER identity before any paper orders.

## Current branch status
- Deployment templates and a fail-closed *offline* safety assessor added.
- Unit tests added but **not executed** in this environment.
- No VPS ordered; no scheduler enabled; no credentials accessed; no broker orders placed.
- No autonomous execution implementation is ready.

## Review gate
The existing `AGENTS.md` says documentation-only until implementation approval and exact DEMO order approval. User authorized preparation and building for future autonomous paper trading, but this does not authorize rewriting permanent restrictions silently or placing any order. Keep execution disabled and request a deliberate policy review before integrating a new Alpaca paper execution path.
