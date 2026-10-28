"""Offline native five-minute manifest qualification; no keys, clients or trading imports."""

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from .archive import Archive
from .calendar import NYSE2026
from .intraday import qualify_download, research_report
from .providers import stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--audit-at", required=True)
    parser.add_argument("--calendar-verified-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        series = qualify_download(
            Archive.open_readonly(args.cache),
            args.manifest,
            args.symbol,
            start=args.start,
            end=args.end,
            audit_at=stamp(args.audit_at),
            calendar=NYSE2026(verified_at=stamp(args.calendar_verified_at)),
        )
        text = json.dumps(research_report(series), default=str, indent=2, sort_keys=True) + "\n"
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        parser.exit(
            1, "Intraday qualification failed; check evidence, window and new output path.\n"
        )
    print("Research structure qualified; replay and execution remain disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
