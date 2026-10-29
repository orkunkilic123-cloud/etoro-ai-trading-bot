# Offline SEC filing events and unknown earnings coverage

This extends the migration plan's news/earnings interface with a working saved-feed adapter.
It does not download feeds, open story links, use credentials, infer sentiment, or place orders.
No paid source is introduced. The input is an owner-obtained public SEC Atom feed; users remain
responsible for applicable access/reuse rules. No real filing fixture is redistributed here.

The sole Trader Skill reference remains the pinned day-trader-skill audit in
[DAY_TRADER_EVIDENCE.md](DAY_TRADER_EVIDENCE.md), commit
`3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`, particularly trader-news's Atom parsing/dedup concept.
This code is independently implemented; no upstream code or sample was copied. External text is
untrusted data and cannot select executable instructions or initiate a URL fetch.

## Contract and clocks

The parser accepts the Atom namespace and standard `entry/id`, `title`, `updated`, optional
`published`, `category@term`, and one alternate `link@href`. Atom semantics are specified in
[RFC 4287](https://www.rfc-editor.org/rfc/rfc4287). SEC current-filings Atom URLs use
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom`; filing links must be
HTTPS on sec.gov/www.sec.gov under `/Archives/edgar/data/`. The parser is an offline format
adapter, not evidence that the feed was obtained from SEC or is complete.

- `published_at`: explicit publication field when present, otherwise null,
  with `publication_basis=updated_only` to disclose the missing original publication timestamp.
- `updated_at`: source-supplied revision clock; must be aware and at/after publication when known.
- `observed_at`: owner-supplied time these exact bytes were observed; must be aware and no earlier
  than either source clock. The software cannot independently prove the owner's timestamp.
- Title/form/link are reported facts. Keyword tags only describe title word matches; there is no
  sentiment, earnings prediction, analyst consensus or causal interpretation.

Inputs are bounded to 2 MiB/1,000 entries, UTF-8, and capped ID/title lengths. DTD/entity declarations,
invalid XML/URLs, duplicate IDs, missing/naive/future/inconsistent times block the whole ingestion.
No missing timestamp is replaced with the current clock. No missing event becomes an assertion
that no event exists. HTML-containing title text remains plain external data; any consumer must
escape it before display.

## Storage and point-in-time queries

`NewsArchive(path).ingest(raw, source=..., observed_at=...)` parses then atomically appends the exact
raw bytes, SHA-256, source and observation time to SQLite. Stable source-feed/id/payload keys
count newly seen revisions once. Repeated observations are retained separately so corrections,
reversions and disappearance/reappearance do not overwrite history. `facts(as_of=...)` returns
only the most recently observed version per source/id available by that instant. Absence from a
later feed does not delete earlier evidence or prove a retraction. Observed-time rollback blocks.
Deduplication is per exact feed URL and ID; changing query URLs can create separate streams.

This local cache contains public text and private research timing. Use trusted local filesystem
permissions; it is not tamper-proof or suitable as an authoritative production account store.
It is separate from all strategy, risk and execution state. The first import creates its schema
only in an empty database. Reopening requires exactly the known news tables, with no unrelated
user tables, views or triggers; unrelated or partial schemas are rejected before schema writes.
Reopening a valid archive preserves prior snapshots/revisions. Never select a risk/execution DB.

`NewsArchive.window(instrument_id, as_of=...)` satisfies the existing `EarningsCalendar` interface
but always returns **complete=False**, no inferred announcements and an explicit unknown source.
A filing feed is not a qualified future earnings calendar and has no verified eToro instrument
mapping. The actual Strategy Engine's `earnings_safe` rejects this window. Connecting it must
never relax the strategy's existing earnings gate. A future qualified calendar adapter needs
coverage intervals, instrument mapping, original availability and announced schedule revisions.

## Windows offline import

From the project's configured Python environment, with a privately saved public Atom file and
its actual observation timestamp (example time only; replace with truthful metadata):

```powershell
New-Item -ItemType Directory -Force .historical-data | Out-Null
python -m etoro_demo_bot.news --feed C:\Research\sec-feed.xml --source 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom' --observed-at '2026-10-29T16:00:00Z' --archive .historical-data/news.sqlite
python -m pytest -q tests/test_news_events.py
```

The command prints newly inserted revision counts, UNKNOWN calendar coverage and disabled
execution, never article titles, IDs or file contents. Repeating an unchanged import reports zero
new revisions. No remote request is made. No scheduler is installed by this component.

## Validation and limitations

Deterministic synthetic tests cover clocks, revisions/as-of queries, restart deduplication,
reverted revisions, unsafe XML/URLs, future data, limits and rejection by the actual earnings gate.
They establish parser/storage behavior only. No source freshness, historical completeness,
company-to-instrument mapping, sentiment accuracy or authenticated broker compatibility is claimed.
