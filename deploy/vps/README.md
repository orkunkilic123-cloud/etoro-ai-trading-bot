# VPS deployment preparation — PAPER ONLY

This branch is preparation, not an active trading service. It does not place orders, schedule trades, or modify broker settings.

## Prerequisites
- Ubuntu 24.04 VPS, Python 3.12+, non-root deployment user, SSH keys.
- Firewall: SSH restricted to trusted IPs; no public application ports required.
- Clone this branch under /opt/trading-bot; install dependencies in a dedicated virtual environment.
- Keep credentials in a root-owned environment file outside the Git checkout; never commit keys or print environment values.
- Use Alpaca PAPER credentials only. Verify account endpoint and broker-side paper environment before enabling any network activity.

## Safety gates before any autonomous trading
1. Audit the actual Alpaca order implementation and its paper-only endpoint enforcement. The current README documents research-only and opt-in manual demo execution; autonomous trading must not be assumed.
2. Persist trading-day state, order IDs, client order IDs, fills and risk reservations in durable storage; recover and reconcile against broker state before placing orders.
3. Implement an exchange-calendar-aware scheduler in America/New_York. Never assume 15:30 Amsterdam is always the open.
4. Implement one-entry-per-signal idempotency, stale-data rejection, hard 1% per-trade and 3% daily-loss limits, no leverage, and a persistent kill switch.
5. Use broker-side protective orders when supported; test partial fills, OCO lifecycle, rejected orders, disconnects, delayed quotes, and VPS restarts.
6. Implement flatten-before-close using actual NYSE calendar; reconcile cancellation/fill races. If reconciliation fails, halt entries and alert; do not claim positions are flat.
7. Monitor health, heartbeat, disk space, clock sync, and failed executions; send alerts without credentials or sensitive logs.
8. Replay and paper-test several sessions and failure scenarios before any consideration of live trading.

## Deployment sequence
1. Provision VPS only after owner is available; enable automatic security updates, SSH hardening and backup.
2. Review repository execution paths and write a separate PAPER-only runner, disabled by default.
3. Add systemd service with Restart=on-failure, restrictive permissions and explicit PAPER_ONLY=1; use a NYSE-aware scheduler inside the process, not fixed local cron.
4. Validate no order path can reach live trading; run offline tests and controlled paper tests.
5. Enable paper scheduling only after owner reviews evidence and risk settings.

No existing positions or OCO orders were touched by this preparation.
