"""SYNTHETIC engineering fixtures only; block credentials and all socket connections."""

import json
import socket
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.alpaca.config import Credentials
from etoro_demo_bot.backtest import Simulation
from etoro_demo_bot.backtest.intraday import Dataset, IntradayBacktest, Plan, Review
from etoro_demo_bot.backtest.intraday.fills import bar_touch, fee, price, quantity
from etoro_demo_bot.backtest.intraday.fixtures import synthetic_dataset
from etoro_demo_bot.backtest.intraday.report import write_bundle, write_report
from etoro_demo_bot.backtest.intraday.serialization import normalized
from etoro_demo_bot.backtest.models import Tick
from etoro_demo_bot.risk import RiskEngine
from etoro_demo_bot.risk.models import RiskPolicy
from etoro_demo_bot.strategy.journal import digest
from etoro_demo_bot.timeframes import HOURLY_BASELINE


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Intraday research cannot connect or load credentials.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(Credentials, "from_environment", blocked)


def run(data: Dataset, root: Path, plan: Plan | None = None) -> Any:
    return IntradayBacktest(data, plan).run(root)


def requote(t: Tick, bid: D) -> Tick:
    return replace(t, quote=replace(t.quote, bid=bid, ask=bid + D(".01")))


def mutate_bar(data: Dataset, index: int, **values: Any) -> Dataset:
    bars = list(data.series.bars)
    bars[index] = replace(bars[index], observation=replace(bars[index].observation, **values))
    return replace(data, series=replace(data.series, bars=tuple(bars)))


@pytest.mark.parametrize("eur", [D(500), D(1000)])
def test_full_replay_costs_risk_and_original_evidence(tmp_path: Path, eur: D) -> None:
    data = synthetic_dataset()
    before = digest(normalized(asdict(data)))
    result = run(data, tmp_path / "new", Plan(simulation=Simulation(initial_eur=eur)))
    assert result.manifest["status"] == "synthetic"
    assert result.metrics["closed_positions"] == 1
    assert result.metrics["net_return"] < result.metrics["gross_return"]
    assert result.metrics["trading_costs_usd"] > 0
    assert result.manifest["execution_authorized"] is False
    assert result.manifest["dataset_digest"] == before == digest(normalized(asdict(data)))
    entry = next(e for e in result.events if e["kind"] == "entry_fill")
    signal = next(e for e in result.events if e["kind"] == "signal_admitted")
    assert datetime.fromisoformat(entry["at"]) > datetime.fromisoformat(entry["signal_at"])
    assert D(entry["price"]) >= signal["proposal"]["proposal"]["price"]
    p = signal["proposal"]["proposal"]
    assert p["leverage"] == 1 and p["side"] == "buy"
    assert p["units"] * (p["price"] - p["stop_loss"]) + p["cost_buffer"] <= eur * D("1.1") * D(
        ".01"
    )
    assert result.benchmarks["cash_eur"]["return"] == 0
    assert result.benchmarks["hourly_strategies"]["status"] == "blocked"
    assert result.benchmarks["buy_and_hold"]["status"] == "blocked"


@pytest.mark.parametrize("delay", [1, 2, 59, 60, 300])
def test_entry_never_backdated_and_expiry(tmp_path: Path, delay: int) -> None:
    result = run(
        synthetic_dataset(), tmp_path / "new", Plan(simulation=Simulation(delay_seconds=delay))
    )
    fills = [e for e in result.events if e["kind"] == "entry_fill"]
    if delay == 1:
        assert fills
    else:
        # No eligible quote arrives within the original 60s signal life.
        assert not fills
        assert result.metrics["missed_opportunities"] == 1


@pytest.mark.parametrize("known_delay", [1, 59, 60, 301])
def test_first_known_time_controls_signal(tmp_path: Path, known_delay: int) -> None:
    data = synthetic_dataset()
    bars = list(data.series.bars)
    original = bars[3]
    known = original.completed_at + timedelta(seconds=known_delay)
    bars[3] = replace(
        original, first_known_at=known, observation=replace(original.observation, known_at=known)
    )
    data = replace(data, series=replace(data.series, bars=tuple(bars)))
    result = run(data, tmp_path / "new")
    assert bool([e for e in result.events if e["kind"] == "entry_fill"]) is (known_delay == 1)


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "duplicate",
        "unordered",
        "wrong_contract",
        "late_snapshot",
        "bad_hash",
        "stale_quote",
        "future_quote",
        "stale_fx",
        "out_of_session",
        "missing_boundary",
        "source",
        "review_snapshot",
        "missing_session",
    ],
)
def test_invalid_or_unqualified_data_blocks_metrics(tmp_path: Path, bad: str) -> None:
    data = synthetic_dataset()
    s = data.series
    if bad == "missing":
        data = replace(data, series=replace(s, bars=s.bars[:5] + s.bars[6:]))
    elif bad == "duplicate":
        data = replace(data, series=replace(s, bars=s.bars[:5] + (s.bars[4],) + s.bars[5:]))
    elif bad == "unordered":
        data = replace(data, ticks=(data.ticks[1], data.ticks[0], *data.ticks[2:]))
    elif bad == "wrong_contract":
        data = replace(data, series=replace(s, contract=HOURLY_BASELINE))
    elif bad == "late_snapshot":
        source = replace(
            s.source, classification="historical_observation", retrieved_at=s.sessions[0].closes
        )
        data = replace(data, series=replace(s, source=source))
    elif bad == "bad_hash":
        data = replace(data, series=replace(s, source=replace(s.source, raw_sha256="invalid")))
    elif bad in ("stale_quote", "future_quote"):
        t = data.ticks[3]
        q = replace(
            t.quote, observed_at=t.at + timedelta(seconds=1 if bad == "future_quote" else -61)
        )
        data = replace(data, ticks=(*data.ticks[:3], replace(t, quote=q), *data.ticks[4:]))
    elif bad == "stale_fx":
        t = data.ticks[0]
        e = replace(
            t.evidence,
            budget=replace(t.evidence.budget, fx_observed_at=t.at - timedelta(seconds=61)),
        )
        data = replace(data, ticks=(replace(t, evidence=e), *data.ticks[1:]))
    elif bad == "out_of_session":
        data = replace(
            data,
            ticks=(
                replace(data.ticks[0], at=s.sessions[0].opens - timedelta(seconds=1)),
                *data.ticks[1:],
            ),
        )
    elif bad == "missing_boundary":
        data = replace(data, ticks=data.ticks[1:])
    elif bad == "source":
        data = replace(data, series=replace(s, source=replace(s.source, provider="unknown")))
    elif bad == "review_snapshot":
        data = replace(data, review=Review("wrong"))
    elif bad == "missing_session":
        data = synthetic_dataset((date(2026, 3, 9), date(2026, 3, 11)))
    result = run(data, tmp_path / "new")
    assert result.manifest["status"] == "blocked" and result.metrics == {}
    assert not result.events and not (tmp_path / "new" / "simulation-risk.sqlite").exists()
    write_report(result, tmp_path / "report")
    assert "metrics withheld" in (tmp_path / "report" / "report.md").read_text()


@pytest.mark.parametrize(
    "reference", ["coverage", "availability", "usage_rights", "corporate_actions"]
)
def test_historical_critical_reviews_are_required(tmp_path: Path, reference: str) -> None:
    data = synthetic_dataset()
    review = Review(
        data.series.snapshot,
        "coverage-ref",
        "original-availability-ref",
        "rights-ref",
        "actions-ref",
        ("quotes/FX/eligibility modelled",),
    )
    review = replace(review, **{reference: ""})  # type: ignore[arg-type]
    series = replace(
        data.series,
        source=replace(data.series.source, classification="historical_observation"),
        replay_blockers=(),
    )
    result = run(replace(data, series=series, review=review), tmp_path / "new")
    assert result.manifest["status"] == "blocked"
    assert "CRITICAL_HISTORICAL_REVIEW_MISSING" in result.manifest["blockers"]


def test_original_replay_blockers_cannot_be_silently_ignored(tmp_path: Path) -> None:
    data = synthetic_dataset()
    data = replace(
        data,
        series=replace(
            data.series, source=replace(data.series.source, classification="historical_observation")
        ),
        review=Review(data.series.snapshot, "c", "a", "r", "actions"),
    )
    result = run(data, tmp_path / "new")
    assert "ORIGINAL_AVAILABILITY_UNVERIFIED" in result.manifest["blockers"]
    assert not result.metrics


@pytest.mark.parametrize("bid", [D(90), D(70)])
def test_stop_gap_is_not_capped_at_requested_stop(tmp_path: Path, bid: D) -> None:
    data = synthetic_dataset()
    first = data.series.sessions[0].opens + timedelta(minutes=25)
    data = replace(data, ticks=tuple(requote(t, bid) if t.at >= first else t for t in data.ticks))
    result = run(data, tmp_path / "new")
    assert result.trades and D(result.trades[0]["exit"]) < 100
    assert D(result.trades[0]["exit"]) <= bid
    assert datetime.fromisoformat(result.trades[0]["at"]) > first
    if bid == 70:
        assert any(
            e["kind"] == "risk_halt" and "DAILY_LOSS_LIMIT" in e["reasons"] for e in result.events
        )


@pytest.mark.parametrize("kind", ["stop", "target", "both", "gap_stop", "gap_target"])
def test_intrabar_touch_conservative_ordering(tmp_path: Path, kind: str) -> None:
    data = synthetic_dataset()
    values = {
        "stop": dict(low=D(99), high=D("100.6")),
        "target": dict(low=D("100.35"), high=D(103)),
        "both": dict(low=D(99), high=D(103)),
        "gap_stop": dict(open=D(90), low=D(89), high=D(101)),
        "gap_target": dict(open=D(103), low=D(100), high=D(104)),
    }[kind]
    data = mutate_bar(data, 5, **values)
    result = run(data, tmp_path / "new")
    trade = result.trades[0]
    if kind == "both":
        assert trade["reason"] == "ambiguous_stop_first"
        assert result.metrics["ambiguous_stop_first"] == 1
    if kind == "gap_stop":
        assert D(trade["exit"]) < 90
    assert datetime.fromisoformat(trade["at"]) > data.series.bars[5].first_known_at
    if kind in ("target", "gap_target"):
        signal = next(e for e in result.events if e["kind"] == "signal_admitted")
        assert D(trade["exit"]) <= signal["proposal"]["target"]


def test_entry_bar_extremes_do_not_hit_before_fill(tmp_path: Path) -> None:
    data = mutate_bar(synthetic_dataset(), 4, low=D(1), high=D(1000))
    result = run(data, tmp_path / "new")
    assert result.trades[0]["reason"] == "session_deadline"


def test_future_prices_cannot_change_an_earlier_signal(tmp_path: Path) -> None:
    data = synthetic_dataset()
    altered = mutate_bar(data, 50, low=D(1), high=D(1000))
    a, b = run(data, tmp_path / "a"), run(altered, tmp_path / "b")
    ea = next(e for e in a.events if e["kind"] == "signal_admitted")
    eb = next(e for e in b.events if e["kind"] == "signal_admitted")
    assert ea == eb
    assert [e for e in a.events if e["kind"] == "entry_fill"] == [
        e for e in b.events if e["kind"] == "entry_fill"
    ]


@pytest.mark.parametrize(
    "mode",
    ["minimum", "whole_only", "ineligible", "unknown_step", "chase", "zero_liquidity", "new_max"],
)
def test_fill_rechecks_evidence_and_fractional_capacity(tmp_path: Path, mode: str) -> None:
    data = synthetic_dataset()
    changed = []
    for t in data.ticks:
        if (t.at - data.series.sessions[0].opens).total_seconds() == 1202:
            e = t.evidence
            if mode == "minimum":
                e = replace(e, eligibility=replace(e.eligibility, minimum_usd=D(1000)))
            elif mode == "whole_only":
                e = replace(e, eligibility=replace(e.eligibility, fractional=False))
            elif mode == "ineligible":
                e = replace(e, eligibility=replace(e.eligibility, underlying_long=False))
            elif mode == "unknown_step":
                e = replace(e, quantity_step_verified=False)
            elif mode == "chase":
                t = requote(t, D(104))
            elif mode == "zero_liquidity":
                t = replace(t, available_units=D(0))
            elif mode == "new_max":
                e = replace(e, eligibility=replace(e.eligibility, max_units=D(".01")))
            t = replace(t, evidence=e)
        changed.append(t)
    result = run(replace(data, ticks=tuple(changed)), tmp_path / "new")
    assert not any(e["kind"] == "entry_fill" for e in result.events)
    assert result.manifest["status"] == "blocked" or result.metrics["rejected_opportunities"] >= 1


def test_partial_entry_cancels_remainder_and_partial_exit_tracks_inventory(tmp_path: Path) -> None:
    data = synthetic_dataset()
    window = data.series.sessions[0]
    ticks = []
    for t in data.ticks:
        seconds = int((t.at - window.opens).total_seconds())
        if seconds == 1202:
            t = replace(t, available_units=D(".5"))
        if t.at == window.closes - timedelta(seconds=898):
            t = replace(t, available_units=D(".25"))
        ticks.append(t)
    result = run(replace(data, ticks=tuple(ticks)), tmp_path / "new")
    entry = next(e for e in result.events if e["kind"] == "entry_fill")
    assert D(entry["units"]) == D(".5") and D(entry["unfilled_cancelled"]) > 0
    assert len(result.trades) == 2
    assert sum(D(t["units"]) for t in result.trades) == D(".5")
    assert result.metrics["closed_positions"] == 1


def test_no_exit_liquidity_is_unresolved_not_fabricated(tmp_path: Path) -> None:
    data = synthetic_dataset()
    cutoff = data.series.sessions[0].closes - timedelta(minutes=15)
    data = replace(
        data,
        ticks=tuple(replace(t, available_units=D(0)) if t.at >= cutoff else t for t in data.ticks),
    )
    result = run(data, tmp_path / "new")
    assert result.manifest["unresolved_inventory"]
    assert D(result.metrics["open_units"]) > 0 and not result.trades
    assert result.metrics["closed_positions"] == 0


def test_overnight_unfilled_exit_uses_next_available_gap_quote(tmp_path: Path) -> None:
    data = synthetic_dataset((date(2026, 3, 9), date(2026, 3, 10)))
    first, second = data.series.sessions
    ticks = []
    for t in data.ticks:
        if first.closes - timedelta(minutes=15) <= t.at <= first.closes:
            t = replace(t, available_units=D(0))
        if t.at >= second.opens:
            t = requote(t, D(90))
        ticks.append(t)
    result = run(replace(data, ticks=tuple(ticks)), tmp_path / "new")
    assert result.trades[0]["overnight"] and result.trades[0]["deadline_breached"]
    assert D(result.trades[0]["exit"]) < 90


@pytest.mark.parametrize(
    "day,hour,count",
    [
        (date(2026, 3, 6), 14, 78),
        (date(2026, 3, 9), 13, 78),
        (date(2026, 10, 30), 13, 78),
        (date(2026, 11, 2), 14, 78),
        (date(2026, 11, 27), 14, 42),
        (date(2026, 12, 24), 14, 42),
    ],
)
def test_dst_early_close_and_session_exit(tmp_path: Path, day: date, hour: int, count: int) -> None:
    data = synthetic_dataset((day,))
    assert data.series.sessions[0].opens.hour == hour and len(data.series.bars) == count
    result = run(data, tmp_path / "new")
    assert result.metrics["closed_positions"] == 1
    close = datetime.fromisoformat(result.trades[0]["at"])
    assert (
        data.series.sessions[0].closes - timedelta(minutes=15)
        < close
        < data.series.sessions[0].closes
    )


@pytest.mark.parametrize("killed", [True, False])
def test_actual_kill_switch_and_position_risk(
    tmp_path: Path, killed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not killed:
        original = RiskEngine.__init__

        def tight(self: RiskEngine, store: Any, policy: RiskPolicy | None = None) -> None:
            original(self, store, RiskPolicy(max_position_fraction=D(".001")))

        monkeypatch.setattr(RiskEngine, "__init__", tight)
    result = run(
        synthetic_dataset(), tmp_path / "new", Plan(simulation=Simulation(kill_switch=killed))
    )
    assert not any(e["kind"] == "entry_fill" for e in result.events)
    reason = "KILL_SWITCH_ACTIVE" if killed else "POSITION_SIZE_LIMIT"
    assert any(e["kind"] == "signal_rejected" and reason in e["reasons"] for e in result.events)


def test_reports_and_restart_are_byte_reproducible(tmp_path: Path) -> None:
    data = synthetic_dataset()
    a, b = run(data, tmp_path / "a"), run(data, tmp_path / "b")
    write_report(a, tmp_path / "ra")
    write_report(b, tmp_path / "rb")
    for p in (tmp_path / "ra").iterdir():
        assert p.read_bytes() == (tmp_path / "rb" / p.name).read_bytes()
    with pytest.raises(FileExistsError):
        run(data, tmp_path / "a")
    assert (
        json.loads((tmp_path / "ra" / "report.json").read_text())["manifest"]["provenance"]["kind"]
        == "synthetic_fixture"
    )


def test_fill_arithmetic_and_no_global_decimal_change() -> None:
    data = synthetic_dataset()
    tick = data.ticks[0]
    assert price(D("1.0000001"), buy=True) == D("1.000001")
    assert price(D("1.0000009"), buy=False) == D("1.000000")
    assert fee(D(1), D(100), Simulation()) == D(".060000")
    assert quantity(D(3), replace(tick, available_units=D(".25")), Simulation()) == D(".25")
    assert bar_touch(data.series.bars[0], D(90), D(110), D(0)) is None


def test_csv_external_text_cannot_become_formula(tmp_path: Path) -> None:
    result = run(synthetic_dataset(), tmp_path / "run")
    payload = {"manifest": result.manifest, "events": [{"text": "=HYPERLINK(evil)"}]}
    write_bundle(payload, tmp_path / "report")
    assert "'=HYPERLINK" in (tmp_path / "report" / "events.csv").read_text()


def test_hourly_baseline_rejects_intraday_type() -> None:
    # Independent adapter, never passes 5Min data through hourly validation.
    with pytest.raises((AttributeError, ValueError)):
        from etoro_demo_bot.backtest.fixtures import synthetic_dataset as hourly
        from etoro_demo_bot.timeframes import FIVE_MINUTE_RESEARCH

        replace(hourly(), contract=FIVE_MINUTE_RESEARCH).validate()


def test_fx_funding_and_terminal_translation_are_not_double_charged(tmp_path: Path) -> None:
    data = synthetic_dataset()
    ticks = list(data.ticks)
    t = ticks[-1]
    ticks[-1] = replace(
        t, evidence=replace(t.evidence, budget=replace(t.evidence.budget, usd_per_eur=D("1.2")))
    )
    result = run(
        replace(data, ticks=tuple(ticks)),
        tmp_path / "new",
        Plan(simulation=Simulation(kill_switch=True)),
    )
    initial_fx = data.ticks[0].evidence.budget.usd_per_eur
    initial = D(500) * initial_fx
    funding = price(initial * D(".001"), buy=True)
    expected = float((initial - funding) / D("1.2") / D(500) - 1)
    assert result.metrics["net_return"] == pytest.approx(expected, abs=1e-8)
    assert result.metrics["trading_costs_usd"] == float(funding)
    assert result.metrics["closed_positions"] == 0


@pytest.mark.parametrize("kind", ["trade", "instrument", "total", "concurrency"])
def test_unchanged_risk_limits_still_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from etoro_demo_bot.risk.models import AccountSnapshot, Decision, Exposure, Proposal

    original = RiskEngine.evaluate

    def evaluate(
        self: RiskEngine, proposal: Proposal, account: AccountSnapshot, *, now: datetime
    ) -> Decision:
        if proposal.units > 0:
            if kind == "trade":
                assert proposal.price is not None
                proposal = replace(proposal, stop_loss=D(1))
            elif kind == "instrument":
                account = replace(
                    account,
                    exposures=(Exposure(proposal.instrument_id, account.equity * D(".2"), 1),),
                )
            elif kind == "total":
                account = replace(account, exposures=(Exposure(999, account.equity * D(".8"), 1),))
            elif kind == "concurrency":
                account = replace(account, exposures=(Exposure(999, D(1), 5),))
        return original(self, proposal, account, now=now)

    monkeypatch.setattr(RiskEngine, "evaluate", evaluate)
    result = run(synthetic_dataset(), tmp_path / "new")
    reason = {
        "trade": "TRADE_RISK_LIMIT",
        "instrument": "INSTRUMENT_EXPOSURE_LIMIT",
        "total": "TOTAL_EXPOSURE_LIMIT",
        "concurrency": "CONCURRENT_POSITION_LIMIT",
    }[kind]
    assert not any(e["kind"] == "entry_fill" for e in result.events)
    assert any(e["kind"] == "signal_rejected" and reason in e["reasons"] for e in result.events)


def test_future_calendar_review_cannot_certify_an_earlier_session(tmp_path: Path) -> None:
    data = synthetic_dataset()
    w = data.series.sessions[0]
    later = replace(w, calendar_verified_at=w.closes + timedelta(days=1))
    data = replace(
        data,
        series=replace(
            data.series,
            sessions=(later,),
            bars=tuple(replace(b, session=later) for b in data.series.bars),
        ),
    )
    result = run(data, tmp_path / "new")
    assert result.manifest["status"] == "blocked" and not result.metrics


def test_historical_missing_assumption_manifest_is_blocked(tmp_path: Path) -> None:
    data = synthetic_dataset()
    series = replace(
        data.series,
        source=replace(data.series.source, classification="historical_observation"),
        replay_blockers=(),
    )
    review = Review(series.snapshot, "coverage", "availability", "rights", "actions")
    result = run(replace(data, series=series, review=review), tmp_path / "new")
    assert "HISTORICAL_EXECUTION_EVIDENCE_OR_ASSUMPTIONS_MISSING" in result.manifest["blockers"]
    assert not result.metrics


def test_assumed_historical_eligibility_cannot_grant_fractional_capacity(tmp_path: Path) -> None:
    data = synthetic_dataset()
    fields = ("quotes", "spreads", "fx", "eligibility", "costs", "liquidity", "earnings")
    review = Review(
        data.series.snapshot, "coverage", "availability", "rights", "actions", assumed_fields=fields
    )
    data = replace(
        data,
        review=review,
        series=replace(
            data.series,
            source=replace(data.series.source, classification="historical_observation"),
            replay_blockers=(),
        ),
    )
    result = run(data, tmp_path / "new")
    assert "FRACTIONAL_ELIGIBILITY_REQUIRES_REVIEWED_EVIDENCE" in result.manifest["blockers"]
    assert result.metrics == {}


def test_original_offsets_survive_report_and_risk_uses_utc_day(tmp_path: Path) -> None:
    from datetime import timezone

    data = synthetic_dataset()
    offset = timezone(timedelta(hours=14))
    ticks = tuple(replace(t, at=t.at.astimezone(offset)) for t in data.ticks)
    bars = tuple(
        replace(
            b,
            completed_at=b.completed_at.astimezone(offset),
            first_known_at=b.first_known_at.astimezone(offset),
            observation=replace(
                b.observation,
                start=b.observation.start.astimezone(offset),
                end=b.observation.end.astimezone(offset),
                known_at=b.observation.known_at.astimezone(offset),
            ),
        )
        for b in data.series.bars
    )
    shifted = replace(data, ticks=ticks, series=replace(data.series, bars=bars))
    original = run(data, tmp_path / "a")
    result = run(shifted, tmp_path / "b")
    assert result.metrics == original.metrics
    assert result.manifest["original_bar_timestamps"][0]["start"].endswith("+14:00")
    assert result.manifest["original_bar_timestamps"][0]["first_known_at"].endswith("+14:00")
    assert result.metrics["closed_positions"] == 1
