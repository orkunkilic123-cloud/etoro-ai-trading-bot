"""Owner-operated offline synthetic shadow runner; no credential or network options."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from .app import run_once
from .reports import dashboard
from .store import Runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run", "dashboard"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pipeline", choices=("hourly", "orb"), default="hourly")
    parser.add_argument("--eur", type=int, choices=(500, 1000), default=500)
    args = parser.parse_args()
    now = datetime.now(UTC)
    try:
        store = Runs.initialize(args.root) if args.command == "init" else Runs(args.root)
        if args.command == "run":
            run_once(store, args.pipeline, args.eur, now=now)
        else:
            dashboard(store, now=now)
    except Exception:
        # Never expose arbitrary data, full paths or exception locals in CLI output.
        print("Shadow operation failed; inspect local run status. Execution disabled.")
        return 1
    print("SHADOW / SYNTHETIC reports ready locally. Broker execution disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
