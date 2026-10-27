# eToro Demo API and risk foundation

Python 3.12+ read-only client. Exact allowlist: Demo portfolio GET and market rates GET. All order routes and Real portfolio routes are blocked; no autonomous trading is implemented.

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
