"""Audit a locally downloaded official daily CSV, or reproduce a cached snapshot offline."""

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from .archive import Archive
from .calendar import NYSE2026
from .models import Source
from .providers import AlphaVantageDaily, stamp
from .quality import inspect
from .report import write_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--csv", type=Path)
    group.add_argument("--snapshot")
    parser.add_argument("--symbol", default="IBM")
    parser.add_argument("--retrieved-at", help="Actual download time with timezone offset")
    parser.add_argument("--cache", type=Path, default=Path(".historical-data/archive.sqlite"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.csv and not args.retrieved_at:
        parser.error("--csv requires --retrieved-at; do not invent an earlier availability time")
    try:
        archive = Archive(args.cache)
        if args.csv:
            raw = args.csv.read_bytes()
            source = Source(
                "alpha_vantage_daily",
                f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={args.symbol}&datatype=csv",
                "https://www.alphavantage.co/terms_of_service/",
                stamp(args.retrieved_at),
                hashlib.sha256(raw).hexdigest(),
                "historical_observation",
                "Personal non-commercial research only; redistribution not verified.",
                symbol=args.symbol,
            )
            if source.retrieved_at > datetime.now(UTC):
                raise ValueError("Future retrieval time.")
            identity = archive.put(raw, source)
        else:
            identity = args.snapshot
            raw, source = archive.get(identity)
        calendar = NYSE2026(verified_at=source.retrieved_at)
        history = AlphaVantageDaily(source.symbol, calendar).parse(raw, source)
        quality = inspect(
            history,
            calendar,
            start=history.bars[0].start.date(),
            end=history.bars[-1].start.date(),
            as_of=source.retrieved_at,
        )
        write_readiness(history, quality, args.output, identity)
    except (ValueError, OSError, KeyError):
        parser.exit(1, "Historical audit failed; check local schema, dates and output directory.\n")
    print(f"Historical readiness audit saved. Snapshot: {identity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
