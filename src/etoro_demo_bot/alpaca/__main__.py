"""Explicit future read-only data download. No secrets are loaded unless networking is opted in."""

import argparse
import sqlite3
from pathlib import Path

from ..history.archive import Archive
from ..history.providers import stamp
from .client import MarketDataClient
from .config import Credentials, DataError
from .contracts import BarsQuery


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-network", action="store_true")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="Inclusive aware bar-start timestamp")
    parser.add_argument("--end", required=True, help="Inclusive aware bar-start timestamp")
    parser.add_argument("--adjustment", choices=("raw", "split"), default="raw")
    parser.add_argument("--cache", type=Path, default=Path(".historical-data/alpaca.sqlite"))
    args = parser.parse_args()
    if not args.enable_network:
        parser.error(
            "Networking disabled. Explicit --enable-network is required before loading keys."
        )
    failed = False
    try:
        query = BarsQuery(tuple(args.symbols), stamp(args.start), stamp(args.end), args.adjustment)
        credentials = Credentials.from_environment()
        archive = Archive(args.cache)
        with MarketDataClient(credentials, archive, enabled=True) as client:
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
