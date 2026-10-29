# Owner-operated read-only Demo P&L cash check

## Codespaces

Install the existing project and use your privately configured environment variables
`ETORO_API_KEY`, `ETORO_USER_KEY`, `ETORO_ENVIRONMENT=demo`
and `ETORO_DEMO_KEY_CONFIRMED=true`:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
etoro-demo show-demo-balance
```

The command reads **only** `GET https://public-api.etoro.com/api/v1/trading/info/demo/pnl`.
Existing `check-demo` continues to read the original Demo portfolio GET. Both use the
same credentials policy, bounded retries and strict exact-route allowlist; all order
methods, Real paths and arbitrary query parameters are rejected. No authenticated reads
or order requests were made in development.

## Source-backed formulas (USD cash values only)

According to the official eToro available-cash guide:

- Manual reserved funds = sum of `ordersForOpen[].amount` for `mirrorID == 0`.
- MIT-order reserved funds = sum of every `orders[].amount`.
- Available cash = `credit - manual reserved funds - MIT-order reserved funds`.

All necessary lists and numeric values must be present, finite and nonnegative.
Mirrored opening orders are deliberately excluded, as the official formula prescribes.
No balance is printed if any required cash field is missing or invalid.

`credit` is printed **as credit only**, never as total account balance. Available
cash is a calculation, not equity. Official equity is available cash plus total
invested and unrealized P&L, requiring a more comprehensive validated response
(including mirror exposures and P&L). This command deliberately marks equity,
total account balance and open positions as unavailable instead of guessing.

The eToro guides explicitly scope the cash and equity formulas to USD. Therefore
the label USD refers to the **documented cash formula denomination**, not a
verified personal account base currency. This result is an untrusted observation,
not account identity attestation or permission to trade, and is never passed to
the Risk Manager as a trusted snapshot.

## Remaining limitations

The exact live owner response and account-scoped entitlements have not been
checked (no credentials or authenticated requests permitted). P&L account currency,
total balance and reliable complete position count remain unverified. Pending-order
allocations need not capture every fee or external hold. `credit` should not be
conflated with equity or freely spendable capital. When source contracts are
incomplete, the read fails closed; sanitized errors never reveal response data.

Official sources:

- https://api-portal.etoro.com/guides/calculate-available-cash
- https://api-portal.etoro.com/guides/calculate-equity


## Privacy-safe diagnostic (PR #30)

Run `etoro-demo show-demo-balance` in the owner's Codespaces session. Only a
fixed error category is printed; never paste keys, raw JSON or request headers.

- `authorization`: HTTP 401/403; key invalid, missing entitlement or access denied (not enough evidence to distinguish them).
- `unsupported-endpoint`: HTTP 404, endpoint missing or inaccessible.
- `rate-limit`: HTTP 429 after bounded read-only retries.
- `server`: HTTP 5xx after bounded retries where applicable.
- `network`: transport/connection failure.
- `timeout`: read or connection timeout.
- `invalid-response`: HTTP 200 with invalid or non-object JSON.
- `incomplete-or-incompatible-data`: HTTP 200 object lacks fields needed for documented cash computation.
- `unexpected-http`: another unexpected HTTP response.
- `local configuration`: may be grouped with incompatible-data for credential declaration failures; no credential values are exposed.

No diagnostics access Real endpoints or submit orders. No full local validation
claim should be made until the complete repository is tested in a suitable runtime.
