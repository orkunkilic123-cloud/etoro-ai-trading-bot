"""Explicitly fabricated full sessions for software validation, never market evidence."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from ...history.calendar import NYSE2026
from ...history.intraday import ResearchBar, ResearchSeries, SessionWindow
from ...history.models import Bar, Source
from ...monte_carlo.fixtures import synthetic_inputs
from ...strategy.orb import VolumeEvidence
from ...timeframes import FIVE_MINUTE_RESEARCH
from ..models import Tick
from .models import Dataset, Review


def synthetic_dataset(days: tuple[date, ...] = (date(2026, 3, 9),)) -> Dataset:
    reviewed = datetime(2026, 1, 1, tzinfo=UTC)
    calendar = NYSE2026(verified_at=reviewed)
    windows = tuple(
        SessionWindow(d, s.opens, s.closes, calendar.source_url, reviewed)
        for d in days
        for s in calendar.sessions(d, d)
    )
    if not windows:
        raise ValueError("Synthetic fixture requires trading sessions.")
    snapshot = "b" * 64
    base, _ = synthetic_inputs(500)
    instrument = replace(base.opportunity.instrument, symbol="SYNTH")
    bars = []
    ticks = []
    for w in windows:
        count = int((w.closes - w.opens).total_seconds() / 300)
        for j in range(count):
            start = w.opens + timedelta(minutes=5 * j)
            end = start + timedelta(minutes=5)
            bar = Bar(
                start,
                end,
                D(100) if j < 4 else D("100.4"),
                D("100.3") if j < 3 else D("100.6"),
                D("99.7") if j < 4 else D("100.35"),
                D(100) if j < 3 else D("100.4"),
                D(100 if j < 3 else 250),
                end,
                "raw",
            )
            bars.append(ResearchBar(bar, end, end, w, snapshot))
        offsets = {
            0,
            int((w.closes - w.opens).total_seconds()),
            1202,
            int((w.closes - w.opens).total_seconds()) - 899,
            int((w.closes - w.opens).total_seconds()) - 898,
        }
        offsets.update(j * 300 + 1 for j in range(1, count))
        for seconds in sorted(offsets):
            at = w.opens + timedelta(seconds=seconds)
            bid = D("100.4") if seconds >= 1200 else D(100)
            e = base.evidence
            evidence = replace(
                e,
                available_at=at,
                session_close=w.closes,
                liquidity_observed_at=at,
                eligibility=replace(e.eligibility, observed_at=at),
                product=replace(e.product, expires_at=at + timedelta(days=1)),
                session=replace(
                    e.session,
                    observed_at=at,
                    valid_until=at + timedelta(seconds=60),
                    is_open=at < w.closes,
                ),
                budget=replace(
                    e.budget,
                    fx_observed_at=at,
                    conversion_cost_fraction=D(".001"),
                    round_trip_fixed_usd=D(".02"),
                    round_trip_fee_fraction=D(".001"),
                    slippage_fraction=D(".001"),
                ),
                earnings=replace(
                    e.earnings,
                    known_at=at,
                    covered_from=at - timedelta(days=1),
                    covered_until=w.closes + timedelta(days=2),
                    announcements=(),
                    complete=True,
                ),
            )
            quote = replace(base.opportunity.quote, bid=bid, ask=bid + D(".01"), observed_at=at)
            ticks.append(
                Tick(at, quote, evidence, D(1000), decide=seconds == 1201, close_allowed=True)
            )
    source = Source(
        "alpaca-iex-download-5min-v1",
        "https://data.alpaca.markets/v2/stocks/bars?timeframe=5Min",
        "https://alpaca.markets/disclosures",
        windows[0].opens,
        "a" * 64,
        "synthetic",
        "SYNTHETIC fabricated bars, quotes, first-known times, FX and eligibility; no market data",
    )
    series = ResearchSeries(
        FIVE_MINUTE_RESEARCH,
        "SYNTH",
        source,
        snapshot,
        tuple(bars),
        windows,
        ("SYNTHETIC_SOURCE", "ORIGINAL_AVAILABILITY_UNVERIFIED"),
    )
    return Dataset(
        series,
        instrument,
        tuple(ticks),
        Review(
            snapshot,
            assumptions=("All prices, availability, costs, FX and eligibility fabricated.",),
        ),
        VolumeEvidence(snapshot, windows[0].opens, "synthetic-volume-only", complete=True),
    )
