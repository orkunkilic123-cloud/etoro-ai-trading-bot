"""Offline, reproducible multi-symbol Alpaca 5Min evidence audit; no network/execution."""

import argparse
import csv
import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path

from .archive import Archive
from .calendar import NYSE2026
from .intraday import qualify_download

REQUIRED = (
    "original_publication_revisions",
    "source_license_and_retention",
    "corporate_actions_split_basis",
    "historical_quotes_spreads_liquidity",
    "historical_execution_costs",
    "historical_point_in_time_fx",
    "historical_instrument_eligibility",
    "historical_earnings",
)


def audit_symbols(
    archive: Archive,
    manifests: dict[str, str],
    *,
    start: date,
    end: date,
    audit_at: datetime,
    calendar_verified_at: datetime,
) -> dict[str, object]:
    """Audit archive-only provenance and full sessions; never infer old publication times."""
    if (
        not manifests
        or len(manifests) > 20
        or start > end
        or (end - start).days > 365
        or audit_at.tzinfo is None
        or audit_at.utcoffset() is None
        or calendar_verified_at.tzinfo is None
        or calendar_verified_at.utcoffset() is None
        or calendar_verified_at > audit_at
    ):
        raise ValueError("INVALID_OFFLINE_AUDIT_SCOPE")
    calendar = NYSE2026(verified_at=calendar_verified_at)
    expected_sessions = calendar.sessions(start, end)
    results: list[dict[str, object]] = []
    for symbol, manifest in sorted(manifests.items()):
        if not symbol or not isinstance(manifest, str) or len(manifest) != 64:
            raise ValueError("INVALID_SYMBOL_OR_MANIFEST")
        observed = 0
        expected = sum(int((s.closes - s.opens).total_seconds() // 300) for s in expected_sessions)
        source_sha: str | None = None
        retrieved_at: str | None = None
        reason: list[str] = []
        try:
            series = qualify_download(
                archive,
                manifest,
                symbol,
                start=start,
                end=end,
                audit_at=audit_at,
                calendar=calendar,
            )
            observed = len(series.bars)
            source_sha = series.source.raw_sha256
            retrieved_at = series.source.retrieved_at.isoformat()
        except (ValueError, OSError):
            reason.append("STRUCTURE_OR_PROVENANCE_NOT_QUALIFIED")
        reason.extend("MISSING_" + field.upper() for field in REQUIRED)
        results.append(
            {
                "symbol": symbol,
                "manifest": manifest,
                "source_sha256": source_sha,
                "retrieved_at": retrieved_at,
                "feed": "iex",
                "timeframe": "5Min",
                "price_basis": "raw",
                "expected_regular_bars": expected,
                "qualified_regular_bars": observed,
                "structural_coverage": "qualified" if not reason[0].startswith("STRUCTURE") else "blocked",
                "status": "blocked",
                "replay_eligible": False,
                "original_first_known_at": None,
                "blockers": reason,
            }
        )
    return {
        "schema": "phase16-alpaca-iex-5min-audit-v1",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "audit_at": audit_at.isoformat(),
        "calendar_verified_at": calendar_verified_at.isoformat(),
        "datasets": results,
        "genuine_replay_eligible": False,
        "execution_authorized": False,
        "eur_500_returns": None,
        "eur_1000_returns": None,
        "monte_carlo_returns": None,
        "cash_comparison": None,
        "buy_and_hold_comparison": None,
    }


def _outputs(report: dict[str, object]) -> tuple[bytes, bytes, bytes]:
    rows = report["datasets"]
    assert isinstance(rows, list)
    raw = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    buffer = io.StringIO(newline="")
    fields = ("symbol", "manifest", "status", "structural_coverage", "expected_regular_bars",
              "qualified_regular_bars", "replay_eligible", "blockers")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow([
            row[k] if k != "blockers" else ";".join(row[k])
            for k in fields
        ])
    csv_bytes = buffer.getvalue().encode("utf-8")
    md = [
        "# Phase 16 — Alpaca IEX 5Min evidence audit",
        "",
        "Offline structural assessment only. No authenticated download or execution occurred.",
        "No historical profitability, eToro fills or original availability are established.",
        "",
        "| Symbol | Structural coverage | Bars | Replay |",
        "| --- | --- | ---: | --- |",
    ]
    for row in rows:
        md.append(
            f"| {row['symbol']} | {row['structural_coverage']} | "
            f"{row['qualified_regular_bars']}/{row['expected_regular_bars']} | blocked |"
        )
    md.extend(["", "## Missing independent evidence", ""])
    for item in REQUIRED:
        md.append(f"- {item.replace('_', ' ')}")
    md.extend(["", "Raw hashes authenticate stored bytes, not original provider publication.",
               "IEX is venue-specific, not consolidated volume or executable eToro pricing.",
               "Blocked: ORB replay, 10,000-draw MC, cash/buy-and-hold and EUR 500/1,000 results.",
               ""])
    return raw, csv_bytes, "\n".join(md).encode("utf-8")


def write_bundle(directory: Path, report: dict[str, object]) -> dict[str, str]:
    """Exclusive output directory; do not overwrite prior evidence."""
    if directory.exists():
        raise FileExistsError("Evidence output already exists.")
    directory.mkdir(parents=True, exist_ok=False)
    names = ("evidence.json", "evidence.csv", "evidence.md")
    result: dict[str, str] = {}
    for name, data in zip(names, _outputs(report), strict=True):
        with (directory / name).open("xb") as target:
            target.write(data)
        result[name] = hashlib.sha256(data).hexdigest()
    with (directory / "sha256.json").open("xb") as target:
        target.write((json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Private, offline multi-symbol evidence audit")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--item", nargs=2, action="append", required=True, metavar=("SYMBOL", "MANIFEST"))
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--audit-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--calendar-verified-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    symbols = dict(args.item)
    if len(symbols) != len(args.item):
        parser.error("Duplicate symbols are forbidden.")
    try:
        report = audit_symbols(
            Archive.open_readonly(args.cache),
            symbols,
            start=args.start,
            end=args.end,
            audit_at=args.audit_at,
            calendar_verified_at=args.calendar_verified_at,
        )
        checksums = write_bundle(args.output, report)
    except (ValueError, OSError):
        parser.error("Audit blocked: invalid input, provenance or output.")
    print(json.dumps({"status": "blocked_for_replay", "sha256": checksums}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
