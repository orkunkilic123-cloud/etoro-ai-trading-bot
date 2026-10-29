# Owner-operated read-only Demo cash inspection

From GitHub Codespaces after installing the project with `python -m pip install --no-deps --no-build-isolation -e .`, run:

```bash
etoro-demo show-demo-balance
```

The CLI uses existing `ETORO_API_KEY`, `ETORO_USER_KEY`, `ETORO_ENVIRONMENT=demo` and `ETORO_DEMO_KEY_CONFIRMED=true` declarations. Configure these privately outside the source tree, never via printed terminal examples or committed files. Neither this implementation nor its tests makes authenticated broker calls. Do not upload the output or log secrets.

Only the previously allowlisted `GET /api/v1/trading/info/demo/portfolio` is used. `clientPortfolio.credit` is displayed as **portfolio credit**, never total balance or equity. The cash calculation subtracts documented manual `ordersForOpen` and `orders` reservations. It requires `accountCurrencyId=1` (USD), credit, both pending-order lists, and position/mirror collections. Unknown/missing fields fail closed. Open-position count covers only direct positions; any copy-trading mirrors prevent complete position claims. This CLI does not trust the snapshot for the Risk Manager.

## Known limitations

- Official eToro cash documentation explicitly recommends the **Demo P&L** endpoint for the cash formula. The current allowlisted portfolio endpoint may not return all required fields, particularly `accountCurrencyId`. In that case this command intentionally returns unavailable rather than guessing. No new route was enabled.
- The existence and semantics of total account balance and equity cannot be proven from the portfolio credit field; both intentionally display unavailable.
- The listed reserved cash describes documented pending-order allocations, not all potential holds/fees.
- One successfully authenticated GET does not independently prove broker-side Demo key scope. Existing owner key assertions and Demo-only route safety still apply.
- The current official response schema and actual owner account response should be independently checked without sharing raw data before claiming production-grade compatibility.
- Never use this observation to bypass risk checks, activate execution, or place orders.

Source: https://api-portal.etoro.com/guides/calculate-available-cash and https://api-portal.etoro.com/guides/calculate-equity
