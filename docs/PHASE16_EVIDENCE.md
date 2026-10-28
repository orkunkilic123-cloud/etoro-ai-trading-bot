# Phase 16 — genuine 5Min qualification boundary

This release adds an **offline multi-symbol evidence audit**, not a claim of real backtest
readiness. The sole external Trader Skill reference remains
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
at the existing pinned revision. None of its downloader, broker or order code is copied.

## Verified provider contract and limits (28 October 2026)

Alpaca's [stock-bars reference](https://docs.alpaca.markets/us/reference/stockbars)
accepts `5Min`, `feed=iex`, up to 10,000 rows per page and continuation
via `next_page_token`. Results can be grouped by symbol, not interleaved by time.
[Basic pricing](https://docs.alpaca.markets/us/docs/about-market-data-api)
lists free IEX coverage, US stocks and ETFs, 200 historical requests/minute and
a recent-15-minute restriction. These service descriptions **do not verify** the
owner's account access, per-symbol completeness or market-data reuse permission.
Venue-specific IEX volume is neither consolidated US volume nor a historical eToro quote.

## Safe first read and multiple symbols

Authenticated acquisition stays in the existing Alpaca **data-only** client.
It is disabled unless the owner supplies the explicit network and five-minute flags;
no credentials are accessed in repository development or offline audit.
The repository's allowlist permits only the existing HTTPS GET historical stock-bars route.
No trading/account endpoint or paid feed is added.

For the first owner-authorized local data read, review your Basic terms and execute
the documented command in [Phase 15](ALPACA_5MIN_IMPORT.md), beginning with **one GET**.
The initial budget intentionally blocks incomplete pagination. Increase the budget only
after reviewing response and quota limits. For multi-symbol acquisition, use the existing
`--symbols IBM SPY` query and remember that a page may contain only IBM.
Each invocation must have a deliberate `--request-limit`; for 5Min the owner CLI
limits it to 30. Keep actual responses in the private SQLite archive, outside Git.
The current evidence validator also supports selecting individual symbols from
a complete multi-symbol download manifest.

Do not automate repeated authentication or infer raw data licensing, original
publication or correction times from a later retrieval date.

## Reproducible offline audit

Existing `history.intraday.qualify_download` checks raw 5Min session grids,
the reviewed NYSE 2026 calendar, DST, holiday/half-day boundaries, missing/duplicate
bars, and native checksums. No synthetic replacement or volume interpolation is allowed.
Other years remain unsupported until reviewed. Run from an existing private archive:

```powershell
python -m etoro_demo_bot.history.phase16_audit --cache .historical-data/alpaca.sqlite --item IBM MANIFEST_ID_IBM --item SPY MANIFEST_ID_SPY --start 2026-03-09 --end 2026-03-09 --audit-at 2026-10-28T16:00:00+00:00 --calendar-verified-at 2026-10-28T15:00:00+00:00 --output .historical-data/phase16-evidence
```

Replace IDs and review times with real evidence. If both symbols came from the
same complete multi-symbol manifest, supply the same ID twice. The cache opens
read-only; report output must not exist. Output contains `evidence.json`,
`evidence.csv`, `evidence.md` and `sha256.json`, encoded UTF-8 with LF.
Detailed private archive data must never be committed or shared without permission.

Each symbol is assessed separately. A structurally complete full-session dataset
can have `structural_coverage=qualified`, but **replay status remains blocked**.
Every symbol's report names missing original publication/revisions, usable rights,
corporate actions and split basis, historical bid/ask/liquidity, realistic costs,
point-in-time USD/EUR FX, eToro product eligibility and earnings evidence.
A hash proves stored bytes' integrity, not vendor originality.
No original first-known timestamp is invented or backdated.

## Backtest, Monte Carlo and comparators

The current Phase 14 `IntradayBacktest.Dataset.validate()` rejects later
retrieval timestamps and missing historical execution evidence. No attempt is made
to replace that gate with candle-close timestamps. The new report explicitly sets
all genuine ORB, EUR 500/1,000, 10,000-draw Monte Carlo, cash and buy-and-hold
results to null. A comparison requires defensible historical quote/FX, eligibility,
cost and temporal inputs on the same basis and validated selection/holdout dates.
The existing synthetic benchmark remains separate and cannot validate profitability.

### Minimum remaining owner actions

1. Review Basic IEX account access, retention and personal/research use rights.
2. Authorize one bounded read-only capture locally, with private storage and real
   timestamps. Do not provide keys in chat.
3. Supply the private SQLite archive or run offline audit on the owner's computer.
4. Obtain independent point-in-time availability/revision, corporate action,
   quote, fee, FX, earnings and eligibility evidence before genuine ORB replay.

Recommended Phase 17: independently reviewed market-data vintage/quote/FX/action
evidence adapters and no-look-ahead tests, followed by a **separately authorized**
conditional research comparison only if the existing gates admit it.
No Demo/Real execution or leverage is authorized.
