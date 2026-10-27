# Windows PowerShell setup (Python 3.12+)

Use a free Python installation from python.org and run these commands from the repository root. No paid service is required. This client has no order API or autonomous trading loop.

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
