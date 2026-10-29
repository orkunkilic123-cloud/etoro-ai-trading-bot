# Offline Demo broker-data diagnostics

This milestone consumes two owner-held public-schema response files plus the **existing** local
risk/execution SQLite journal. It parses supported fields, cross-checks account totals and position
exposure, reports potential reservation overlaps, constructs an incomplete AccountSnapshot and
runs the actual RiskEngine rejection path. It makes no network requests, reads no credentials and
never modifies or recreates safety state. A successful diagnostic means its checks ran; it is not
a successful broker connection or permission to trade.

## Verified schema scope

Public source: https://api-portal.etoro.com/api-reference/openapi.json, retrieved 29 October 2026.
SHA-256: `549e77e8f37dc167dfb6295e4771faf1f9bb71f62d0e925109cd6aa9a5d299a0`.

- `GET /api/v1/trading/info/demo/pnl`: `PortfolioResponseWithPnl` → `ClientPortfolio`.
  Account currency is `accountCurrencyId` (1 = USD). Credit is documented USD. Positions reference
  `TradingRealAdminApi_Position` despite the Demo route: the schema declares `positionID`, `CID`,
  `instrumentID`, `mirrorID`, `settlementTypeID`, and nested `unrealizedPnL` containing `pnL`,
  `exposureInAccountCurrency` and calculation `timestamp`. The schema explicitly maps settlement
  ID 1 to Real Asset (underlying settlement, not live-account mode). Units/exposure must be positive;
  direction long, leverage 1 and no mirrored positions are required by this restricted parser.
- `GET /api/v1/trading/info/demo/aggregate-portfolio`:
  `TradingPortfolioDemoApi_AggregatedPortfolioResponse` declares `cid`, `timestamp`, `accountCurrency`,
  `accountTotals`, `instrumentAggregates`, and `mirrors`. Account totals reference
  `TradingPortfolioDemoApi_AggregatedPortfolioAccountTotals`. The parser takes `accountTotalValue`
  directly, and checks the documented identities `accountBalance = accountAvailableCash +
  accountFrozenCash` and `accountTotalValue = accountAvailableCash + accountTotalUsedMargin +
  accountCurrentPnl`. Used margin is documented as position margins plus frozen opening allocations
  plus mirror margin. The accepted subset excludes mirrors and bonus credit.
- Per-instrument `netCurrentExposureAccountCurrency` from
  `TradingPortfolioDemoApi_AggregatedPortfolioInstrumentAggregate` must exactly equal the sum of
  supported P&L positions' account-currency exposure. Missing, extra or duplicate instruments block.

The previous P&L cash normalizer is reused. Aggregate available cash, balance, P&L and margin must
agree with the independently parsed P&L values. No invented `amount + PnL` equity field is used:
equity is the documented aggregate total, checked against documented equations. Exact Decimal
comparisons are intentionally conservative; no undocumented rounding tolerance is guessed.

**Schema/example discrepancy:** the P&L example uses camel-case `positionId`/`instrumentId`/`cid`
and flatter P&L values, whereas its referenced schema uses the names/nesting above. This parser
follows the schema; conflicting examples fail closed. Only a future authorized owner-operated
read can establish actual response compatibility. No fallback spelling is guessed.

## Supported subset and rejection

Both responses must have the expected full enumerations. Mirrors, bonus credit, close activity,
stockOrders, entryOrders and exitOrders are explicitly unsupported and must be present and empty.
Position IDs and pending order IDs must be unique. One broker customer ID must agree across rows
and the aggregate response. Missing/nullable P&L calculations, non-USD account currency, wrong
settlement/direction/leverage, nonfinite amounts, missing fields, stale/future timestamps or
inconsistent sums block. The observation and all provided calculation times must be aware and
no older than 60 seconds. Input files are limited to 4 MiB each, arrays to 10,000 items; duplicate
JSON keys and binary floating-point monetary inputs are rejected.

An unfiltered full response is required; omission of fields, filters/pagination or unsupported
activities cannot be interpreted as an empty account. The payloads alone cannot prove the actual
request filters, completeness, original receipt time, account/key mode or account ownership.
No `complete=True` construction path is provided. Local labels and supplied observation timestamps
are not independent evidence. AccountSnapshot explicitly remains `demo=False`, `complete=False`,
`cash_flows_reconciled=False`; the actual RiskEngine returns INVALID_ACCOUNT before opening any
write transaction. The broker-reported CID is compared internally but never printed or treated
as a verified binding to the local account ID.

## Existing journal reconciliation boundary

SQLite opens with `mode=ro`, `query_only=ON` and a consistent read transaction. Missing, corrupt or
unsupported state blocks; no initialization/migration/reset occurs. The connection is explicitly
closed for Windows compatibility. The diagnostic validates local account ownership, stored ticket
checksum, proposal/instrument identity, order states and all existing reservation amounts.

Exact broker-order-ID and instrument overlap is reported only as a **potential overlap**. A local
execution ticket lacks an independently established binding to the broker CID, so this is not
enough to release or deduct a duplicated reservation. All local holds remain subtracted in the
internal conservative cash observation; it may double-count. Contradictory terminal/close/mismatched
intent overlap blocks. Unknown/submitted and other unfinished orders are prominently counted.
No reservation, duplicate tombstone, kill flag or daily-loss latch is changed. Correct authoritative
handoff without double-counting remains blocked on verified identity and lifecycle linkage.

## Owner-operated read-only command (Windows PowerShell)

Use only existing privately retained, fresh response files from a separately authorized owner read.
Do not send account data, credentials or files to chat. This command performs **no download**:

```powershell
python -m etoro_demo_bot.broker_diagnostics --pnl-file C:\Private\demo-pnl.json --aggregate-file C:\Private\demo-aggregate.json --risk-state C:\Private\existing-risk.sqlite --observed-at 'ACTUAL_ISO8601_OBSERVATION_TIME_WITH_OFFSET'
```

Replace the timestamp locally with the actual observation time; never re-date an old file to pass
freshness. Retain raw JSON number tokens; the command decodes them as Decimal. The existing safety
DB must already include the execution journal. Do not create or clear a production DB to make this
command pass. If no such reviewed state exists, LOCAL_SAFETY_STATE_UNAVAILABLE is the correct result.

Output contains fixed codes, position/overlap/unresolved counts and kill/daily-baseline/halt status.
It never prints customer/account IDs, amounts, positions, payloads, paths, headers or exceptions.
Exit 0 means the diagnostic completed with trading still blocked; exit 1 means invalid/unavailable
input or state. An empty pending list is not proof of no unknown submissions.

Offline software verification with synthetic inputs:

```powershell
python -m pytest -q tests/test_broker_diagnostics.py
python -m etoro_demo_bot.broker_diagnostics --help
```

Tests exercise public-schema parsing → aggregate consistency → read-only local reservations →
AccountSnapshot → actual RiskEngine, and prove byte-identical safety DB contents before/after.
They cover unknown submissions, duplicate IDs, stale/nullable data, unsupported currency/assets,
wrong customers, conflicting overlaps, corrupt/missing state and sanitized errors. They establish
software behavior only. Windows and authenticated compatibility remain unverified unless separately
recorded by an actual run.
