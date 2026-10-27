"""Chronological selection: training chooses a frozen plan; final test is evaluation only."""

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from ..scanner.models import aware
from ..strategy.journal import digest
from .engine import Backtest, Result
from .models import Dataset, Plan
from .report import write_report


@dataclass(frozen=True)
class Split:
    train_start: datetime
    validation_start: datetime
    test_start: datetime
    end: datetime

    def __post_init__(self) -> None:
        times = (self.train_start, self.validation_start, self.test_start, self.end)
        if not all(aware(t) for t in times) or not all(
            a < b for a, b in zip(times, times[1:], strict=False)
        ):
            raise ValueError("Splits must be aware, chronological and non-overlapping.")


def window(data: Dataset, start: datetime, end: datetime) -> Dataset:
    ticks = tuple(t for t in data.ticks if start <= t.at < end)
    boundary = next((t for t in data.ticks if t.at == start), None)
    if boundary is None or len(ticks) < 2:
        raise ValueError(
            "Each evaluation boundary needs timestamped FX/quote evidence and at least two events."
        )
    return replace(
        data,
        start=start,
        end=ticks[-1].at,
        ticks=ticks,
        initial_usd_per_eur=boundary.evidence.budget.usd_per_eur,
        initial_fx_known_at=boundary.evidence.budget.fx_observed_at,
    )


def evaluate_split(
    data: Dataset, plans: tuple[Plan, ...], split: Split, directory: Path
) -> dict[str, Result]:
    if not plans:
        raise ValueError("At least one predeclared candidate plan is required.")
    directory.mkdir(parents=True, exist_ok=False)
    train = window(data, split.train_start, split.validation_start)
    scored = []
    for index, plan in enumerate(plans):
        result = Backtest(train, plan).run(directory / f"train-{index}")
        write_report(result, directory / f"train-{index}-report")
        scored.append(
            (result.metrics["total_return"], digest(result.manifest["plan"]), index, result)
        )
    # Selection never reads validation/test outcomes; deterministic tie break.
    _, _, index, best = max(scored, key=lambda x: (x[0], x[1]))
    plan = plans[index]
    results = {"train": best}
    for name, start, end in (
        ("validation", split.validation_start, split.test_start),
        ("test", split.test_start, split.end),
    ):
        results[name] = Backtest(window(data, start, end), plan).run(directory / name)
        results[name].manifest["evaluation_role"] = name
        results[name].manifest["selection"] = (
            "Training-only total return; fixed before validation/test."
        )
        write_report(results[name], directory / f"{name}-report")
    return results


def walk_forward(
    data: Dataset, plans: tuple[Plan, ...], splits: tuple[Split, ...], directory: Path
) -> tuple[dict[str, Result], ...]:
    if any(
        b.test_start < a.end or b.train_start < a.train_start
        for a, b in zip(splits, splits[1:], strict=False)
    ):
        raise ValueError("Walk-forward test windows must be chronological and disjoint.")
    directory.mkdir(parents=True, exist_ok=False)
    return tuple(
        evaluate_split(data, plans, split, directory / f"fold-{i}")
        for i, split in enumerate(splits)
    )
