# eToro Demo API foundation

Python 3.12+ read-only client. Exact allowlist: Demo portfolio GET and market rates GET. All order routes and Real portfolio routes are blocked; no autonomous trading is implemented.

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
