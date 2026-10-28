# Phase 15 — owner-operated Alpaca 5Min evidence intake (initial implementation)

**Status: offline intake implemented; authenticated 5Min download and genuine ORB replay remain blocked.**

The existing Alpaca client intentionally refuses authenticated 5Min requests. Do not bypass
that guard with a modified client or submit credentials to ChatGPT. This phase adds an
offline importer for original pages already lawfully acquired by the owner, using the
existing immutable SQLite Archive, strict native 5Min parser, pagination-chain verifier
and `archive_research_pages`. No data are included in the repository.

## Official provider context (checked 2026-10-28)

- [Historical stock bars](https://docs.alpaca.markets/us/reference/stockbars):
  `GET https://data.alpaca.markets/v2/stocks/bars`, `timeframe=5Min`,
  `feed=iex`, paginated with `next_page_token`. Multi-symbol pages
  are sorted by symbol then timestamp.
- [Basic plan](https://docs.alpaca.markets/us/docs/about-market-data-api):
  free IEX venue data, historical stocks since 2016, 200 historical requests/min,
  with the latest 15-minute historical restriction. These documented offerings are
  not a verification of an individual account, specific IBM coverage or data rights.
- IEX does not represent all US exchanges. Rights/retention and private internal use
  must be checked against current account agreements; **no data redistribution**.
  Do not assume archival rights merely from successful authentication.

## Offline import

Privately capture the **original HTTP JSON entity bodies**, not screenshots or
reformatted JSON. Preserve actual retrieval timestamp (UTC), request parameters,
actual per-page `page_token` values and response provenance in a private log.
Only exact stock-bars GET with the listed IEX/raw/5Min options is compatible.
Never copy tokens, credentials, headers or private response bodies into this repository.

For a single-page historical capture after 2026-03-09:

```powershell
python -m etoro_demo_bot.history.alpaca_5min_import --cache .historical-data/alpaca.sqlite --page .historical-data/ibm-page-1.json --symbol IBM --start 2026-03-09T00:00:00Z --end 2026-03-10T00:00:00Z --retrieved-at 2026-10-28T15:00:00Z --rights-note "Private owner review pending"
```

Use the **real** capture time, not the example above. For extra pages repeat
`--page` in page order and add one `--cursor` per subsequent page containing
the exact request page_token. Keep under 100 pages and 4 MiB per page. A successful
output is `imported_not_qualified` with an immutable manifest ID, not replay
permission. The archive stores original exact bytes, original source URL/parameters,
retrieval timestamp, SHA-256 and classification. A checksum does not prove provider
authenticity, historical publication time or licensing. Do not manually create fake
Alpaca pages.

Then run the already-existing structural validator:

```powershell
python -m etoro_demo_bot.history.intraday_cli --cache .historical-data/alpaca.sqlite --manifest MANIFEST_ID --symbol IBM --start 2026-03-09 --end 2026-03-09 --audit-at 2026-10-28T15:10:00Z --calendar-verified-at 2026-10-28T15:05:00Z --output .historical-data/ibm-five-minute-audit.json
```

Replace the example times with actual reviewed instants and the exact manifest ID.
A single missing IEX bar or unsupported calendar date blocks structural qualification.

## Evidence qualification report contract

Report status is one of **blocked**, **conditional** or **qualified**, but
**qualified refers strictly to structural research coverage**, never tradability or
profitability. Record machine-readable fields for:

- source, feed, symbol, currency, raw/adjusted price basis, request window,
  bounded page count and total rows
- raw page SHA-256 hashes, manifest ID, request tokens (keep private), retrieval time,
  original publication/revision evidence (null unless independently verified)
- regular session expected/observed/missing/extra/duplicate intervals, zero volume,
  suspicious jumps, DST/holiday/early-close review
- split and corporate-action review, rights/retention reference, historical quote,
  FX, spread, costs, eligibility, liquidity, earnings, and point-in-time provenance
- explicit blockers, assumptions and reviewer timestamps.

Until all Phase 14 gates pass, use `status=blocked`, null profitability metrics
and `execution_authorized=false`. Imported captures are **retrieval-backed**;
their original first-known publication times are unknown. Never backdate them to
bar close to make a replay pass. Distinguish synthetic fixture archives from genuine
observations by source classification **and independent evidence**, not by changing labels.

## Outstanding owner action

1. Review Alpaca Basic account terms, IEX feed and permission to keep private historical data.
2. Perform a single bounded read-only capture **outside this repository**, using
   your own secure authorized client, with no order/account endpoint.
3. Preserve raw bytes, timestamps and page tokens privately, then run the
   offline import and audit commands above.
4. Independently substantiate original availability/revisions, splits, quotes,
   USD/EUR conversion, fees/spreads, symbol eligibility, session calendar and
   sufficient coverage. Otherwise real replay and EUR 500/1,000 comparisons stay blocked.

The present implementation does not include a first authenticated 5Min read command:
the existing client still prohibits it. That requires additional reviewed changes.
No paid services, execution routes or unattended network activity are enabled.

## Phase 15 blocked-outcome evidence report

`etoro_demo_bot.history.alpaca_5min_evidence.evidence_report` uses the existing
offline 2026 five-minute structural validator and produces a fail-closed,
machine-readable `alpaca-iex-5min-evidence-v1` report. The status remains `blocked`
until original publication/revision availability, redistribution/retention rights,
corporate actions, quotes/liquidity, costs/slippage, time-appropriate FX, eToro
instrument eligibility, and point-in-time earnings are independently documented.
The report deliberately writes `original_first_known_at=null`, `returns=null`,
`eur_500=null`, `eur_1000=null` and `execution_authorized=false`. Structural
qualification alone cannot unlock Phase 14 replay. The `write_evidence_report`
helper uses exclusive output creation and UTF-8/LF JSON. This is a conservative
baseline pending a reviewed evidence-supply and attestation interface.
