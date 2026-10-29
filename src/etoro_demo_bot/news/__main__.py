"""Offline import of owner-saved public SEC Atom bytes. Prints counts only."""

import argparse
import sqlite3
from pathlib import Path

from .archive import NewsArchive
from .events import MAX_BYTES, NewsError, timestamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    failed = False
    count = 0
    try:
        with args.feed.open("rb") as file:
            raw = file.read(MAX_BYTES + 1)
        count = NewsArchive(args.archive).ingest(
            raw, source=args.source, observed_at=timestamp(args.observed_at)
        )
    except (NewsError, OSError, sqlite3.Error):
        failed = True
    if failed:
        parser.exit(1, "Offline filing import blocked; review input and local storage.\n")
    print(
        f"New filing revisions: {count}; earnings-calendar coverage: UNKNOWN; execution disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
