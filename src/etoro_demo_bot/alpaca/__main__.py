"""Explicit future read-only data download. No secrets are loaded unless networking is opted in."""

import argparse
import json
import sqlite3
from pathlib import Path

from ..history.archive import Archive
from ..history.providers import stamp
from ..timeframes import Timeframe
from .client import MarketDataClient
from .config import Credentials, DataError
from .contracts import BARS, ORIGIN, BarsQuery


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--enable-network", action="store_true")
    mode.add_argument(
        "--dry-run", action="store_true", help="Validate query offline; no keys or cache"
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="Inclusive aware bar-start timestamp")
    parser.add_argument("--end", required=True, help="Inclusive aware bar-start timestamp")
    parser.add_argument("--timeframe", choices=("1Hour", "5Min"), default="1Hour")
    parser.add_argument("--enable-five-minute", action="store_true")
    parser.add_argument("--adjustment", choices=("raw", "split"), default="raw")
    parser.add_argument("--cache", type=Path, default=Path(".historical-data/alpaca.sqlite"))
    parser.add_argument(
        "--request-limit",
        type=int,
        choices=(1, 3, 30, 300),
        default=300,
        help="Total GET budget including retries and pages; use 1 for the first read-only test",
    )
    args = parser.parse_args()
    if not args.enable_network and not args.dry_run:
        parser.error(
            "Networking disabled. Explicit --enable-network is required before loading keys."
        )
    failed = False
    try:
        query = BarsQuery(
            tuple(args.symbols),
            stamp(args.start),
            stamp(args.end),
            args.adjustment,
            Timeframe(args.timeframe),
        )
        if args.dry_run:
            print(json.dumps({"method": "GET", "url": ORIGIN + BARS, "params": query.params()}))
            print("Offline query only; access, historical age and coverage remain unverified.")
            return 0
        if query.timeframe is Timeframe.FIVE_MINUTES and not args.enable_five_minute:
            raise DataError("Five-minute read requires separate owner opt-in.")
        if args.enable_five_minute and query.timeframe is not Timeframe.FIVE_MINUTES:
            raise DataError("Five-minute opt-in requires 5Min timeframe.")
        if args.enable_five_minute and args.request_limit > 30:
            raise DataError("Five-minute request budget must be at most 30.")
        credentials = Credentials.from_environment()
        archive = Archive(args.cache)
        with MarketDataClient(
            credentials,
            archive,
            enabled=True,
            request_limit=args.request_limit,
            allow_five_minute=args.enable_five_minute,
        ) as client:
            identity = client.fetch(query)
    except (DataError, ValueError, OSError, sqlite3.Error):
        failed = True
    if failed:
        parser.exit(
            1, "Alpaca data download failed; review local configuration, access and input.\n"
        )
    print(f"Read-only data snapshot: {identity}")
    print("Historical availability, completeness and replay readiness still require review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
