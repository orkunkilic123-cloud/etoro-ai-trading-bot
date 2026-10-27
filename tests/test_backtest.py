"""Synthetic replay tests. All numbers here are invented engineering inputs."""

import ast
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.backtest import (
    Backtest,
    Plan,
    Result,
    Simulation,
    Split,
    evaluate_split,
    walk_forward,
    write_report,
)
from etoro_demo_bot.backtest.evaluation import window
from etoro_demo_bot.backtest.fixtures import synthetic_dataset
from etoro_demo_bot.backtest.metrics import metrics
from etoro_demo_bot.backtest.models import Dataset, Tick
from etoro_demo_bot.strategy import Rules, Strategy, Style


def plan(**kwargs: Any) -> Plan:
    return Plan(Rules(style=Style.SWING), Simulation(**kwargs))


def small() -> Dataset:
    data = synthetic_dataset(1)
    return replace(data, ticks=data.ticks[:4], end=data.ticks[3].at)


def fills(result: Result) -> list[dict[str, Any]]:
    return [e for e in result.events if e["kind"] == "entry_fill"]


def test_next_quote_fill_and_gap_exit(tmp_path: Path) -> None:
    data = small()
    result = Backtest(data, plan()).run(tmp_path / "run")
    entry = fills(result)
    assert len(entry) == 1
    assert entry[0]["at"] == data.ticks[1].at.isoformat()
    assert entry[0]["at"] != data.ticks[0].at.isoformat()
    assert len(result.trades) == 1
    assert D(result.trades[0]["exit"]) < D("125")
    assert D(result.trades[0]["pnl"]) < 0
    assert result.metrics["trading_costs_usd"] > 0
    assert D(result.manifest["open_units"]) == 0
    assert result.manifest["provenance"]["kind"] == "synthetic"


@pytest.mark.parametrize("eur", [D("500"), D("1000")])
@pytest.mark.parametrize("style", list(Style))
def test_portfolios_and_styles(tmp_path: Path, eur: D, style: Style) -> None:
    p = Plan(Rules(style=style), Simulation(initial_eur=eur))
    result = Backtest(small(), p).run(tmp_path / "run")
    assert fills(result)
    assert all(D(e["cash"]) >= 0 for e in result.equity)
    assert (
        result.metrics["annualized_return"] is None and result.metrics["sharpe_daily_365"] is None
    )
    assert result.benchmarks["cash_usd"]["metrics"]["total_return"] < 0


def test_partial_fill_cancel_remainder_and_cash(tmp_path: Path) -> None:
    result = Backtest(small(), plan(fill_fraction=D(".5"))).run(tmp_path / "run")
    entry = fills(result)[0]
    assert D(str(entry["unfilled_cancelled"])) > 0
    assert len(result.trades) == 1 and D(result.manifest["open_units"]) > 0
    assert all(D(p["cash"]) >= 0 for p in result.equity)


@pytest.mark.parametrize("delay", [6, 30, 60])
def test_delay_cannot_use_old_signal_or_same_bar(tmp_path: Path, delay: int) -> None:
    result = Backtest(small(), plan(delay_seconds=delay)).run(tmp_path / "run")
    assert not fills(result)
    assert any(
        e["kind"] == "entry_cancelled" and e["reason"] == "SIGNAL_EXPIRED" for e in result.events
    )


def test_market_closure_blocks_fills(tmp_path: Path) -> None:
    data = small()
    ticks = list(data.ticks)
    ticks[1] = replace(
        ticks[1],
        evidence=replace(
            ticks[1].evidence, session=replace(ticks[1].evidence.session, is_open=False)
        ),
    )
    result = Backtest(replace(data, ticks=tuple(ticks)), plan()).run(tmp_path / "run")
    assert not fills(result)


def test_future_history_does_not_change_prefix(tmp_path: Path) -> None:
    data = small()
    first = Backtest(data, plan()).run(tmp_path / "first")
    future = data.history[-1]
    altered = replace(future, candle=replace(future.candle, close=999, high=1000))
    second = Backtest(replace(data, history=data.history[:-1] + (altered,)), plan()).run(
        tmp_path / "second"
    )
    assert first.events == second.events and first.equity == second.equity
    assert first.manifest["dataset_digest"] != second.manifest["dataset_digest"]


def test_late_publication_excludes_indicator_input(tmp_path: Path) -> None:
    data = small()
    bars = list(data.history)
    bars[59] = replace(bars[59], available_at=data.start + timedelta(hours=5))
    result = Backtest(replace(data, history=tuple(bars)), plan()).run(tmp_path / "run")
    assert result.manifest["dataset_digest"]
    assert all(e["at"] >= data.start.isoformat() for e in result.events)
    # No early access to the only high-volume completed bar.
    assert not fills(result)


def test_fill_price_risk_recheck_rejects_gap_up(tmp_path: Path) -> None:
    data = small()
    ticks = list(data.ticks)
    ticks[1] = replace(ticks[1], quote=replace(ticks[1].quote, bid=D("200"), ask=D("201")))
    result = Backtest(replace(data, ticks=tuple(ticks)), plan()).run(tmp_path / "run")
    assert not fills(result)
    reject = next(e for e in result.events if e["kind"] == "entry_cancelled")
    assert "TRADE_RISK_LIMIT" in reject["reasons"]


def test_kill_switch_is_enforced(tmp_path: Path) -> None:
    result = Backtest(small(), plan(kill_switch=True)).run(tmp_path / "run")
    assert not fills(result)
    assert any(
        e["kind"] == "risk_halt" and "KILL_SWITCH_ACTIVE" in e["reasons"] for e in result.events
    )


def test_daily_loss_latches_after_gap(tmp_path: Path) -> None:
    data = small()
    ticks = list(data.ticks)
    ticks[2] = replace(ticks[2], quote=replace(ticks[2].quote, bid=D("1"), ask=D("1.02")))
    ticks[3] = replace(ticks[3], quote=replace(ticks[3].quote, bid=D("134.8"), ask=D("134.82")))
    result = Backtest(replace(data, ticks=tuple(ticks)), plan()).run(tmp_path / "run")
    halts = [e for e in result.events if e["kind"] == "risk_halt"]
    assert len(halts) == 2 and all("DAILY_LOSS_LIMIT" in e["reasons"] for e in halts)


def test_minimum_fractional_eligibility_and_liquidity(tmp_path: Path) -> None:
    changes: list[tuple[str, Callable[[Tick], Tick]]] = [
        (
            "minimum",
            lambda t: replace(
                t,
                evidence=replace(
                    t.evidence, eligibility=replace(t.evidence.eligibility, minimum_usd=D("10000"))
                ),
            ),
        ),
        (
            "whole",
            lambda t: replace(
                t,
                evidence=replace(
                    t.evidence,
                    eligibility=replace(t.evidence.eligibility, fractional=False),
                    quantity_step=D("1"),
                ),
            ),
        ),
        ("liquidity", lambda t: replace(t, available_units=D(0))),
    ]
    for name, change in changes:
        data = small()
        altered = replace(data, ticks=tuple(change(t) for t in data.ticks))
        assert not fills(Backtest(altered, plan()).run(tmp_path / name))


def test_earnings_blackout(tmp_path: Path) -> None:
    data = small()
    ticks = tuple(
        replace(
            t,
            evidence=replace(
                t.evidence,
                earnings=replace(
                    t.evidence.earnings, announcements=(data.start + timedelta(hours=2),)
                ),
            ),
        )
        for t in data.ticks
    )
    result = Backtest(replace(data, ticks=ticks), plan()).run(tmp_path / "run")
    assert not fills(result)
    assert any("EARNINGS_BLACKOUT" in e.get("reasons", ()) for e in result.events)


def test_cost_and_slippage_sensitivity(tmp_path: Path) -> None:
    base = Backtest(small(), plan()).run(tmp_path / "base")
    costly = Backtest(
        small(), plan(commission_fraction=D(".001"), slippage_fraction=D(".001"))
    ).run(tmp_path / "cost")
    assert costly.metrics["trading_costs_usd"] > base.metrics["trading_costs_usd"]
    assert D(str(fills(costly)[0]["price"])) > D(str(fills(base)[0]["price"]))


def test_volatility_sensitivity_blocks_unsafe_signal(tmp_path: Path) -> None:
    data = small()
    bars = list(data.history)
    for i in range(35, 60):
        price = 60.0 if i % 2 else 160.0
        bars[i] = replace(
            bars[i],
            candle=replace(
                bars[i].candle, open=price, close=price, low=price - 0.2, high=price + 0.2
            ),
        )
    # Scanner's independent volatility screen fails closed rather than treating stress as a signal.
    result = Backtest(replace(data, history=tuple(bars)), plan()).run(tmp_path / "stress")
    assert not fills(result)
    assert any(e.get("reason") == "VOLATILITY_LIMIT" for e in result.events)


def test_reproducible_reports_and_no_overwrite(tmp_path: Path) -> None:
    first = Backtest(small(), plan()).run(tmp_path / "a")
    second = Backtest(small(), plan()).run(tmp_path / "b")
    write_report(first, tmp_path / "a-report")
    write_report(second, tmp_path / "b-report")
    for path in (tmp_path / "a-report").iterdir():
        assert path.read_bytes() == (tmp_path / "b-report" / path.name).read_bytes()
    report = json.loads((tmp_path / "a-report/report.json").read_text())
    assert report["manifest"]["provenance"]["kind"] == "synthetic"
    assert "never evidence of profitability" in (tmp_path / "a-report/report.md").read_text()
    with pytest.raises(FileExistsError):
        Backtest(small(), plan()).run(tmp_path / "a")


def test_metrics_known_path() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    points = [
        {"at": (start + timedelta(days=i)).isoformat(), "equity": str(v), "exposure": str(v / 2)}
        for i, v in enumerate([100, 110, 88, 105])
    ]
    result = metrics(points, [10, -5, 5], 2)
    assert result["total_return"] == pytest.approx(0.05)
    assert result["maximum_drawdown"] == pytest.approx(0.2)
    assert result["profit_factor"] == 3 and result["win_rate"] == pytest.approx(2 / 3)
    assert result["expectancy_usd"] == pytest.approx(10 / 3)
    assert result["time_weighted_exposure"] == 0.5
    assert result["annualized_return"] is None


def test_timezone_offsets_replay_identical_instants(tmp_path: Path) -> None:
    data = small()
    offset = timezone(timedelta(hours=-5))
    shifted = replace(data, ticks=tuple(replace(t, at=t.at.astimezone(offset)) for t in data.ticks))
    a = Backtest(data, plan()).run(tmp_path / "a")
    b = Backtest(shifted, plan()).run(tmp_path / "b")
    assert a.events == b.events and a.equity == b.equity


@pytest.mark.parametrize(
    "case",
    ["unordered", "future_quote", "future_evidence", "no_provenance", "stale_fx", "missing_end"],
)
def test_data_validation(case: str) -> None:
    data = small()
    if case == "unordered":
        data = replace(data, ticks=tuple(reversed(data.ticks)))
    if case == "future_quote":
        data = replace(
            data,
            ticks=(
                replace(
                    data.ticks[0],
                    quote=replace(
                        data.ticks[0].quote, observed_at=data.start + timedelta(seconds=1)
                    ),
                ),
            )
            + data.ticks[1:],
        )
    if case == "future_evidence":
        data = replace(
            data,
            ticks=(
                replace(
                    data.ticks[0],
                    evidence=replace(
                        data.ticks[0].evidence, available_at=data.start + timedelta(seconds=1)
                    ),
                ),
            )
            + data.ticks[1:],
        )
    if case == "no_provenance":
        data = replace(data, provenance=replace(data.provenance, kind="real"))
    if case == "stale_fx":
        data = replace(data, initial_fx_known_at=data.start - timedelta(days=1))
    if case == "missing_end":
        data = replace(data, end=data.end + timedelta(seconds=1))
    with pytest.raises(ValueError):
        data.validate()


def test_train_validation_final_test_selection(tmp_path: Path) -> None:
    data = synthetic_dataset(3)
    day = timedelta(days=1)
    split = Split(
        data.start, data.start + day, data.start + 2 * day, data.end + timedelta(seconds=1)
    )
    plans = (plan(), Plan(Rules(enabled=(Strategy.REVERSION,), style=Style.SWING), Simulation()))
    results = evaluate_split(data, plans, split, tmp_path / "split")
    assert results["train"].manifest["plan_digest"] == results["test"].manifest["plan_digest"]
    assert results["validation"].manifest["plan_digest"] == results["test"].manifest["plan_digest"]
    assert results["test"].manifest["evaluation_role"] == "test"
    assert all(
        datetime.fromisoformat(p["at"]) < split.validation_start for p in results["train"].equity
    )
    with pytest.raises(ValueError):
        walk_forward(data, plans, (split, split), tmp_path / "overlap")
    with pytest.raises(ValueError):
        window(data, data.start + timedelta(minutes=1), data.end)


def test_simulator_never_imports_broker_or_credentials() -> None:
    root = Path(__file__).parents[1] / "src/etoro_demo_bot/backtest"
    for file in root.glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not any(
                    x in (node.module or "").split(".")
                    for x in ("execution", "client", "config", "httpx", "socket")
                )


def test_fill_rechecks_newly_known_earnings(tmp_path: Path) -> None:
    data = small()
    ticks = list(data.ticks)
    t = ticks[1]
    ticks[1] = replace(
        t,
        evidence=replace(
            t.evidence,
            earnings=replace(t.evidence.earnings, announcements=(t.at + timedelta(hours=1),)),
        ),
    )
    result = Backtest(replace(data, ticks=tuple(ticks)), plan()).run(tmp_path / "run")
    assert not fills(result)


def test_archived_simulation_reservation_keeps_duplicate_protection(tmp_path: Path) -> None:
    from etoro_demo_bot.backtest.risk import SimulationRisk
    from etoro_demo_bot.risk import AccountSnapshot, Proposal

    now = small().start
    risk = SimulationRisk(tmp_path / "new.sqlite", killed=False)
    risk.store.establish_day(now.date(), D("550"))
    account = AccountSnapshot(
        "backtest-demo",
        D("550"),
        D("550"),
        (),
        now,
        demo=True,
        complete=True,
        cash_flows_reconciled=True,
    )
    p = Proposal("test", 1, D(".5"), D("100"), D("99"), now, D(".1"), underlying_verified=True)
    assert risk.evaluate(p, account, now=now).passed
    risk.retire(p.proposal_id)
    assert risk.evaluate(replace(p, proposal_id="other"), account, now=now).reasons == (
        "DUPLICATE_PROPOSAL",
    )
    with risk.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM simulated_tombstones").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        SimulationRisk(tmp_path / "new.sqlite", killed=False)


def test_overnight_baseline_precedes_gap_valuation(tmp_path: Path) -> None:
    data = synthetic_dataset(2)
    # Retain a position across an overnight gap with explicit session evidence.
    ticks: tuple[Tick, ...] = (data.ticks[0], data.ticks[1], data.ticks[48], data.ticks[49])
    ticks = ticks[:2] + tuple(
        replace(t, quote=replace(t.quote, bid=D("1"), ask=D("1.02"))) for t in ticks[2:]
    )
    result = Backtest(replace(data, ticks=ticks, end=ticks[-1].at), plan()).run(tmp_path / "run")
    baseline = next(e for e in result.events if e["kind"] == "daily_baseline")
    assert D(baseline["equity"]) > 500
    assert any(
        e["kind"] == "risk_halt" and "DAILY_LOSS_LIMIT" in e["reasons"] for e in result.events
    )


def test_daylight_offset_change_preserves_chronology(tmp_path: Path) -> None:
    data = small()
    ticks = tuple(
        replace(t, at=t.at.astimezone(timezone(timedelta(hours=-4 if i < 2 else -5))))
        for i, t in enumerate(data.ticks)
    )
    a = Backtest(data, plan()).run(tmp_path / "a")
    b = Backtest(replace(data, ticks=ticks), plan()).run(tmp_path / "b")
    assert a.events == b.events


def test_final_test_prices_cannot_change_training_selection(tmp_path: Path) -> None:
    data = synthetic_dataset(3)
    day = timedelta(days=1)
    split = Split(
        data.start, data.start + day, data.start + day * 2, data.end + timedelta(seconds=1)
    )
    plans = (plan(), Plan(Rules(enabled=(Strategy.REVERSION,), style=Style.SWING), Simulation()))
    a = evaluate_split(data, plans, split, tmp_path / "a")
    altered = replace(
        data,
        ticks=tuple(
            replace(t, quote=replace(t.quote, bid=D("70"), ask=D("70.02")))
            if t.at >= split.test_start
            else t
            for t in data.ticks
        ),
    )
    b = evaluate_split(altered, plans, split, tmp_path / "b")
    assert a["train"].events == b["train"].events
    assert a["test"].manifest["plan_digest"] == b["test"].manifest["plan_digest"]


def test_walk_forward_runs_disjoint_out_of_sample_windows(tmp_path: Path) -> None:
    data = synthetic_dataset(5)
    day = timedelta(days=1)
    splits = (
        Split(data.start, data.start + day, data.start + 2 * day, data.start + 3 * day),
        Split(
            data.start, data.start + 3 * day, data.start + 4 * day, data.end + timedelta(seconds=1)
        ),
    )
    results = walk_forward(data, (plan(),), splits, tmp_path / "walk")
    assert len(results) == 2
    assert results[0]["test"].equity[-1]["at"] < results[1]["test"].equity[0]["at"]


def test_mean_reversion_replay_uses_existing_strategy(tmp_path: Path) -> None:
    data = small()
    history = list(data.history)
    for i in range(60):
        price = 100.0 if i < 45 else 100 - (i - 45) * 0.15
        history[i] = replace(
            history[i],
            candle=replace(
                history[i].candle,
                open=price,
                close=price,
                low=price - 0.1,
                high=price + 0.1,
                volume=100,
            ),
        )
    ticks = tuple(
        replace(t, quote=replace(t.quote, bid=D("97.89"), ask=D("97.90"))) for t in data.ticks
    )
    result = Backtest(
        replace(data, history=tuple(history), ticks=ticks),
        Plan(Rules(enabled=(Strategy.REVERSION,), style=Style.SWING), Simulation()),
    ).run(tmp_path / "run")
    assert fills(result)
    proposed = next(e for e in result.decisions if e["status"] == "proposed")
    assert proposed["details"]["strategy"] == "mean_reversion"


def test_annualized_metrics_require_long_daily_sample() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    points = [
        {
            "at": (start + timedelta(days=i)).isoformat(),
            "equity": str(100 + i * 0.1 + (i % 2) * 0.01),
            "exposure": "50",
        }
        for i in range(367)
    ]
    result = metrics(points, [], 0)
    assert result["annualized_return"] is not None and result["sharpe_daily_365"] is not None
    assert result["profit_factor"] is None and result["win_rate"] is None


def test_repeated_old_quote_cannot_fill_a_new_intent(tmp_path: Path) -> None:
    data = small()
    ticks = list(data.ticks)
    ticks[1] = replace(ticks[1], quote=replace(ticks[1].quote, observed_at=data.start))
    result = Backtest(replace(data, ticks=tuple(ticks)), plan()).run(tmp_path / "run")
    assert not fills(result)


def test_unknown_closing_permission_retains_inventory(tmp_path: Path) -> None:
    data = small()
    ticks = tuple(replace(t, close_allowed=False) for t in data.ticks)
    result = Backtest(replace(data, ticks=ticks), plan()).run(tmp_path / "run")
    assert fills(result) and not result.trades
    assert D(result.manifest["open_units"]) > 0
