# eToro Demo trading foundations

Python 3.12+ read-only API client, risk engine and opt-in Demo execution coordinator. The read-only client allows only Demo portfolio GET and market rates GET. The original client blocks order routes and Real portfolio routes. A separate, disabled-by-default Demo execution coordinator requires exact manual approval and risk checks; no autonomous trading is implemented.

- [Strategy engine: proposals, risk review, exit advice and learning boundary](docs/STRATEGY_ENGINE.md)
- [Market scanner: data contracts, indicators, scores and limitations](docs/MARKET_SCANNER.md)
- [Demo execution: authorization, journal and recovery](docs/DEMO_EXECUTION.md)
- [Risk management: policy, persistence and offline example](docs/RISK_MANAGEMENT.md)
- [Windows setup and read-only connection test](docs/WINDOWS_SETUP.md)
- [Architecture and roadmap](docs/IMPLEMENTATION_PLAN.md)
- [Verified API findings](docs/API_FINDINGS.md)
- [Permanent rules](AGENTS.md)

Linux/macOS development:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
```

Tests are offline. The explicit `etoro-demo check-demo` command requires locally configured Demo credentials; see the guide. An opaque key's scope cannot be verified locally: Demo declaration plus broker-side enforcement and immutable read-only routing are the safety boundaries. Never enable diagnostic tooling that prints secrets or frame locals.

The offline risk engine limits estimated risk to 1% per trade, latches a daily halt at 3% equity loss, forbids leverage and reserves capacity in SQLite. It rejects invalid/stale inputs and duplicates, and persists an emergency kill switch across restarts. A risk PASS never authorizes execution. See the risk guide for UTC baseline requirements and conservative reservation lifecycle limitations.

Phase 4 adds an analysis-only market scanner with batched official data routes, completed-bar indicators, explainable opportunity scores, EUR budget/cost screening and persistent caches/quota pacing. Network access defaults off; verified product, calendar, FX and cost evidence are required. Scores never approve orders. Run `python -m pytest tests/test_scanner.py` for the offline scanner suite.

Phase 5 adds deterministic momentum breakout, trend-following and mean-reversion proposals for intraday/short-swing analysis. Point-in-time evidence, earnings coverage, conservative sizing and persistent decision journaling are required. Risk review is explicit; strategy code cannot invoke execution. No profitability claim or autonomous trading is enabled.
