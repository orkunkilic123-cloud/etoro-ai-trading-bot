# Alpaca Network Secrets in Codex Cloud

This workflow supports **read-only historical IEX bars**. It enables no orders or eToro
execution. The implementation was validated with synthetic placeholders and mocked HTTP
transport, not actual credentials or authenticated requests. Account access, proxy substitution
and historical coverage remain unverified end to end.

## Secure configuration

1. Open the Codex environment settings for this repository. Under **Network Secrets**, add
   the following bindings. Enter values only in the secure settings interface, never in chat,
   scripts, shell command literals or repository files.

   | Suggested secret name | Target environment variable | Allowed HTTPS destination |
   | --- | --- | --- |
   | ALPACA_DATA_API_KEY | ALPACA_DATA_API_KEY | data.alpaca.markets |
   | ALPACA_DATA_API_SECRET | ALPACA_DATA_API_SECRET | data.alpaca.markets |

   Each destination is a hostname, without scheme, port, path or wildcard. If an existing
   secret is named ALPACA_API_KEY or ALPACA_SECRET_KEY, its **target variable** must still
   match the table: the application does not read those alternate names.

2. Set the ordinary non-secret variable **ALPACA_DATA_CODEX_PROXY_REQUIRED=true**.
   Keep **ALPACA_DATA_FREE_ACCESS_CONFIRMED=false** until you have reviewed Basic IEX
   access and applicable account/exchange data terms. Only then set that confirmation to
   exactly **true**. This records your assertion; it does not verify account entitlements.
3. Permit data.alpaca.markets for this integration. Do not add trading hosts or wildcards.
   Preserve unrelated repository setup destinations when editing network policy. Proxy secret
   bindings must remain scoped to the single data host even if other network hosts are allowed.
4. Save settings and publish when the environment workflow requires it. Configuration saving
   is not proof that an existing runtime has updated. Check current environment-status metadata
   for observations_current=true, enforced network policy and each binding's ready status.
   Do not print the environment, placeholder values or secret contents.
5. Preserve platform-provided HTTPS_PROXY and CA settings. Do not copy or change the policy
   file, override the proxy, use NO_PROXY as a workaround, or disable certificate verification.
6. Offline checks require no credentials:
   ```bash
   python -m etoro_demo_bot.alpaca --help
   python -m pytest -q tests/test_alpaca_cloud.py tests/test_alpaca_data.py
   ```
   Do not run a download yet. A future, separately authorized read requires --enable-network
   as well as the free-access confirmation. See WINDOWS_SETUP.md for query syntax, not for
   entering cloud credentials. No actual credential values were used in these checks.

Network Secrets supply placeholders to the process; the managed proxy substitutes the values
on the authorized HTTPS destination. They are not a raw-secret file or process injection
mechanism. No alternate raw-secret mechanism is necessary for this header-based API.

## Transport contract

The production client detects /etc/codex/network-policy.json. Cloud mode is also mandatory
when ALPACA_DATA_CODEX_PROXY_REQUIRED=true, so a missing policy cannot silently become a
direct connection. Unknown flag values, unsupported/malformed policy, missing HTTPS_PROXY,
or a proxy differing from the policy's http_proxy fail closed with a fixed sanitized error.

The approved proxy is passed explicitly to HTTPX. Generic environment inheritance stays off:
NO_PROXY, ALL_PROXY and alternate proxies cannot redirect or bypass this connection. The
HTTPX pool never falls back to a direct connection after proxy failure. Proxy URLs with
userinfo, query, fragment or non-root path are rejected.

SSL_CERT_FILE and SSL_CERT_DIR select the provided trust configuration using Python's
ssl.create_default_context. Without them, the platform's default trust store is used.
Hostname checking and CERT_REQUIRED remain enabled. Invalid CA files fail before a request;
directory-based CA lookup can fail at the TLS handshake. There is no insecure retry.

The application still constructs only GET https://data.alpaca.markets/v2/stocks/bars,
with feed=iex. Authentication is in headers, never URLs. Redirects are not followed.
Cloud and local paths preserve the original opt-in, quota, retry, provenance and secret-error
guards. Explicit injected transports are an offline testing seam and bypass proxy discovery;
the CLI does not expose transport injection.

## Security boundaries and remaining limitations

- The environment administrator and managed proxy are trusted. The proxy necessarily handles
  actual credentials. Correct domain binding is essential; application code cannot verify the
  platform's secret configuration or guarantee its substitution from a placeholder string.
- The policy is a startup snapshot, not live authorization. The sidecar enforces current policy.
- Credentials may have wider brokerage powers; this client does not change their scope.
  Python code, environment configuration and arbitrary custom transports are not a sandbox
  against malicious code with access to the process.
- Keep the mandatory proxy flag true in cloud settings. A machine with neither the policy file
  nor this flag is treated as local; local mode intentionally supports direct verified HTTPS.
- HTTP/network debug logging must stay off. The application does not log headers or upstream
  exception objects. Proxy/operator logs have their own platform controls.
- No end-to-end secret substitution, authenticated availability or historical coverage claim
  is made. No paid subscription is configured. All prior historical-data limitations remain.

Platform contracts consulted: Cloud Environment Runtime's networking.md and Cloud Environment
Onboarding's onboarding.md, available through the installed Codex Cloud plugins. These document
the sidecar proxy, destination-bound placeholder substitution, runtime readiness and publication.


## Offline query preparation

Use the query preview before configuring credentials or enabling downloads:

```bash
python -m etoro_demo_bot.alpaca --dry-run --symbols IBM --start 2026-03-01T00:00:00Z --end 2026-03-02T00:00:00Z
```

This validates the query and prints the fixed GET destination and normalized parameters.
It does not load credentials, construct a client, inspect proxy settings, create a cache,
or send requests. `--dry-run` and `--enable-network` are mutually exclusive. Invalid
queries fail with the same sanitized CLI error as downloads. A successful preview does
not verify account entitlements, free access, completed historical hours, coverage or
replay readiness; those checks still apply to an explicitly enabled future download.

The historical bars contract was reviewed on 2026-10-28 against the official reference:
https://docs.alpaca.markets/us/reference/stockbars . The existing route, hourly timeframe,
inclusive bounds, IEX feed and pagination parameters remain applicable.
