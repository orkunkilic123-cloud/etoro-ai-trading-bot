"""Synthetic-only chronological replay and 10,000-draw stress contract tests."""

import json
import socket
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.alpaca.config import Credentials
from etoro_demo_bot.backtest import Result, Split
from etoro_demo_bot.backtest.intraday import IntradayBacktest, Plan
from etoro_demo_bot.backtest.intraday.evaluation import evaluate_split, walk_forward, window
from etoro_demo_bot.backtest.intraday.fixtures import synthetic_dataset
from etoro_demo_bot.backtest.intraday.report import write_bundle
from etoro_demo_bot.history.calendar import NYSE2026
from etoro_demo_bot.monte_carlo.intraday import compare


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Research evaluation cannot connect or load credentials.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(Credentials, "from_environment", blocked)


@pytest.fixture(scope="module")
def pool(tmp_path_factory: pytest.TempPathFactory) -> tuple[Result, ...]:
    # Module-scoped fixtures are independent of the offline guard; the engines have no clients.
    directory = tmp_path_factory.mktemp("synthetic-orb-pool")
    cal = NYSE2026(verified_at=datetime(2026, 1, 1, tzinfo=UTC))
    days = tuple(s.day for s in cal.sessions(date(2026, 3, 2), date(2026, 4, 2)))[:21]
    with pytest.MonkeyPatch.context() as patch:

        def blocked(*args: Any, **kwargs: Any) -> Any:
            pytest.fail("Synthetic pool creation must stay offline.")

        patch.setattr(socket.socket, "connect", blocked)
        patch.setattr(socket.socket, "connect_ex", blocked)
        patch.setattr(Credentials, "from_environment", blocked)
        return tuple(
            IntradayBacktest(synthetic_dataset((d,))).run(directory / str(i))
            for i, d in enumerate(days)
        )


def test_ten_thousand_draws_reproducible_and_same_policy(
    pool: tuple[Result, ...], tmp_path: Path
) -> None:
    as_of = datetime.fromisoformat(pool[19].manifest["end"])
    a = compare(pool[:20], pool[20], as_of=as_of)
    b = compare(pool[:20], pool[20], as_of=as_of)
    assert a == b and len(a.scenarios) == 10000
    assert a.manifest["status"] == "model_based_stress"
    assert a.manifest["evidence"]["kind"] == "synthetic_fixture"
    assert a.manifest["plan_digest"] == pool[20].manifest["plan_digest"]
    assert {row["net_return"] for row in a.scenarios} <= {
        r.metrics["net_return"] for r in pool[:20]
    }
    assert {row["costs_usd"] for row in a.scenarios} <= {
        r.metrics["trading_costs_usd"] for r in pool[:20]
    }
    assert compare(pool[:20], pool[20], as_of=as_of, seed=20).scenarios != a.scenarios
    write_bundle(asdict(a), tmp_path / "a")
    write_bundle(asdict(b), tmp_path / "b")
    for p in (tmp_path / "a").iterdir():
        assert p.read_bytes() == (tmp_path / "b" / p.name).read_bytes()
    assert len(json.loads((tmp_path / "a" / "report.json").read_text())["scenarios"]) == 10000


@pytest.mark.parametrize(
    "bad",
    [
        "too_small",
        "overlap",
        "unordered",
        "future",
        "test_used",
        "cost_policy",
        "mixed_evidence",
        "inventory",
        "multi_session",
        "test_inventory",
        "seed",
        "naive",
    ],
)
def test_bootstrap_blocks_incompatible_or_leaking_evidence(
    pool: tuple[Result, ...], bad: str
) -> None:
    training, test = pool[:20], pool[20]
    as_of = datetime.fromisoformat(training[-1].manifest["end"])
    seed = 19
    if bad == "too_small":
        training = training[:19]
    elif bad == "overlap":
        training = (training[0], training[0], *training[2:])
    elif bad == "unordered":
        training = tuple(reversed(training))
    elif bad == "future":
        as_of -= timedelta(days=1)
    elif bad == "test_used":
        training = (*training[:19], test)
    elif bad in ("cost_policy", "mixed_evidence", "inventory", "multi_session"):
        manifest = dict(training[0].manifest)
        if bad == "cost_policy":
            manifest["plan_digest"] = "changed"
        elif bad == "mixed_evidence":
            manifest["status"] = "conditional"
        elif bad == "inventory":
            manifest["unresolved_inventory"] = True
        else:
            manifest["session_count"] = 2
        training = (replace(training[0], manifest=manifest), *training[1:])
    elif bad == "test_inventory":
        test = replace(test, manifest={**test.manifest, "unresolved_inventory": True})
    elif bad == "seed":
        seed = -1
    elif bad == "naive":
        as_of = as_of.replace(tzinfo=None)
    result = compare(training, test, as_of=as_of, seed=seed)
    assert result.manifest["status"] == "blocked" and not result.metrics and not result.scenarios


def test_split_and_walkforward_freeze_plan_and_avoid_final_test_selection(tmp_path: Path) -> None:
    days = tuple(
        s.day
        for s in NYSE2026(verified_at=datetime(2026, 1, 1, tzinfo=UTC)).sessions(
            date(2026, 3, 9), date(2026, 3, 13)
        )
    )
    data = synthetic_dataset(days)
    sessions = data.series.sessions
    split = Split(
        sessions[0].opens,
        sessions[1].opens,
        sessions[2].opens,
        sessions[2].closes + timedelta(seconds=1),
    )
    result = evaluate_split(data, Plan(), split, tmp_path / "split")
    assert set(result) == {"train", "validation", "test"}
    assert len({r.manifest["plan_digest"] for r in result.values()}) == 1
    for role, r in result.items():
        assert r.manifest["evaluation_role"] == role
        assert "no validation/test optimization" in r.manifest["selection"]
        assert r.manifest["session_count"] == 1
    second = Split(
        sessions[1].opens,
        sessions[2].opens,
        sessions[3].opens,
        sessions[3].closes + timedelta(seconds=1),
    )
    folds = walk_forward(data, Plan(), (split, second), tmp_path / "folds")
    assert len(folds) == 2
    assert folds[0]["test"].manifest["end"] < folds[1]["test"].manifest["start"]
    with pytest.raises(ValueError, match="disjoint"):
        walk_forward(data, Plan(), (split, split), tmp_path / "invalid")


def test_partial_session_split_and_qualification_rejected(tmp_path: Path) -> None:
    data = synthetic_dataset()
    w = data.series.sessions[0]
    with pytest.raises(ValueError, match="complete sessions"):
        window(data, w.opens + timedelta(minutes=5), w.closes + timedelta(seconds=1))
    with pytest.raises(ValueError, match="complete sessions"):
        window(data, w.opens, w.closes - timedelta(minutes=5))
    split = Split(w.opens, w.opens + timedelta(hours=1), w.opens + timedelta(hours=2), w.closes)
    bad = replace(data, series=replace(data.series, bars=data.series.bars[:-1]))
    with pytest.raises(ValueError):
        evaluate_split(bad, Plan(), split, tmp_path / "bad")


@pytest.mark.parametrize("bad", ["nan", "naive", "instrument", "risk", "no_metrics"])
def test_malformed_results_are_blocked(pool: tuple[Result, ...], bad: str) -> None:
    training = list(pool[:20])
    first = training[0]
    if bad == "nan":
        first = replace(first, metrics={**first.metrics, "net_return": float("nan")})
    elif bad == "naive":
        first = replace(first, manifest={**first.manifest, "end": "2026-03-02T21:00:00"})
    elif bad == "instrument":
        first = replace(
            first,
            manifest={
                **first.manifest,
                "dataset": {**first.manifest["dataset"], "instrument": "other"},
            },
        )
    elif bad == "risk":
        first = replace(first, manifest={**first.manifest, "risk_policy": "other"})
    else:
        first = replace(first, metrics={})
    training[0] = first
    result = compare(
        tuple(training), pool[20], as_of=datetime.fromisoformat(pool[19].manifest["end"])
    )
    assert result.manifest["status"] == "blocked" and not result.scenarios and not result.metrics


def test_synthetic_cli_reports_and_refuses_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from etoro_demo_bot.backtest.intraday.__main__ import main

    output = tmp_path / "synthetic-demo"
    monkeypatch.setattr(
        sys, "argv", ["orb-research", "--output", str(output), "--eur", "1000", "--seed", "7"]
    )
    main()
    payload = json.loads((output / "monte-carlo" / "report.json").read_text())
    assert payload["manifest"]["status"] == "model_based_stress"
    assert payload["manifest"]["plan"]["simulation"]["initial_eur"] == "1000"
    assert len(payload["scenarios"]) == 10000
    assert (output / "session-20" / "metrics.csv").exists()
    with pytest.raises(FileExistsError):
        main()


def test_nonfinite_held_out_result_is_blocked(pool: tuple[Result, ...]) -> None:
    held_out = replace(pool[20], metrics={**pool[20].metrics, "net_return": float("nan")})
    result = compare(pool[:20], held_out, as_of=datetime.fromisoformat(pool[19].manifest["end"]))
    assert result.manifest["status"] == "blocked" and not result.metrics
