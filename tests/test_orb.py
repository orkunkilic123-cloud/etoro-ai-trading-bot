"""SYNTHETIC ORB engineering scenarios, never market evidence or profitability."""

import socket
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.alpaca.config import Credentials
from etoro_demo_bot.history.calendar import NYSE2026
from etoro_demo_bot.history.intraday import ResearchBar, ResearchSeries, SessionWindow
from etoro_demo_bot.history.models import Bar, Source
from etoro_demo_bot.monte_carlo.fixtures import synthetic_inputs
from etoro_demo_bot.risk import RiskEngine, RiskStore
from etoro_demo_bot.strategy.engine import StrategyEngine
from etoro_demo_bot.strategy.journal import Journal, encode
from etoro_demo_bot.strategy.models import Rules
from etoro_demo_bot.strategy.orb import OrbContext, OrbRules, VolumeEvidence, make_proposal
from etoro_demo_bot.timeframes import FIVE_MINUTE_RESEARCH, HOURLY_BASELINE


@pytest.fixture(autouse=True)
def no_network_or_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("ORB tests must not access sockets or real credentials")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(Credentials, "from_environment", blocked)


def scenario(day: date = date(2026, 3, 9), count: int = 4) -> tuple[OrbContext, datetime]:
    """Fabricated original availability at bar completion, exclusively for deterministic tests."""
    cal = NYSE2026(verified_at=datetime.combine(day, datetime.min.time(), UTC))
    sess = cal.sessions(day, day)[0]
    window = SessionWindow(day, sess.opens, sess.closes, cal.source_url, cal.verified_at)
    now = sess.opens + timedelta(minutes=count * 5, seconds=1)
    snapshot = "b" * 64
    bars = []
    for j in range(count):
        start = sess.opens + timedelta(minutes=j * 5)
        finish = start + timedelta(minutes=5)
        close = D("100") if j < 3 else D("100.4")
        bar = Bar(
            start,
            finish,
            D("100"),
            D("100.3") if j < 3 else D("100.5"),
            D("99.7"),
            close,
            D(100) if j < 3 else D(250),
            finish,
            "raw",
        )
        bars.append(ResearchBar(bar, finish, finish, window, snapshot))
    source = Source(
        "alpaca-iex-download-5min-v1",
        "https://data.alpaca.markets/v2/stocks/bars?timeframe=5Min",
        "https://alpaca.markets/disclosures",
        now,
        "a" * 64,
        "synthetic",
        "SYNTHETIC ORB fixture; fabricated availability, not historical verification",
    )
    series = ResearchSeries(
        FIVE_MINUTE_RESEARCH,
        "SYNTH",
        source,
        snapshot,
        tuple(bars),
        (window,),
        ("SYNTHETIC_SOURCE", "ORIGINAL_AVAILABILITY_UNVERIFIED"),
    )
    base, _ = synthetic_inputs(500)
    e = base.evidence
    evidence = replace(
        e,
        available_at=now,
        session_close=sess.closes,
        liquidity_observed_at=now,
        eligibility=replace(e.eligibility, observed_at=now),
        product=replace(e.product, expires_at=now + timedelta(days=1)),
        session=replace(e.session, observed_at=now, valid_until=now + timedelta(seconds=60)),
        earnings=replace(
            e.earnings,
            known_at=now,
            covered_from=now - timedelta(days=1),
            covered_until=sess.closes + timedelta(days=2),
            announcements=(),
            complete=True,
        ),
        budget=replace(e.budget, fx_observed_at=now),
    )
    account = replace(base.account, observed_at=now)
    quote = replace(base.opportunity.quote, bid=D("100.40"), ask=D("100.41"), observed_at=now)
    return OrbContext(
        series, replace(base.opportunity.instrument, symbol="SYNTH"), quote, evidence, account
    ), now


def engine(tmp_path: Path, name: str = "journal.sqlite") -> StrategyEngine:
    return StrategyEngine(Journal.initialize(tmp_path / name))


def replace_bar(c: OrbContext, index: int, **changes: Any) -> OrbContext:
    bars = list(c.series.bars)
    obs = replace(bars[index].observation, **changes)
    bars[index] = replace(bars[index], observation=obs, first_known_at=obs.known_at)
    return replace(c, series=replace(c.series, bars=tuple(bars)))


@pytest.mark.parametrize("stop", ["midpoint", "low"])
def test_completed_breakout_explained_and_proposal_only(tmp_path: Path, stop: str) -> None:
    c, now = scenario()
    worker = engine(tmp_path)
    outcome = worker.propose_orb(c, now=now, rules=OrbRules(stop_rule=stop))
    assert outcome.status == "proposed" and outcome.candidate is not None
    p = outcome.candidate
    assert p.range_high == D("100.3") and p.range_low == D("99.7")
    assert p.range_end == p.session_opens + timedelta(minutes=15)
    assert p.confirmation_end == p.session_opens + timedelta(minutes=20)
    assert p.proposal.price == c.quote.ask  # Confirmation close is not a fabricated fill.
    assert p.proposal.stop_loss == (D("100") if stop == "midpoint" else D("99.7"))
    assert p.target == p.proposal.price + 2 * (p.proposal.price - p.proposal.stop_loss)
    assert p.invalidates_at_or_below == p.range_high
    assert p.expires_at == p.confirmation_end + timedelta(seconds=60)
    assert p.exit_deadline == p.session_closes - timedelta(seconds=900)
    assert p.proposal.leverage == 1 and p.proposal.side == "buy"
    assert p.research_only and not p.execution_authorized
    assert "SYNTHETIC_SOURCE" in p.replay_blockers
    assert dict(p.evidence_times)["confirmation_known"] <= now
    assert worker.journal.events()[-1]["status"] == "orb_proposed"
    with worker.journal.connect() as db:
        assert db.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
    assert worker.propose_orb(c, now=now).reasons == ("ORB_DUPLICATE_SESSION_SIGNAL",)


@pytest.mark.parametrize(
    "change", ["wick", "equal", "inside", "quote_retrace", "chase", "large_gap"]
)
def test_false_breakouts_and_price_extensions(tmp_path: Path, change: str) -> None:
    c, now = scenario()
    if change in ("wick", "equal", "inside"):
        close = D("100.3") if change == "equal" else D("100.2")
        c = replace_bar(c, 3, close=close, high=D("101"))
    elif change == "quote_retrace":
        c = replace(c, quote=replace(c.quote, bid=D("100.2"), ask=D("100.21")))
    elif change == "chase":
        c = replace(c, quote=replace(c.quote, bid=D("100.8"), ask=D("100.81")))
    else:
        c = replace_bar(c, 3, open=D("103"), high=D("104"), close=D("103"))
        c = replace(c, quote=replace(c.quote, bid=D("103"), ask=D("103.01")))
    result = engine(tmp_path).propose_orb(c, now=now)
    assert result.candidate is None
    assert result.status in ("waiting", "invalidated", "blocked")


def test_modest_opening_gap_still_needs_completed_close(tmp_path: Path) -> None:
    c, now = scenario()
    c = replace_bar(c, 3, open=D("100.35"), low=D("100.34"))
    assert engine(tmp_path).propose_orb(c, now=now).candidate is not None


@pytest.mark.parametrize(
    "mode", ["missing", "duplicate", "reverse", "wrong_contract", "late_known", "stale_source"]
)
def test_temporal_and_provenance_failures(tmp_path: Path, mode: str) -> None:
    c, now = scenario()
    bars = c.series.bars
    if mode == "missing":
        c = replace(c, series=replace(c.series, bars=bars[:1] + bars[2:]))
    elif mode == "duplicate":
        c = replace(c, series=replace(c.series, bars=bars[:1] + bars))
    elif mode == "reverse":
        c = replace(c, series=replace(c.series, bars=tuple(reversed(bars))))
    elif mode == "wrong_contract":
        c = replace(c, series=replace(c.series, contract=HOURLY_BASELINE))
    elif mode == "late_known":
        c = replace_bar(c, 0, known_at=now + timedelta(hours=1))
    else:
        # Late historical retrieval cannot masquerade as original bar publication.
        c = replace(
            c,
            series=replace(
                c.series, source=replace(c.series.source, retrieved_at=now + timedelta(hours=1))
            ),
        )
    assert engine(tmp_path).propose_orb(c, now=now).candidate is None


@pytest.mark.parametrize("mode", ["incomplete", "misaligned", "out_of_session", "overlap"])
def test_phase1_rejects_invalid_bar_contract(mode: str) -> None:
    c, _ = scenario()
    b = c.series.bars[1]
    start = b.observation.start
    end = b.observation.end
    if mode == "incomplete":
        end -= timedelta(seconds=1)
    elif mode == "misaligned":
        start += timedelta(seconds=1)
        end += timedelta(seconds=1)
    elif mode == "out_of_session":
        start = b.session.opens - timedelta(minutes=5)
        end = b.session.opens
    else:
        start -= timedelta(minutes=1)
        end -= timedelta(minutes=1)
    with pytest.raises(ValueError):
        replace(b, observation=replace(b.observation, start=start, end=end), completed_at=end)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_range_requires_three_bars_and_later_confirmation(tmp_path: Path, count: int) -> None:
    c, now = scenario(count=count)
    result = engine(tmp_path).propose_orb(c, now=now)
    assert result.status == "waiting" and result.candidate is None


@pytest.mark.parametrize(
    "mode", ["missing", "unreviewed", "wrong_snapshot", "future", "zero", "thin", "qualified"]
)
def test_optional_volume_requires_qualified_evidence(tmp_path: Path, mode: str) -> None:
    c, now = scenario()
    v = VolumeEvidence(c.series.snapshot, now, "SYNTHETIC_VOLUME_REVIEW", complete=True)
    if mode == "missing":
        v = None  # type: ignore[assignment]
    elif mode == "unreviewed":
        v = replace(v, complete=False)
    elif mode == "wrong_snapshot":
        v = replace(v, snapshot="c" * 64)
    elif mode == "future":
        v = replace(v, available_at=now + timedelta(seconds=1))
    elif mode == "zero":
        for i in range(3):
            c = replace_bar(c, i, volume=D(0))
    elif mode == "thin":
        c = replace_bar(c, 3, volume=D(50))
    c = replace(c, volume=v)
    result = engine(tmp_path).propose_orb(c, now=now, rules=OrbRules(volume_ratio=D(2)))
    assert (result.candidate is not None) == (mode == "qualified")


def test_volume_disabled_does_not_impute_missing_volume(tmp_path: Path) -> None:
    c, now = scenario()
    c = replace_bar(c, 0, volume=None)
    assert engine(tmp_path).propose_orb(c, now=now).candidate is not None
    assert c.series.bars[0].observation.volume is None


@pytest.mark.parametrize("seconds", [59, 60, 61, 300])
def test_expiry_anchored_to_confirmation_not_retrieval(tmp_path: Path, seconds: int) -> None:
    c, now = scenario()
    decision = c.series.bars[-1].completed_at + timedelta(seconds=seconds)
    # Keep all other evidence fresh; expiry must still be tied to the original signal.
    c = fresh_context(c, decision)
    result = engine(tmp_path).propose_orb(c, now=decision)
    assert (result.candidate is not None) == (seconds < 60)


def fresh_context(c: OrbContext, now: datetime) -> OrbContext:
    e = c.evidence
    return replace(
        c,
        quote=replace(c.quote, observed_at=now),
        account=replace(c.account, observed_at=now),
        evidence=replace(
            e,
            available_at=now,
            liquidity_observed_at=now,
            earnings=replace(e.earnings, known_at=now),
            eligibility=replace(e.eligibility, observed_at=now),
            session=replace(e.session, observed_at=now, valid_until=now + timedelta(seconds=60)),
            budget=replace(e.budget, fx_observed_at=now),
        ),
    )


@pytest.mark.parametrize(
    "day,open_hour,close_hour",
    [
        (date(2026, 3, 6), 14, 21),
        (date(2026, 3, 9), 13, 20),
        (date(2026, 10, 30), 13, 20),
        (date(2026, 11, 2), 14, 21),
        (date(2026, 11, 27), 14, 18),
        (date(2026, 12, 24), 14, 18),
    ],
)
def test_dst_and_early_close_deadlines(
    tmp_path: Path, day: date, open_hour: int, close_hour: int
) -> None:
    c, now = scenario(day)
    p = engine(tmp_path).propose_orb(c, now=now).candidate
    assert p is not None
    assert p.session_opens.hour == open_hour and p.session_closes.hour == close_hour
    assert p.exit_deadline == p.session_closes - timedelta(minutes=15)


def test_holidays_and_cross_session_inputs_cannot_trigger(tmp_path: Path) -> None:
    c, now = scenario()
    assert not NYSE2026(verified_at=now).sessions(date(2026, 7, 3), date(2026, 7, 3))
    worker = engine(tmp_path)
    assert worker.propose_orb(c, now=datetime(2026, 7, 3, 15, tzinfo=UTC)).candidate is None
    assert worker.propose_orb(c, now=now + timedelta(days=1)).candidate is None
    assert worker.propose_orb(c, now=c.series.sessions[0].closes).candidate is None


def risk_engine(tmp_path: Path, c: OrbContext, *, arm: bool = False) -> RiskEngine:
    store = RiskStore.initialize(tmp_path / "research-risk.sqlite", c.account.account_id)
    store.establish_day(c.account.observed_at.date(), c.account.equity)
    if arm:
        store.set_kill_switch(False, acknowledged=True)  # Only this new SYNTHETIC fixture store.
    return RiskEngine(store)


@pytest.mark.parametrize("arm", [False, True])
def test_risk_handoff_preserves_kill_switch_and_never_authorizes(tmp_path: Path, arm: bool) -> None:
    c, now = scenario()
    worker = engine(tmp_path)
    p = worker.propose_orb(c, now=now).candidate
    assert p is not None
    risk = risk_engine(tmp_path, c, arm=arm)
    review = worker.review_orb(p, c, risk, now=now)
    assert review.decision.passed is arm
    assert not review.execution_authorized and not review.decision.execution_authorized
    if not arm:
        assert "KILL_SWITCH_ACTIVE" in review.decision.reasons
    assert not worker.review_orb(p, c, risk, now=now).decision.passed


def test_review_tampering_and_expiry_block_before_risk(tmp_path: Path) -> None:
    c, now = scenario()
    worker = engine(tmp_path)
    p = worker.propose_orb(c, now=now).candidate
    assert p is not None
    risk = risk_engine(tmp_path, c, arm=True)
    changed = replace(p, target=p.target + D(1))
    assert not worker.review_orb(changed, c, risk, now=now).decision.passed
    assert not worker.review_orb(p, c, risk, now=p.expires_at).decision.passed
    assert not worker.review_orb(
        p, replace(c, quote=replace(c.quote, ask=c.quote.ask + D(".01"))), risk, now=now
    ).decision.passed
    with risk.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 0


def test_future_bar_prices_do_not_change_past_signal(tmp_path: Path) -> None:
    c, now = scenario(count=5)
    at = c.series.sessions[0].opens + timedelta(minutes=20, seconds=1)
    c = fresh_context(c, at)
    c = replace(c, series=replace(c.series, source=replace(c.series.source, retrieved_at=at)))
    a = make_proposal(c, now=at, rules=OrbRules(), safety=Rules())
    changed = replace_bar(c, 4, high=D(500), low=D(1), close=D(499))
    b = make_proposal(changed, now=at, rules=OrbRules(), safety=Rules())
    assert asdict(a) == asdict(b)
    assert "orb-15m-v1" in encode(asdict(a))


@pytest.mark.parametrize(
    "mode",
    [
        "quote_old",
        "quote_future",
        "not_demo",
        "leveraged_product",
        "eligibility",
        "step",
        "earnings_unknown",
        "earnings_blackout",
        "spread",
        "fx",
        "wrong_symbol",
    ],
)
def test_market_evidence_never_bypassed(tmp_path: Path, mode: str) -> None:
    c, now = scenario()
    if mode == "quote_old":
        c = replace(c, quote=replace(c.quote, observed_at=now - timedelta(seconds=61)))
    elif mode == "quote_future":
        c = replace(c, quote=replace(c.quote, observed_at=now + timedelta(seconds=1)))
    elif mode == "not_demo":
        c = replace(c, account=replace(c.account, demo=False))
    elif mode == "leveraged_product":
        c = replace(
            c, evidence=replace(c.evidence, product=replace(c.evidence.product, unleveraged=False))
        )
    elif mode == "eligibility":
        c = replace(
            c,
            evidence=replace(
                c.evidence, eligibility=replace(c.evidence.eligibility, underlying_long=False)
            ),
        )
    elif mode == "step":
        c = replace(c, evidence=replace(c.evidence, quantity_step_verified=False))
    elif mode == "earnings_unknown":
        c = replace(
            c, evidence=replace(c.evidence, earnings=replace(c.evidence.earnings, complete=False))
        )
    elif mode == "earnings_blackout":
        c = replace(
            c,
            evidence=replace(
                c.evidence, earnings=replace(c.evidence.earnings, announcements=(now,))
            ),
        )
    elif mode == "spread":
        c = replace(c, quote=replace(c.quote, ask=D(102)))
    elif mode == "fx":
        c = replace(
            c,
            evidence=replace(
                c.evidence,
                budget=replace(c.evidence.budget, fx_observed_at=now - timedelta(seconds=61)),
            ),
        )
    else:
        c = replace(c, instrument=replace(c.instrument, symbol="OTHER"))
    assert engine(tmp_path).propose_orb(c, now=now).candidate is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "v2"),
        ("entry_ttl_seconds", 0),
        ("entry_ttl_seconds", 61),
        ("entry_ttl_seconds", True),
        ("close_buffer_seconds", 0),
        ("last_entry_minutes", 19),
        ("volume_ratio", D(0)),
        ("volume_ratio", D("NaN")),
        ("target_r", D(0)),
        ("stop_rule", "short"),
        ("max_chase_fraction", D(1)),
    ],
)
def test_invalid_rules_fail_closed(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(OrbRules(), **{field: value})


def test_new_session_has_new_signal_without_restarting_state(tmp_path: Path) -> None:
    a, at = scenario(date(2026, 3, 9))
    b, bt = scenario(date(2026, 3, 10))
    worker = engine(tmp_path)
    first = worker.propose_orb(a, now=at).candidate
    second = worker.propose_orb(b, now=bt).candidate
    assert first is not None and second is not None
    assert first.signal_id != second.signal_id


def test_entry_window_and_close_buffer_cannot_extend_safety(tmp_path: Path) -> None:
    c, now = scenario(count=18)
    assert engine(tmp_path).propose_orb(c, now=now).status == "expired"
    c, now = scenario(date(2026, 11, 27))
    p = (
        engine(tmp_path, "second.sqlite")
        .propose_orb(c, now=now, rules=OrbRules(close_buffer_seconds=60))
        .candidate
    )
    assert p is not None and p.exit_deadline == p.session_closes - timedelta(seconds=900)


def test_daily_loss_halt_still_rejects_research_proposal(tmp_path: Path) -> None:
    c, now = scenario()
    risk = risk_engine(tmp_path, c, arm=True)
    c = replace(c, account=replace(c.account, equity=c.account.equity * D(".97")))
    worker = engine(tmp_path)
    p = worker.propose_orb(c, now=now).candidate
    assert p is not None
    review = worker.review_orb(p, c, risk, now=now)
    assert not review.decision.passed and "DAILY_LOSS_LIMIT" in review.decision.reasons
    with risk.store.transaction() as db:
        assert db.execute("SELECT halted FROM days").fetchone()[0] == 1


def test_position_limit_rejects_even_when_strategy_allocation_is_larger(tmp_path: Path) -> None:
    c, now = scenario()
    c = replace(
        c,
        evidence=replace(
            c.evidence, budget=replace(c.evidence.budget, max_allocation_fraction=D(1))
        ),
    )
    worker = StrategyEngine(
        Journal.initialize(tmp_path / "journal.sqlite"), Rules(allocation_fraction=D(1))
    )
    p = worker.propose_orb(c, now=now).candidate
    assert p is not None
    review = worker.review_orb(p, c, risk_engine(tmp_path, c, arm=True), now=now)
    assert not review.decision.passed and "POSITION_SIZE_LIMIT" in review.decision.reasons


def test_unjournalled_pure_proposal_cannot_reach_risk(tmp_path: Path) -> None:
    c, now = scenario()
    p = make_proposal(c, now=now, rules=OrbRules(), safety=Rules())
    worker = engine(tmp_path)
    risk = risk_engine(tmp_path, c, arm=True)
    assert not worker.review_orb(p, c, risk, now=now).decision.passed
    with risk.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM reservations").fetchone()[0] == 0
