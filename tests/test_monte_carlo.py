"""Synthetic deterministic Monte Carlo tests. No sockets or credential access."""

import ast
import hashlib
import json
import os
import socket
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.monte_carlo.engine import MonteCarloAgent, Result, path_outcome, summarize
from etoro_demo_bot.monte_carlo.fixtures import synthetic_inputs
from etoro_demo_bot.monte_carlo.models import Block, Move, Pool, Settings, Trial
from etoro_demo_bot.monte_carlo.report import write_report
from etoro_demo_bot.risk import Exposure, RiskEngine, RiskPolicy, RiskStore
from etoro_demo_bot.scanner.analysis import ScoringRules
from etoro_demo_bot.scanner.indicators import calculate
from etoro_demo_bot.scanner.models import Candle
from etoro_demo_bot.strategy import (
    Context,
    Journal,
    ObservedBar,
    Rules,
    Strategy,
    StrategyEngine,
    Style,
)
from etoro_demo_bot.strategy.journal import digest
from etoro_demo_bot.strategy.models import Candidate


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Monte Carlo must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    # Remove all real process values from test code's view.
    monkeypatch.setattr(os, "environ", {})


def engines(
    path: Path,
    c: Context,
    *,
    killed: bool = False,
    baseline: D | None = None,
    rules: Rules | None = None,
    policy: RiskPolicy | None = None,
) -> tuple[StrategyEngine, RiskEngine]:
    path.mkdir()
    store = RiskStore.initialize(path / "risk.sqlite", c.account.account_id)
    store.establish_day(c.account.observed_at.date(), baseline or c.account.equity)
    if not killed:
        store.set_kill_switch(False, acknowledged=True)
    return (
        StrategyEngine(
            Journal.initialize(path / "strategy.sqlite"), rules or Rules(take_profit_r=D(2))
        ),
        RiskEngine(store, policy),
    )


def run(path: Path, eur: int = 500, seed: int = 19) -> Result:
    c, pool = synthetic_inputs(eur)
    strategy, risk = engines(path, c)
    return MonteCarloAgent().run(
        c, pool, strategy, risk, now=c.account.observed_at, settings=Settings(seed)
    )


@pytest.mark.parametrize("eur", [500, 1000])
def test_ten_thousand_reproducible_and_one_reservation(tmp_path: Path, eur: int) -> None:
    first, second = run(tmp_path / "first", eur), run(tmp_path / "second", eur)
    assert first == second and first.status == "simulated"
    assert len(first.trials) == 10000 and not first.execution_authorized
    assert sum(first.metrics["outcomes"].values()) == 10000
    assert all(first.metrics["outcomes"][k] > 0 for k in ("gap_stop", "target", "stop", "horizon"))
    store = RiskStore(tmp_path / "first" / "risk.sqlite")
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 1
    assert first.manifest["risk_decision"]["execution_authorized"] is False
    assert first.metrics["exceeds_planned_risk_frequency"] > 0


def test_seed_changes_draws_not_model_and_decimal_context_isolated(tmp_path: Path) -> None:
    a = run(tmp_path / "a")
    b = run(tmp_path / "b", seed=20)
    assert a.trials != b.trials and a.inputs_digest != b.inputs_digest
    with localcontext() as ctx:
        ctx.prec = 10
        low_precision = run(tmp_path / "low")
    assert a == low_precision


@pytest.mark.parametrize(
    "reason",
    ["kill", "daily", "cash", "exposure", "stale", "real", "missing_state", "position_limit"],
)
def test_fail_closed_risk_and_strategy(tmp_path: Path, reason: str) -> None:
    c, pool = synthetic_inputs()
    baseline = D(600) if reason == "daily" else None
    if reason == "cash":
        c = replace(c, account=replace(c.account, available_balance=D(0)))
    elif reason == "exposure":
        c = replace(c, account=replace(c.account, exposures=(Exposure(1, D(140), 1),)))
    elif reason == "stale":
        c = replace(
            c, account=replace(c.account, observed_at=c.account.observed_at - timedelta(days=1))
        )
    elif reason == "real":
        c = replace(c, account=replace(c.account, demo=False))
    policy = RiskPolicy(max_position_fraction=D(".01")) if reason == "position_limit" else None
    s, r = engines(tmp_path / "state", c, killed=reason == "kill", baseline=baseline, policy=policy)
    if reason == "missing_state":
        r.store.path.unlink()
    result = MonteCarloAgent().run(c, pool, s, r, now=c.opportunity.created_at)
    assert result.status == "blocked" and not result.trials
    if reason == "kill":
        assert "KILL_SWITCH_ACTIVE" in result.reasons
    if reason == "daily":
        assert "DAILY_LOSS_LIMIT" in result.reasons


def test_restart_duplicate_and_kill_persist(tmp_path: Path) -> None:
    c, pool = synthetic_inputs()
    s, r = engines(tmp_path / "state", c)
    agent = MonteCarloAgent()
    result = agent.run(c, pool, s, r, now=c.account.observed_at)
    assert result.status == "simulated"
    s2 = StrategyEngine(Journal(s.journal.path), s.rules)
    r2 = RiskEngine(RiskStore(r.store.path))
    assert agent.run(c, pool, s2, r2, now=c.account.observed_at).status == "blocked"
    r2.store.set_kill_switch(True)
    # A new strategy journal must still respect the persistent kill switch.
    s3 = StrategyEngine(Journal.initialize(tmp_path / "new-strategy.sqlite"), s.rules)
    rejected = agent.run(c, pool, s3, r2, now=c.account.observed_at)
    assert "KILL_SWITCH_ACTIVE" in rejected.reasons


def candidate(tmp_path: Path) -> tuple[Context, Candidate]:
    c, _ = synthetic_inputs()
    s, _ = engines(tmp_path / "state", c)
    value = s.propose(c, now=c.account.observed_at).candidate
    assert value is not None
    # Pure arithmetic fixture; never used as a substitute for risk review in agent.run.
    c = replace(
        c,
        opportunity=replace(
            c.opportunity, quote=replace(c.opportunity.quote, bid=D(100), ask=D(100))
        ),
        evidence=replace(
            c.evidence,
            budget=replace(
                c.evidence.budget,
                round_trip_fixed_usd=D(0),
                round_trip_fee_fraction=D(0),
                slippage_fraction=D(0),
                conversion_cost_fraction=D(0),
            ),
        ),
    )
    return c, replace(
        value,
        proposal=replace(value.proposal, price=D(100), units=D(1), stop_loss=D(95)),
        take_profit=D(110),
    )


@pytest.mark.parametrize(
    ("move", "outcome", "pnl"),
    [
        (("1", "1.12", ".94", "1.01"), "stop", "-5"),
        ((".80", ".90", ".79", ".85"), "gap_stop", "-20"),
        (("1.20", "1.21", ".90", "1.00"), "target", "10"),
        (("1", "1.10", ".99", "1.05"), "target", "10"),
        (("1", "1.04", ".99", "1.03"), "horizon", "3"),
    ],
)
def test_bar_ordering_gaps_and_analytic_pnl(
    tmp_path: Path,
    move: tuple[str, ...],
    outcome: str,
    pnl: str,
) -> None:
    c, item = candidate(tmp_path)
    b = Block(
        c.account.observed_at,
        c.account.observed_at,
        c.account.observed_at,
        (Move(*(D(v) for v in move)),),
    )
    result = path_outcome(item, b, c, 0, 0)
    assert result.outcome == outcome and result.pnl_usd == D(pnl)
    assert result.costs_usd == 0 and result.exit_step == 1


def test_no_target_and_explicit_cost_fx_attribution(tmp_path: Path) -> None:
    c, item = candidate(tmp_path)
    now = c.account.observed_at
    flat = Block(now, now, now, (Move(D(1), D(1), D(1), D(1)),))
    c = replace(
        c,
        evidence=replace(
            c.evidence,
            budget=replace(
                c.evidence.budget,
                slippage_fraction=D(".02"),
                round_trip_fixed_usd=D(1),
                conversion_cost_fraction=D(".01"),
            ),
        ),
    )
    result = path_outcome(replace(item, take_profit=None), flat, c, 0, 0)
    assert result.pnl_usd == -3  # entry 101, exit 99, fixed fee 1
    assert result.costs_usd == 3
    assert result.portfolio_pnl_eur == (D(-3) - D("5.5")) / D("1.1")
    assert result.outcome == "horizon"


def test_exact_tail_metrics() -> None:
    trials = tuple(
        Trial(i, 0, "stop", 1, D(1), D(-10 if i < 100 else 1), D(0), D(0)) for i in range(10000)
    )
    metrics = summarize(trials)
    assert metrics["var99_usd"] == 10
    assert metrics["expected_shortfall99_usd"] == 10
    assert metrics["expected_shortfall95_usd"] == D("1.2")
    assert metrics["expected_pnl_usd"] == D(".89")


def repool(pool: Pool, blocks: tuple[Block, ...]) -> Pool:
    return replace(pool, blocks=blocks, source_sha256=digest([asdict(b) for b in blocks]))


@pytest.mark.parametrize(
    "bad",
    [
        "future",
        "naive",
        "overlap",
        "ratio",
        "nan",
        "checksum",
        "historical",
        "short",
        "instrument",
        "horizon",
    ],
)
def test_pool_validation_before_strategy_state(tmp_path: Path, bad: str) -> None:
    c, pool = synthetic_inputs()
    first = pool.blocks[0]
    if bad == "future":
        first = replace(first, known_at=c.account.observed_at + timedelta(seconds=1))
    elif bad == "naive":
        first = replace(first, start=first.start.replace(tzinfo=None))
    elif bad == "overlap":
        first = pool.blocks[1]
    elif bad in ("ratio", "nan"):
        first = replace(
            first, moves=(Move(D(1), D(".9") if bad == "ratio" else D("NaN"), D(".8"), D(1)),)
        )
    pool = repool(pool, (first,) + pool.blocks[1:])
    if bad == "checksum":
        pool = replace(pool, source_sha256="0" * 64)
    elif bad == "historical":
        pool = replace(pool, classification="historical_verified")
    elif bad == "short":
        pool = repool(pool, pool.blocks[:19])
    elif bad == "instrument":
        pool = replace(pool, instrument_id=999)
    elif bad == "horizon":
        pool = replace(pool, horizon_seconds=0)
    s, r = engines(tmp_path / "state", c)
    with pytest.raises(ValueError):
        MonteCarloAgent().run(c, pool, s, r, now=c.account.observed_at)
    with r.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 0


@pytest.mark.parametrize("strategy", list(Strategy))
def test_all_strategy_interfaces(tmp_path: Path, strategy: Strategy) -> None:
    c, pool = synthetic_inputs()
    if strategy == Strategy.REVERSION:
        prices = (100.0,) * 45 + tuple(100 - i * 0.15 for i in range(15))
        bars = tuple(
            Candle(c.account.observed_at - timedelta(hours=61 - i), v, v + 0.1, v - 0.1, v, 100)
            for i, v in enumerate(prices)
        )
        f = calculate(bars)
        parts = ScoringRules().rank(f)
        q = replace(c.opportunity.quote, bid=D("97.89"), ask=D("97.90"))
        c = replace(
            c,
            opportunity=replace(
                c.opportunity,
                features=f,
                score=sum(v for _, v in parts),
                contributions=parts,
                quote=q,
            ),
            bars=tuple(ObservedBar(b, b.start + timedelta(hours=1)) for b in bars),
        )
    s, r = engines(
        tmp_path / "state",
        c,
        rules=Rules(style=Style.SWING, enabled=(strategy,), take_profit_r=D(2)),
    )
    result = MonteCarloAgent().run(c, pool, s, r, now=c.account.observed_at)
    assert result.status == "simulated"
    assert result.manifest["candidate"]["strategy"] == strategy


def test_report_reproducible_checksums_no_overwrite(tmp_path: Path) -> None:
    result = run(tmp_path / "state")
    for directory in ("a", "b"):
        write_report(result, tmp_path / directory)
    for file in (tmp_path / "a").iterdir():
        assert file.read_bytes() == (tmp_path / "b" / file.name).read_bytes()
    hashes = json.loads((tmp_path / "a" / "checksums.json").read_text())
    for name, expected in hashes.items():
        assert hashlib.sha256((tmp_path / "a" / name).read_bytes()).hexdigest() == expected
    assert "SYNTHETIC" in (tmp_path / "a" / "report.md").read_text()
    with pytest.raises(FileExistsError):
        write_report(result, tmp_path / "a")


@pytest.mark.parametrize(
    "settings", [{"trials": 9999}, {"trials": True}, {"seed": -1}, {"seed": True}, {"seed": 2**64}]
)
def test_settings_fail_closed(settings: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Settings(**settings)


def test_no_network_execution_or_credentials_imports() -> None:
    root = Path(__file__).parents[1] / "src" / "etoro_demo_bot" / "monte_carlo"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert not any(
                part in name.split(".")
                for name in modules
                for part in ("execution", "client", "config", "httpx", "requests", "os", "socket")
            )


def test_spread_fees_are_deducted_once(tmp_path: Path) -> None:
    c, item = candidate(tmp_path)
    c = replace(
        c,
        opportunity=replace(
            c.opportunity, quote=replace(c.opportunity.quote, bid=D(99), ask=D(100))
        ),
        evidence=replace(
            c.evidence, budget=replace(c.evidence.budget, round_trip_fee_fraction=D(".01"))
        ),
    )
    now = c.account.observed_at
    b = Block(now, now, now, (Move(D(1), D(1), D(1), D(1)),))
    with localcontext() as ctx:
        ctx.prec = 60
        result = path_outcome(item, b, c, 0, 0)
    assert abs(result.exit_price - 99) < D("1e-50")
    assert abs(result.pnl_usd - D("-1.995")) < D("1e-50")
    assert abs(result.costs_usd - D("1.995")) < D("1e-50")


def test_intraday_horizon_blocked_without_reservation(tmp_path: Path) -> None:
    c, pool = synthetic_inputs()
    c = replace(
        c, evidence=replace(c.evidence, session_close=c.account.observed_at + timedelta(hours=2))
    )
    s, r = engines(tmp_path / "state", c)
    result = MonteCarloAgent().run(c, pool, s, r, now=c.account.observed_at)
    assert result.reasons == ("HORIZON_EXCEEDS_EXIT_DEADLINE",)
    with r.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 0


def test_risk_ceiling_preserved(tmp_path: Path) -> None:
    c, pool = synthetic_inputs()
    s, r = engines(tmp_path / "state", c, rules=Rules(risk_fraction=D(".01")))
    result = MonteCarloAgent().run(c, pool, s, r, now=c.account.observed_at)
    assert result.status == "simulated"
    assert result.manifest["risk_decision"]["risk_amount"] <= c.account.equity * D(".01")
    assert result.manifest["candidate"]["proposal"]["leverage"] == 1
    assert result.manifest["candidate"]["take_profit"] is None
