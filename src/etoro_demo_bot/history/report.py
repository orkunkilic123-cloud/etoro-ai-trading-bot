"""Reproducible readiness reports: missing results are null, never fabricated returns."""

import csv
import json
from dataclasses import asdict
from pathlib import Path

from ..strategy.models import Strategy
from .models import History, Quality
from .replay import blockers


def write_readiness(history: History, quality: Quality, directory: Path, snapshot: str) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    reasons = list(blockers(history)) + [f.code for f in quality.findings if f.blocking]
    reasons.append("REVIEWED_QUOTE_FX_ELIGIBILITY_EARNINGS_EVENTS_NOT_SUPPLIED")
    rows = [
        {"strategy": strategy, "initial_eur": eur, "status": "blocked", "total_return": None}
        for eur in (500, 1000)
        for strategy in [*(s.value for s in Strategy), "buy_and_hold", "cash"]
    ]
    payload = {
        "snapshot": snapshot,
        "source": asdict(history.source),
        "symbol": history.symbol,
        "resolution": history.resolution,
        "pipeline_version": "history-v1",
        "exchange": history.exchange,
        "currency": history.currency,
        "price_basis": history.basis,
        "actions_complete": history.actions_complete,
        "point_in_time_verified": history.point_in_time_verified,
        "quality": asdict(quality),
        "blockers": sorted(set(reasons)),
        "comparisons": rows,
        "interpretation": "Data readiness audit only; no strategy performance evidence.",
    }
    (directory / "readiness.json").write_text(
        json.dumps(payload, default=str, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    with (directory / "comparisons.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (directory / "README.md").write_text(
        "# Historical data readiness\n\nNo backtest performance is claimed.\n\n"
        f"Snapshot: `{snapshot}`\n\nRows: {quality.rows}; {quality.first} to {quality.last}.\n\n"
        "All three strategies and both benchmarks remain blocked for EUR 500 and EUR 1,000.\n\n"
        + "\n".join(f"- {reason}" for reason in sorted(set(reasons)))
        + "\n",
        encoding="utf-8",
    )
