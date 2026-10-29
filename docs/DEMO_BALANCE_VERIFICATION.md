# Demo balance verification — portfolio-only safety blocker

## Codespaces command

After installing the project with `python -m pip install --no-deps --no-build-isolation -e .` and privately configuring the existing four `ETORO_*` environment variables:

```bash
etoro-demo show-demo-balance
```

**This command currently fails closed by design.** It only uses the existing authenticated GET `/api/v1/trading/info/demo/portfolio`, but official eToro guidance specifies a different read route, GET `/api/v1/trading/info/demo/pnl`, for calculating available USD cash and equity. No authenticated requests were made during development. No new endpoint or execution permission was introduced.

A successful `check-demo` continues to confirm only read access to the Demo portfolio endpoint; it cannot prove account total, currency, or equity. The new command does not display any financial figures, because the available official documentation does not independently establish the required balance response fields for the allowed route. It reports a sanitized error and exits nonzero. No credentials, response bodies, or authentication headers are printed.

## Review blockers

- The P&L response schema, account currency, direct and mirrored positions, and complete pending-order arrays need official contract verification for a future separately reviewed **read-only Demo P&L integration**.
- Do not treat `credit` as equity or total balance. Available cash is a documented calculation from the P&L response; pending-order allocations are not necessarily all account holds.
- `accountCurrencyId=1` is **not** established here as authoritative proof of USD; prior synthetic fixtures were not account attestation.
- Do not pass this observation into the Risk Manager, grant execution permission, or enable autonomous trading.
- `check-demo` behavior and its success message must remain unchanged.

Official references:
- https://api-portal.etoro.com/guides/calculate-available-cash
- https://api-portal.etoro.com/guides/calculate-equity
