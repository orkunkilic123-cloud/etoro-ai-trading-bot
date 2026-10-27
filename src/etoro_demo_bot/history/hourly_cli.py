"""Offline hourly CSV coverage audit; never download data or run orders."""

import argparse
import json
from datetime import date
from pathlib import Path

from .archive import Archive
from .calendar import NYSE2026
from .hourly import CoveragePolicy, StudyWindow, cached_hourly, readiness_manifest
from .models import Source
from .providers import stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--csv", type=Path)
    inputs.add_argument("--snapshot")
    parser.add_argument("--source", type=Path, help="Source metadata JSON required with --csv")
    parser.add_argument(
        "--study", type=Path, required=True, help="Study boundaries and import metadata"
    )
    parser.add_argument("--cache", type=Path, default=Path(".historical-data/hourly.sqlite"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.csv and not args.source:
        parser.error("--csv requires an independently reviewed --source JSON")
    try:
        request = json.loads(args.study.read_text(encoding="utf-8-sig"))
        window = StudyWindow(
            date.fromisoformat(request["start"]),
            date.fromisoformat(request["end"]),
            *(stamp(request[k]) for k in ("train_at", "validation_at", "test_at", "finish_at")),
        )
        policy = CoveragePolicy(**request.get("policy", {}))
        audit_at = stamp(request["audit_at"])
        calendar = NYSE2026(verified_at=stamp(request["calendar_verified_at"]))
        archive = Archive(args.cache)
        if args.csv:
            metadata = json.loads(args.source.read_text(encoding="utf-8-sig"))
            metadata["retrieved_at"] = stamp(metadata["retrieved_at"])
            snapshot = archive.put(args.csv.read_bytes(), Source(**metadata))
        else:
            snapshot = args.snapshot
        history = cached_hourly(
            archive,
            snapshot,
            exchange=request["exchange"],
            currency=request["currency"],
            basis=request["basis"],
        )
        result = readiness_manifest(
            history, calendar, window, policy, audit_at=audit_at, snapshot=snapshot
        )
        result["import_metadata"] = {
            "exchange": request["exchange"],
            "currency": request["currency"],
            "basis": request["basis"],
        }
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, default=str, indent=2, sort_keys=True) + "\n")
    except (ValueError, TypeError, KeyError, OSError):
        parser.exit(
            1, "Hourly audit failed; check schema, integrity, calendar and new output path.\n"
        )
    print("Hourly readiness audit saved; this is not a backtest performance report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
