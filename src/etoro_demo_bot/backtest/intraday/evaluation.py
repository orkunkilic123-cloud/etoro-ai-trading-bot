"""Predeclared fixed-plan chronological evaluation; final test cannot select parameters."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..engine import Result
from ..evaluation import Split
from .engine import IntradayBacktest
from .models import Dataset, Plan
from .report import write_report


def window(data: Dataset, start: datetime, end: datetime) -> Dataset:
    sessions = tuple(w for w in data.series.sessions if start <= w.opens < end)
    if not sessions or sessions[0].opens != start or sessions[-1].closes >= end:
        raise ValueError("Evaluation requires complete sessions and an exact session-open start.")
    days = {w.day for w in sessions}
    series = replace(
        data.series,
        sessions=sessions,
        bars=tuple(b for b in data.series.bars if b.session.day in days),
    )
    ticks = tuple(t for t in data.ticks if any(w.opens <= t.at <= w.closes for w in sessions))
    return replace(data, series=series, ticks=ticks)


def evaluate_split(data: Dataset, plan: Plan, split: Split, directory: Path) -> dict[str, Result]:
    split.__post_init__()
    blockers = data.validate()
    if blockers:
        raise ValueError("Cannot split unqualified historical evidence.")
    directory.mkdir(parents=True, exist_ok=False)
    results = {}
    for name, start, end in (
        ("train", split.train_start, split.validation_start),
        ("validation", split.validation_start, split.test_start),
        ("test", split.test_start, split.end),
    ):
        result = IntradayBacktest(window(data, start, end), plan).run(directory / name)
        result.manifest["evaluation_role"] = name
        result.manifest["selection"] = "Single predeclared plan; no validation/test optimization."
        write_report(result, directory / f"{name}-report")
        results[name] = result
    return results


def walk_forward(
    data: Dataset, plan: Plan, splits: tuple[Split, ...], directory: Path
) -> tuple[dict[str, Result], ...]:
    if not splits or any(
        b.test_start < a.end or b.train_start < a.train_start
        for a, b in zip(splits, splits[1:], strict=False)
    ):
        raise ValueError("Walk-forward tests must be chronological and disjoint.")
    directory.mkdir(parents=True, exist_ok=False)
    return tuple(
        evaluate_split(data, plan, s, directory / f"fold-{i}") for i, s in enumerate(splits)
    )
