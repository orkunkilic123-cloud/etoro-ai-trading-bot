# Windows PowerShell setup (Python 3.12+)

Use a free Python installation from python.org and run these commands from the repository root. No paid service is required. The CLI is read-only; the separate execution coordinator remains disabled by default. There is no autonomous trading loop.

## Install and verify offline

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

Activation is optional; no PowerShell execution-policy changes are needed. The lock includes Windows-specific dependencies and the build backend. Tests use mocked HTTP only and require no keys.

## Configure a Demo key securely in this local session

First confirm in eToro Settings → Trading → API Key Management that the user key is bound to **Demo** and has **Read** permission. Do not use a Real key. Scope cannot be decoded from the opaque credential locally; the confirmation below is a user declaration, not cryptographic proof. eToro enforces key scope on the Demo portfolio request. Never probe a Real endpoint.

The application reads environment variables only. `.env.example` documents names; `.env` files are not loaded automatically. Do not paste secrets into command lines, chat, scripts, logs or committed files. In your own PowerShell terminal, masked input keeps values out of command history:

```powershell
function Set-SessionSecret([string]$Name) {
    $secureValue = Read-Host "Enter $Name locally" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        [Environment]::SetEnvironmentVariable(
            $Name, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer), 'Process'
        )
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $secureValue.Dispose()
    }
}
Set-SessionSecret 'ETORO_API_KEY'
Set-SessionSecret 'ETORO_USER_KEY'
$env:ETORO_ENVIRONMENT = 'demo'
# Set only after checking Demo binding in eToro's key-management screen.
$env:ETORO_DEMO_KEY_CONFIRMED = 'true'
```

Environment variables reside in process memory and are inherited by children; they are not encrypted storage. Close the session or clear them when finished. Do not enable HTTP wire logging or traceback tools that dump local variables. TLS verification is enabled; corporate proxies must supply a trusted CA rather than disabling verification.

## Explicit read-only connection test

```powershell
.\.venv\Scripts\etoro-demo.exe check-demo
```

This sends only `GET https://public-api.etoro.com/api/v1/trading/info/demo/portfolio`. Success prints a status message, not portfolio contents or credentials. A 401/403 may mean wrong scope, invalid/expired credentials, missing permission or account restrictions; inspect non-secret key metadata locally. There is no Real fallback. No order authorization is involved because this command cannot place orders.

```powershell
Remove-Item Env:ETORO_API_KEY, Env:ETORO_USER_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ETORO_DEMO_KEY_CONFIRMED -ErrorAction SilentlyContinue
Remove-Item Function:Set-SessionSecret
```

## Limits of this foundation

Only the Demo portfolio and shared market rates GET routes are supported. Rates accept 1–1000 positive instrument IDs and preserve HTTP 206 as `partial=True`; quote delay and missing data must be handled by future analysis. Responses are JSON objects with otherwise unnormalized vendor fields; success does not prove trading readiness.

The client serializes requests and conservatively paces both endpoints together at one request/second, including retries. Use one client/process per key: separate processes or other applications share the server quota but not this local limiter. Server cooldowns are honored; waits over five minutes abort rather than retry early. Safe reads retry at most twice for transport errors, 429, 502, 503 and 504; auth failures and redirects never retry. Account access and Windows installation still require validation on your machine.

## Phase 3 offline execution-engine verification

The separate Demo execution coordinator is disabled by default and is not connected to this CLI. It has no credential-loading or autonomous execution command. Validate it using mocked tests only:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_execution.py
```

See [DEMO_EXECUTION.md](DEMO_EXECUTION.md) for authorization, SQLite migration, risk integration, recovery and deployment limitations. Real account use requires a trusted Demo identity attestation provider and exact human order approval; neither is supplied by an environment-mode flag. Do not initialize or delete production safety state to clear a halt or duplicate reservation. Existing `check-demo` remains a read-only portfolio request.


## Phase 4 offline market-scanner verification

No credentials, paid services or additional dependencies are needed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scanner.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m hatchling build
```

The tests use synthetic keys, mocked HTTP, simulated time and temporary SQLite files. Do not configure real keys for these tests. No scanner/execution command is added to the CLI. The existing `check-demo` command is unrelated to scanner validation and is unnecessary here.

For future approved read-only integration, compose `Scanner` with the explicit providers described in [MARKET_SCANNER.md](MARKET_SCANNER.md). `MarketClient` defaults to network disabled. Choose a small explicit watchlist, a scan interval (default 300 seconds), verified EUR/USD conversion and conservative fees. Unknown product leverage, currency, session or history coverage blocks ranking. This release supplies no live evidence provider, so do not fabricate those attestations to get a signal.

If initializing a local analysis store later, create `.scanner-state` explicitly and keep its SQLite files separate from `.risk-state`. All scanner instances sharing a key must share the quota store. Do not run the older clients concurrently on that key without common quota coordination, or delete state to bypass cooldowns. Closing a window or restarting does not authorize orders. Automated scoring never changes the disabled execution default.


## Phase 5 offline strategy-engine verification

Use the existing environment and pinned dependencies. No keys or broker connection are needed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_strategy.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m hatchling build
```

Tests initialize only temporary synthetic journals/accounts and run no authenticated API calls. There is no strategy execution command. See [STRATEGY_ENGINE.md](STRATEGY_ENGINE.md) for library composition and required evidence. Create `.strategy-state` explicitly for a future local analysis journal, separately from `.risk-state`; never reset safety state to clear a duplicate or halt. `Journal.initialize` refuses to overwrite existing files.

Proposal generation is offline and reserves no capacity. Explicit RiskEngine review does reserve local capacity; do not use a real safety database for experiments. Exit results and stop/target levels are advice, never broker instructions. A fresh, verified earnings calendar and product/quantity-step/FX/cost evidence are required; do not substitute invented facts. Rules are immutable versions; Learning Agent suggestions require review before any promotion. Autonomous execution remains disabled.


## Phase 6 offline backtesting and synthetic reports

No credentials, market download or new dependencies are needed. These commands run synthetic engineering fixtures only:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m hatchling build
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest --synthetic --eur 500 --output .backtest-output\synthetic-500
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest --synthetic --eur 1000 --output .backtest-output\synthetic-1000
```

Output directories must be new; reruns deliberately refuse to overwrite evidence or safety state. Open `comparison.md` and each strategy's `report.md` locally. JSON, CSV, checksums, complete input archives and isolated simulation journals are also saved. All results are prominently synthetic; do not present them as historical returns or evidence of profitability. No order execution occurs.

See [BACKTESTING.md](BACKTESTING.md) for library input contracts, chronological splits, metrics and data limitations. Keep replay output separate from `.risk-state` and `.strategy-state`; never point experiments at production state. There is no real-data downloader or credential configuration step. Supply independently reviewed historical evidence through the typed Dataset interface before conducting a real-data study.
