"""Deterministic, offline entry/exit, journal and real RiskEngine integration tests."""

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.risk import AccountSnapshot, RiskEngine, RiskStore
from etoro_demo_bot.scanner.analysis import Budget, ScoringRules
from etoro_demo_bot.scanner.indicators import calculate
from etoro_demo_bot.scanner.models import (
    Candle,
    Eligibility,
    Instrument,
    Opportunity,
    ProductEvidence,
    Quote,
    SessionEvidence,
)
from etoro_demo_bot.strategy import (
    Context,
    EarningsWindow,
    Evidence,
    ExitMonitor,
    Journal,
    ObservedBar,
    Position,
    Rules,
    Strategy,
    StrategyEngine,
    StrategyError,
    Style,
)
from etoro_demo_bot.strategy.rules import matches

NOW = datetime(2026, 10, 27, 15, 30, tzinfo=UTC)


def context(eur: str = "500") -> Context:
    bars = tuple(
        Candle(
            NOW - timedelta(hours=61 - i),
            100 + i * i * 0.01,
            100 + i * i * 0.01 + 0.2,
            100 + i * i * 0.01 - 0.2,
            100 + i * i * 0.01,
            300 if i == 59 else 100,
        )
        for i in range(60)
    )
    features = calculate(bars)
    parts = ScoringRules().rank(features)
    quote = Quote(1, D("134.80"), D("134.81"), NOW, "realtime")
    opportunity = Opportunity(
        Instrument(1, "SYNTH", "Stocks", 1),
        sum(p[1] for p in parts),
        parts,
        features,
        quote,
        NOW,
        NOW + timedelta(seconds=60),
        D("10"),
        D("550"),
    )
    budget = Budget(
        D(eur), D("1.1"), NOW, "synthetic-fx", D(".001"), D(".01"), D(".001"), D(".001")
    )
    evidence = Evidence(
        Eligibility(1, D("10"), D("10000"), True, NOW, True),
        ProductEvidence(1, "USD", True, True, "synthetic", NOW + timedelta(days=1)),
        SessionEvidence(1, True, NOW, NOW + timedelta(hours=1), "synthetic-calendar"),
        budget,
        NOW,
        NOW + timedelta(hours=5),
        D("10000000"),
        NOW,
        D(".001"),
        True,
        EarningsWindow(
            1, NOW, NOW - timedelta(days=1), NOW + timedelta(days=7), (), "synthetic", True
        ),
    )
    equity = D(eur) * D("1.1")
    account = AccountSnapshot(
        "synthetic-demo",
        equity,
        equity,
        (),
        NOW,
        demo=True,
        complete=True,
        cash_flows_reconciled=True,
    )
    return Context(
        opportunity,
        tuple(ObservedBar(b, b.start + timedelta(hours=1)) for b in bars),
        evidence,
        account,
    )


def engine(tmp_path: Path, rules: Rules | None = None) -> StrategyEngine:
    return StrategyEngine(Journal.initialize(tmp_path / "strategy.sqlite"), rules)


def candidate(tmp_path: Path, rules: Rules | None = None) -> tuple[StrategyEngine, Context, Any]:
    eng = engine(tmp_path, rules)
    c = context()
    result = eng.propose(c, now=NOW)
    assert result.candidate is not None, result
    return eng, c, result.candidate


@pytest.mark.parametrize("eur", ["500", "1000"])
@pytest.mark.parametrize("style", list(Style))
def test_small_portfolio_and_risk_handoff(tmp_path: Path, eur: str, style: Style) -> None:
    c = context(eur)
    eng = engine(tmp_path, Rules(style=style))
    result = eng.propose(c, now=NOW)
    assert result.status == "proposed" and result.candidate is not None
    item = result.candidate
    p = item.proposal
    assert item.strategy == Strategy.BREAKOUT and item.take_profit is None
    assert not item.execution_authorized and p.leverage == 1
    assert p.price is not None and p.stop_loss is not None
    assert p.units * p.price >= c.evidence.eligibility.minimum_usd
    assert p.units * (p.price - p.stop_loss) + p.cost_buffer <= c.account.equity * D(".01")
    store = RiskStore.initialize(tmp_path / "risk.sqlite", c.account.account_id)
    store.establish_day(NOW.date(), c.account.equity)
    store.set_kill_switch(False, acknowledged=True)
    review = eng.review(item, c.account, RiskEngine(store), now=NOW)
    assert review.decision.passed and not review.execution_authorized
    assert not eng.review(item, c.account, RiskEngine(store), now=NOW).decision.passed
    assert [e["status"] for e in eng.journal.events()] == [
        "proposed",
        "risk_review_started",
        "risk_pass",
    ]


@pytest.mark.parametrize("failure", ["kill", "daily", "balance", "positions"])
def test_existing_risk_limits_not_bypassed(tmp_path: Path, failure: str) -> None:
    eng, c, item = candidate(tmp_path)
    store = RiskStore.initialize(tmp_path / "risk.sqlite", c.account.account_id)
    store.establish_day(NOW.date(), c.account.equity)
    if failure != "kill":
        store.set_kill_switch(False, acknowledged=True)
    account = c.account
    if failure == "daily":
        account = replace(account, equity=account.equity * D(".97"))
    if failure == "balance":
        account = replace(account, available_balance=D("0"))
    if failure == "positions":
        from etoro_demo_bot.risk import Exposure

        account = replace(account, exposures=(Exposure(2, D("100"), 5),))
    result = eng.review(item, account, RiskEngine(store), now=NOW)
    assert not result.decision.passed
    assert eng.journal.events()[-1]["status"] == "risk_rejected"


def test_three_entry_rules() -> None:
    f = context().opportunity.features
    assert matches(f, Rules()) == (Strategy.BREAKOUT, Strategy.TREND)
    assert matches(f, Rules(enabled=(Strategy.TREND,))) == (Strategy.TREND,)
    reversion = replace(f, ema=100, sma=101, momentum=-0.01, rsi=20, close=95, atr=1)
    assert matches(reversion, Rules()) == (Strategy.REVERSION,)
    assert matches(replace(reversion, momentum=-0.1), Rules()) == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_fraction", D(".011")),
        ("allocation_fraction", D("2")),
        ("stop_atr", D("NaN")),
        ("signal_ttl_seconds", 61),
        ("enabled", ()),
        ("take_profit_r", D("0")),
        ("version", "bad\nversion"),
        ("style", "live"),
    ],
)
def test_invalid_rules(field: str, value: Any) -> None:
    with pytest.raises(StrategyError):
        Rules(**{field: value})


@pytest.mark.parametrize(
    "case",
    [
        "expiry",
        "future_signal",
        "future_quote",
        "delayed",
        "stale_quote",
        "spread",
        "closed",
        "future_evidence",
        "liquidity",
        "future_liquidity",
        "fraction_step",
        "minimum",
        "currency",
        "leverage",
        "earnings_unknown",
        "earnings_future",
        "earnings_event",
        "fx_future",
        "costs",
        "score",
        "conflict",
    ],
)
def test_entry_safety_failures(tmp_path: Path, case: str) -> None:
    c = context()
    o, e = c.opportunity, c.evidence
    if case == "expiry":
        o = replace(o, expires_at=NOW)
    if case == "future_signal":
        o = replace(o, created_at=NOW + timedelta(seconds=1))
    if case == "future_quote":
        o = replace(o, quote=replace(o.quote, observed_at=NOW + timedelta(seconds=1)))
    if case == "delayed":
        o = replace(o, quote=replace(o.quote, quote_type="delayed"))
    if case == "stale_quote":
        o = replace(o, quote=replace(o.quote, observed_at=NOW - timedelta(seconds=61)))
    if case == "spread":
        o = replace(o, quote=replace(o.quote, bid=D("100")))
    if case == "closed":
        e = replace(e, session=replace(e.session, is_open=False))
    if case == "future_evidence":
        e = replace(e, available_at=NOW + timedelta(seconds=1))
    if case == "liquidity":
        e = replace(e, daily_dollar_volume=D("1"))
    if case == "future_liquidity":
        e = replace(e, liquidity_observed_at=NOW + timedelta(seconds=1))
    if case == "fraction_step":
        e = replace(e, quantity_step_verified=False)
    if case == "minimum":
        e = replace(e, eligibility=replace(e.eligibility, minimum_usd=D("1000")))
    if case == "currency":
        e = replace(e, product=replace(e.product, currency="EUR"))
    if case == "leverage":
        e = replace(e, product=replace(e.product, unleveraged=False))
    if case == "earnings_unknown":
        e = replace(e, earnings=replace(e.earnings, complete=False))
    if case == "earnings_future":
        e = replace(e, earnings=replace(e.earnings, known_at=NOW + timedelta(seconds=1)))
    if case == "earnings_event":
        e = replace(e, earnings=replace(e.earnings, announcements=(NOW + timedelta(hours=1),)))
    if case == "fx_future":
        e = replace(e, budget=replace(e.budget, fx_observed_at=NOW + timedelta(seconds=1)))
    if case == "costs":
        e = replace(e, budget=replace(e.budget, round_trip_fixed_usd=D("100")))
    if case == "score":
        o = replace(o, score=1)
    if case == "conflict":
        o = replace(
            o, score=50, contributions=(("momentum_breakout", 35), ("potential_mean_reversion", 15))
        )
    eng = engine(tmp_path)
    result = eng.propose(replace(c, opportunity=o, evidence=e), now=NOW)
    assert result.status == "rejected" and result.candidate is None
    assert eng.journal.events()[-1]["status"] == "rejected"


def test_no_lookahead_future_bars_do_not_change_decision(tmp_path: Path) -> None:
    c = context()
    eng = engine(tmp_path)
    future = ObservedBar(Candle(NOW, 500, 900, 100, 800, 1000000), NOW + timedelta(hours=1))
    result = eng.propose(replace(c, bars=c.bars + (future,)), now=NOW)
    assert result.candidate is not None
    # Compare independent fresh state: decision and sizing cannot depend on future bars.
    other = tmp_path / "other"
    other.mkdir()
    assert result == engine(other).propose(c, now=NOW)


def test_revision_available_later_cannot_influence_features(tmp_path: Path) -> None:
    c = context()
    data = c.bars[:-1] + (replace(c.bars[-1], available_at=NOW + timedelta(seconds=1)),)
    result = engine(tmp_path).propose(replace(c, bars=data), now=NOW)
    assert result.reasons == ("FEATURE_PROVENANCE_MISMATCH",)


def test_pre_completion_availability_rejected(tmp_path: Path) -> None:
    c = context()
    data = (replace(c.bars[0], available_at=c.bars[0].candle.start),) + c.bars[1:]
    assert engine(tmp_path).propose(replace(c, bars=data), now=NOW).reasons == (
        "BAR_AVAILABLE_BEFORE_COMPLETION",
    )


def test_duplicate_restart_and_rule_change(tmp_path: Path) -> None:
    eng, c, item = candidate(tmp_path)
    restarted = StrategyEngine(
        Journal(tmp_path / "strategy.sqlite"), Rules(version="v2", style=Style.SWING)
    )
    assert restarted.propose(c, now=NOW).reasons == ("DUPLICATE_SIGNAL",)
    changed = replace(c, opportunity=replace(c.opportunity, created_at=NOW + timedelta(seconds=1)))
    assert restarted.propose(changed, now=NOW + timedelta(seconds=1)).reasons == (
        "DUPLICATE_SIGNAL",
    )
    assert item.proposal.proposal_id


def test_concurrent_proposals_one_claim(tmp_path: Path) -> None:
    eng = engine(tmp_path)
    c = context()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: eng.propose(c, now=NOW), range(2)))
    assert sorted(r.status for r in results) == ["proposed", "rejected"]


def test_journal_missing_fail_closed(tmp_path: Path) -> None:
    eng = StrategyEngine(Journal(tmp_path / "missing.sqlite"))
    assert eng.propose(context(), now=NOW).reasons == ("JOURNAL_UNAVAILABLE",)
    assert not (tmp_path / "missing.sqlite").exists()


def test_missed_opportunity_recorded(tmp_path: Path) -> None:
    eng = engine(tmp_path, Rules(minimum_relative_volume=D("100")))
    result = eng.propose(context(), now=NOW)
    assert result.status == "missed" and result.reasons == ("NO_ENTRY_SETUP",)
    assert eng.journal.events()[0]["status"] == "missed"


def test_low_decimal_context_does_not_change_sizing(tmp_path: Path) -> None:
    eng, c, item = candidate(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with localcontext() as ctx:
        ctx.prec = 3
        result = engine(other).propose(c, now=NOW)
    assert result.candidate == item


def test_review_changed_expired_or_unjournaled_blocked(tmp_path: Path) -> None:
    eng, c, item = candidate(tmp_path)
    store = RiskStore.initialize(tmp_path / "risk.sqlite", c.account.account_id)
    risk = RiskEngine(store)
    for altered in (
        replace(item, expires_at=NOW),
        replace(item, proposal=replace(item.proposal, units=D("100"))),
    ):
        assert not eng.review(altered, c.account, risk, now=NOW).decision.passed
    assert eng.journal.events()[-1]["status"] == "proposed"


def position(item: Any) -> Position:
    return Position(
        "position-1",
        item,
        NOW,
        NOW,
        item.proposal.units,
        item.proposal.price,
        item.proposal.stop_loss,
        item.proposal.price,
        NOW,
        True,
        NOW,
    )


def test_swing_winner_runs_and_stop_ratchets(tmp_path: Path) -> None:
    eng, c, item = candidate(tmp_path, Rules(style=Style.SWING))
    monitor = ExitMonitor(eng.journal)
    q = replace(c.opportunity.quote, bid=D("200"), ask=D("200.01"))
    result = monitor.evaluate(position(item), q, c.bars, c.evidence, now=NOW)
    assert result.action == "hold" and not result.execution_authorized
    assert result.proposed_stop is not None and result.proposed_stop > item.proposal.stop_loss
    assert item.exit_deadline is None and item.take_profit is None


@pytest.mark.parametrize(
    "case,reason",
    [
        ("stop", "STOP_LOSS"),
        ("risk", "RISK_REVIEW_REQUIRED"),
        ("earnings", "EARNINGS_BLACKOUT"),
        ("target", "CONFIGURED_TAKE_PROFIT"),
        ("trend", "TREND_INVALIDATED"),
        ("trailing", "TRAILING_STOP"),
    ],
)
def test_exit_rules(tmp_path: Path, case: str, reason: str) -> None:
    rules = Rules(style=Style.SWING, take_profit_r=D("2") if case == "target" else None)
    eng, c, item = candidate(tmp_path, rules)
    p = position(item)
    q = c.opportunity.quote
    e = c.evidence
    if case == "stop":
        q = replace(q, bid=D("100"))
    if case == "risk":
        p = replace(p, risk_valid=False)
    if case == "earnings":
        e = replace(e, earnings=replace(e.earnings, announcements=(NOW + timedelta(days=1),)))
    if case == "target":
        q = replace(q, bid=D("200"), ask=D("200.01"))
    if case == "trend":
        p = replace(
            p,
            active_stop=D("90"),
            candidate=replace(item, proposal=replace(item.proposal, stop_loss=D("90"))),
        )
        q = replace(q, bid=D("120"))
        p = replace(p, candidate=replace(p.candidate, rules=replace(rules, trailing_atr=None)))
    if case == "trailing":
        p = replace(p, peak_bid=D("200"))
    advice = ExitMonitor(eng.journal).evaluate(p, q, c.bars, e, now=NOW)
    assert advice.action == "propose_close" and advice.reasons == (reason,)


@pytest.mark.parametrize(
    "case", ["closed", "stale", "future_peak", "unknown_earnings", "weaken_stop"]
)
def test_exit_unknown_inputs_block_hold(tmp_path: Path, case: str) -> None:
    eng, c, item = candidate(tmp_path)
    p = position(item)
    q = c.opportunity.quote
    e = c.evidence
    if case == "closed":
        e = replace(e, session=replace(e.session, is_open=False))
    if case == "stale":
        q = replace(q, observed_at=NOW - timedelta(seconds=61))
    if case == "future_peak":
        p = replace(p, peak_observed_at=NOW + timedelta(seconds=1))
    if case == "unknown_earnings":
        e = replace(e, earnings=replace(e.earnings, complete=False))
    if case == "weaken_stop":
        p = replace(p, active_stop=D("1"))
    assert ExitMonitor(eng.journal).evaluate(p, q, c.bars, e, now=NOW).action == "blocked"


def test_no_execution_or_network_imports() -> None:
    root = Path(__file__).parents[1] / "src/etoro_demo_bot/strategy"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not any(
                    x in (node.module or "").split(".")
                    for x in ("execution", "client", "config", "httpx", "socket", "os")
                )
            if isinstance(node, ast.Import):
                assert not any(
                    x.name in ("httpx", "socket", "os", "subprocess", "importlib")
                    for x in node.names
                )


@pytest.mark.parametrize("eur,expected", [("500", "rejected"), ("1000", "proposed")])
def test_whole_share_affordability(tmp_path: Path, eur: str, expected: str) -> None:
    c = context(eur)
    e = replace(
        c.evidence,
        eligibility=replace(c.evidence.eligibility, fractional=False),
        quantity_step=D("1"),
    )
    result = engine(tmp_path).propose(replace(c, evidence=e), now=NOW)
    assert result.status == expected
    if result.candidate:
        assert (
            result.candidate.proposal.units == result.candidate.proposal.units.to_integral_value()
        )


def test_trend_only_candidate(tmp_path: Path) -> None:
    result = engine(tmp_path, Rules(enabled=(Strategy.TREND,))).propose(context(), now=NOW)
    assert result.candidate is not None and result.candidate.strategy == Strategy.TREND


def test_mean_reversion_integration(tmp_path: Path) -> None:
    c = context()
    # A shallow recent decline in a flat range, not a strong downtrend.
    prices = (100.0,) * 45 + tuple(100 - i * 0.15 for i in range(15))
    bars = tuple(
        Candle(NOW - timedelta(hours=61 - i), v, v + 0.1, v - 0.1, v, 100)
        for i, v in enumerate(prices)
    )
    f = calculate(bars)
    parts = ScoringRules().rank(f)
    q = replace(c.opportunity.quote, bid=D("97.89"), ask=D("97.90"))
    o = replace(
        c.opportunity, features=f, score=sum(v for _, v in parts), contributions=parts, quote=q
    )
    c = replace(
        c, opportunity=o, bars=tuple(ObservedBar(b, b.start + timedelta(hours=1)) for b in bars)
    )
    eng = engine(tmp_path, Rules(style=Style.SWING, enabled=(Strategy.REVERSION,)))
    result = eng.propose(c, now=NOW)
    assert result.candidate is not None and result.candidate.strategy == Strategy.REVERSION
    item = result.candidate
    advice = ExitMonitor(eng.journal).evaluate(
        position(item), replace(q, bid=D("101"), ask=D("101.01")), c.bars, c.evidence, now=NOW
    )
    assert advice.reasons == ("MEAN_REVERSION_COMPLETE",)


def test_intraday_exit_and_late_entry(tmp_path: Path) -> None:
    eng, c, item = candidate(tmp_path)
    assert item.exit_deadline is not None
    now = item.exit_deadline
    q = replace(c.opportunity.quote, observed_at=now)
    e = replace(
        c.evidence,
        available_at=now,
        session=replace(c.evidence.session, observed_at=now, valid_until=now + timedelta(hours=1)),
    )
    p = replace(position(item), observed_at=now, risk_observed_at=now)
    assert ExitMonitor(eng.journal).evaluate(p, q, c.bars, e, now=now).reasons == (
        "INTRADAY_SESSION_EXIT",
    )
    other = tmp_path / "late"
    other.mkdir()
    late = replace(c, evidence=replace(c.evidence, session_close=NOW + timedelta(minutes=10)))
    assert engine(other).propose(late, now=NOW).reasons == ("TOO_LATE_FOR_INTRADAY_ENTRY",)


def test_risk_commit_then_journal_failure_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    eng, c, item = candidate(tmp_path)
    store = RiskStore.initialize(tmp_path / "risk.sqlite", c.account.account_id)
    store.establish_day(NOW.date(), c.account.equity)
    store.set_kill_switch(False, acknowledged=True)
    risk = RiskEngine(store)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("synthetic write failure")

    monkeypatch.setattr(eng.journal, "finish_review", fail)
    assert not eng.review(item, c.account, risk, now=NOW).decision.passed
    restarted = StrategyEngine(Journal(tmp_path / "strategy.sqlite"))
    assert not restarted.review(item, c.account, risk, now=NOW).decision.passed
    assert "DUPLICATE_PROPOSAL" in risk.evaluate(item.proposal, c.account, now=NOW).reasons
    assert restarted.journal.events()[-1]["status"] == "risk_review_started"


def test_unavailable_earnings_for_swing_horizon(tmp_path: Path) -> None:
    c = context()
    e = replace(
        c.evidence, earnings=replace(c.evidence.earnings, covered_until=NOW + timedelta(days=2))
    )
    result = engine(tmp_path, Rules(style=Style.SWING)).propose(replace(c, evidence=e), now=NOW)
    assert result.reasons == ("EARNINGS_COVERAGE_UNKNOWN",)


def test_journal_rollback_and_corruption(tmp_path: Path) -> None:
    eng, c, _ = candidate(tmp_path)
    assert eng.propose(c, now=NOW - timedelta(seconds=1)).candidate is None
    with eng.journal.connect() as db:
        db.execute("DROP TABLE claims")
    assert eng.propose(c, now=NOW).reasons == ("JOURNAL_UNAVAILABLE",)


def test_naive_decision_time_fails_closed(tmp_path: Path) -> None:
    assert engine(tmp_path).propose(context(), now=NOW.replace(tzinfo=None)).reasons == (
        "INVALID_TIME",
    )
