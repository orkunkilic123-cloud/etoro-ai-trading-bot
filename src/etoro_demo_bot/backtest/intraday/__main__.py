"""Offline synthetic-only demo. No input URL, credentials or broker configuration."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ...history.calendar import NYSE2026
from ...monte_carlo.intraday import compare
from ..models import Simulation
from .engine import IntradayBacktest
from .fixtures import synthetic_dataset
from .models import Plan
from .report import write_bundle, write_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic ORB replay and training-session bootstrap"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--eur", choices=("500", "1000"), default="500")
    parser.add_argument("--seed", type=int, default=19)
    args = parser.parse_args()
    if not 0 <= args.seed < 2**64:
        parser.error("Seed must be an unsigned 64-bit integer.")
    args.output.mkdir(parents=True, exist_ok=False)
    review = synthetic_dataset().series.sessions[0].calendar_verified_at
    days = tuple(
        s.day for s in NYSE2026(verified_at=review).sessions(date(2026, 3, 2), date(2026, 4, 2))
    )[:21]
    plan = Plan(simulation=Simulation(initial_eur=Decimal(args.eur)))
    results = []
    for i, day in enumerate(days):
        result = IntradayBacktest(synthetic_dataset((day,)), plan).run(args.output / f"state-{i}")
        write_report(result, args.output / f"session-{i}")
        results.append(result)
    comparison = compare(
        tuple(results[:20]),
        results[20],
        as_of=datetime.fromisoformat(results[19].manifest["end"]),
        seed=args.seed,
    )
    write_bundle(asdict(comparison), args.output / "monte-carlo")
    print("Synthetic engineering reports written; no market evidence or profitability claim.")


if __name__ == "__main__":
    main()
