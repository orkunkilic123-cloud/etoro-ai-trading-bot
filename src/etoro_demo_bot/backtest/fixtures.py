"""Explicitly SYNTHETIC engineering scenarios. Not historical prices or exchange sessions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from ..scanner.analysis import Budget
from ..scanner.models import (
    Candle,
    Eligibility,
    Instrument,
    ProductEvidence,
    Quote,
    SessionEvidence,
)
from ..strategy.models import EarningsWindow, Evidence, ObservedBar
from .models import Dataset, Provenance, Tick


def synthetic_dataset(days: int = 3) -> Dataset:
    if not 1 <= days <= 100:
        raise ValueError("Synthetic scenario length must be 1–100 days.")
    start = datetime(2026, 1, 5, tzinfo=UTC)
    history = []
    for i in range(60):
        value = 100 + i * i * 0.01
        bar = Candle(
            start - timedelta(hours=60 - i),
            value,
            value + 0.2,
            value - 0.2,
            value,
            300 if i == 59 else 100,
        )
        history.append(ObservedBar(bar, bar.start + timedelta(hours=1)))
    ticks = []

    def tick(at: datetime, bid: str, decide: bool) -> Tick:
        price = D(bid)
        budget = Budget(
            D("500"), D("1.1"), at, "SYNTHETIC_FX", D(".001"), D(".02"), D(".001"), D(".001")
        )
        e = Evidence(
            Eligibility(1, D("10"), D("1000"), True, at, True),
            ProductEvidence(1, "USD", True, True, "SYNTHETIC_PRODUCT", at + timedelta(days=1)),
            SessionEvidence(1, True, at, at + timedelta(minutes=10), "SYNTHETIC_24H_CALENDAR"),
            budget,
            at,
            datetime.combine(at.date() + timedelta(days=1), datetime.min.time(), UTC),
            D("10000000"),
            at,
            D(".001"),
            True,
            EarningsWindow(
                1,
                at,
                at - timedelta(days=1),
                at + timedelta(days=8),
                (),
                "SYNTHETIC_NO_EVENTS",
                True,
            ),
        )
        return Tick(
            at,
            Quote(1, price, price + D(".02"), at, "realtime"),
            e,
            D("10000"),
            decide,
            close_allowed=True,
        )

    for day in range(days):
        boundary = start + timedelta(days=day)
        for hour in range(24):
            now = boundary + timedelta(hours=hour)
            # A synthetic opening move followed by a gap below the initial stop.
            bid = "134.80" if hour == 0 else "125.00" if hour < 4 else "130.00"
            ticks.append(tick(now, bid, True))
            ticks.append(tick(now + timedelta(seconds=5), bid, False))
            value = float(D(bid))
            candle = Candle(now, value, value + 0.2, value - 0.2, value, 100)
            history.append(ObservedBar(candle, now + timedelta(hours=1)))
    end = ticks[-1].at
    return Dataset(
        Instrument(1, "SYNTHETIC", "Stocks", 1),
        start,
        end,
        D("1.1"),
        start,
        tuple(history),
        tuple(ticks),
        Provenance(
            "synthetic",
            "Deterministic generated test scenario",
            "Repository test fixture",
            "NOT_REAL_MARKET_EVIDENCE",
            (
                "Invented engineering prices, metadata, liquidity, FX and 24h "
                "sessions; not historical evidence.",
            ),
        ),
    )
