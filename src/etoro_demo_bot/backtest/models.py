"""Offline point-in-time replay contracts; no broker payloads or credentials."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..risk.models import money
from ..scanner.models import Instrument, Quote, aware, fresh
from ..strategy.models import Evidence, ObservedBar, Rules

D = Decimal


@dataclass(frozen=True)
class Provenance:
    kind: str  # synthetic or historical_verified; declaration requires external review
    source: str
    license: str
    review_reference: str
    limitations: tuple[str, ...]

    def validate(self) -> None:
        if self.kind not in ("synthetic", "historical_verified") or not all(
            (self.source, self.license, self.review_reference, self.limitations)
        ):
            raise ValueError("Complete evidence provenance is required.")


@dataclass(frozen=True)
class Tick:
    at: datetime
    quote: Quote
    evidence: Evidence
    available_units: Decimal
    decide: bool = True
    close_allowed: bool = False


@dataclass(frozen=True)
class Dataset:
    instrument: Instrument
    start: datetime
    end: datetime
    initial_usd_per_eur: Decimal
    initial_fx_known_at: datetime
    history: tuple[ObservedBar, ...]
    ticks: tuple[Tick, ...]
    provenance: Provenance

    def validate(self) -> None:
        self.provenance.validate()
        if (
            not aware(self.start)
            or not aware(self.end)
            or self.end <= self.start
            or self.start.utcoffset() != timedelta(0)
            or any((self.start.hour, self.start.minute, self.start.second, self.start.microsecond))
            or not fresh(self.initial_fx_known_at, self.start, 60)
            or not money(self.initial_usd_per_eur, positive=True)
            or not self.ticks
            or self.instrument.kind not in ("Stocks", "ETF")
        ):
            raise ValueError("Invalid replay boundaries or initial FX evidence.")
        previous = self.start
        for index, tick in enumerate(self.ticks):
            if (
                not aware(tick.at)
                or not self.start <= tick.at <= self.end
                or index > 0
                and tick.at <= previous
                or not fresh(tick.quote.observed_at, tick.at, 60)
                or tick.quote.instrument_id != self.instrument.instrument_id
                or tick.quote.quote_type != "realtime"
                or not money(tick.quote.bid, positive=True)
                or not money(tick.quote.ask, positive=True)
                or tick.quote.bid > tick.quote.ask
                or type(tick.close_allowed) is not bool
                or type(tick.decide) is not bool
                or not money(tick.available_units)
                or not money(tick.evidence.quantity_step, positive=True)
                or not aware(tick.evidence.session.valid_until)
                or not aware(tick.evidence.session_close)
                or not aware(tick.evidence.product.expires_at)
                or not fresh(tick.evidence.available_at, tick.at, 60)
            ):
                raise ValueError("Invalid, stale, future or unordered replay event.")
            previous = tick.at
        if self.ticks[-1].at != self.end:
            raise ValueError("Final valuation requires an observed final quote.")
        seen: set[datetime] = set()
        for bar in self.history:
            if (
                not aware(bar.available_at)
                or not aware(bar.candle.start)
                or bar.candle.start in seen
            ):
                raise ValueError(
                    "History must have unique aware bars; revisions need a versioned adapter."
                )
            seen.add(bar.candle.start)


@dataclass(frozen=True)
class Simulation:
    initial_eur: Decimal = D("500")
    commission_fixed: Decimal = D("0.01")
    commission_fraction: Decimal = D("0.0005")
    slippage_fraction: Decimal = D("0.0005")
    fx_fraction: Decimal = D("0.001")
    fill_fraction: Decimal = D("1")
    delay_seconds: int = 1
    kill_switch: bool = False

    def __post_init__(self) -> None:
        if self.initial_eur not in (D("500"), D("1000")):
            raise ValueError("Supported starting scenarios are EUR 500 and EUR 1000.")
        for v in (
            self.commission_fixed,
            self.commission_fraction,
            self.slippage_fraction,
            self.fx_fraction,
        ):
            if not money(v):
                raise ValueError("Invalid simulation cost.")
        if (
            any(
                v >= 1 for v in (self.commission_fraction, self.slippage_fraction, self.fx_fraction)
            )
            or not money(self.fill_fraction, positive=True)
            or self.fill_fraction > 1
            or type(self.delay_seconds) is not int
            or not 1 <= self.delay_seconds <= 86400
            or type(self.kill_switch) is not bool
        ):
            raise ValueError("Invalid simulation fill policy.")


@dataclass(frozen=True)
class Plan:
    rules: Rules
    simulation: Simulation
