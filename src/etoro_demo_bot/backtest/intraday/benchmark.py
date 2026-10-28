"""Offline local compute benchmark, explicitly outside deterministic report contents."""

import statistics
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ...history.calendar import NYSE2026
from ...monte_carlo.intraday import compare
from .engine import IntradayBacktest
from .fixtures import synthetic_dataset
from .models import Plan


@dataclass(frozen=True)
class Timing:
    replay_seconds: tuple[float, ...]
    monte_carlo_seconds: float
    metrics: dict[str, Any]


def benchmark(directory: Path) -> Timing:
    directory.mkdir(parents=True, exist_ok=False)
    days = tuple(
        s.day
        for s in NYSE2026(
            verified_at=synthetic_dataset().series.sessions[0].calendar_verified_at
        ).sessions(date(2026, 3, 2), date(2026, 4, 3))
    )
    results, times = [], []
    plan = Plan()
    for i, day in enumerate(days[:21]):
        data = synthetic_dataset((day,))
        started = time.perf_counter()
        results.append(IntradayBacktest(data, plan).run(directory / f"session-{i}"))
        times.append(time.perf_counter() - started)
    started = time.perf_counter()
    mc = compare(
        tuple(results[:20]),
        results[20],
        as_of=synthetic_dataset((days[19],)).series.sessions[0].closes,
    )
    elapsed = time.perf_counter() - started
    if mc.manifest["status"] != "model_based_stress" or len(mc.scenarios) != 10000:
        raise ValueError("Synthetic benchmark qualification failed.")
    return Timing(
        tuple(times),
        elapsed,
        {
            "replay_p50_seconds": statistics.median(times),
            "replay_p95_seconds": sorted(times)[19],
            "sessions": len(times),
            "bars_per_session": 78,
            "trials": len(mc.scenarios),
            "status": mc.manifest["status"],
        },
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="orb-benchmark-") as root:
        result = benchmark(Path(root) / "new-run")
        print({**result.metrics, "monte_carlo_seconds": result.monte_carlo_seconds})
