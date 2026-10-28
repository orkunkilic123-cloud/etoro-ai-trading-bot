"""Analysis-only contracts. Evidence is supplied by trusted adapters, never guessed."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from ..risk.models import AccountSnapshot, Decision, Proposal
from ..timeframes import HOURLY_BASELINE, BarContract


class ScanError(ValueError):
    """Fixed, non-sensitive failure code."""


def aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def fresh(value: datetime, now: datetime, age: int) -> bool:
    return aware(value) and aware(now) and timedelta(0) <= now - value <= timedelta(seconds=age)


@dataclass(frozen=True)
class Instrument:
    instrument_id: int
    symbol: str
    kind: str
    exchange_id: int


@dataclass(frozen=True)
class Quote:
    instrument_id: int
    bid: Decimal
    ask: Decimal
    observed_at: datetime
    quote_type: str


@dataclass(frozen=True)
class Candle:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    contract: BarContract = HOURLY_BASELINE


@dataclass(frozen=True)
class Eligibility:
    instrument_id: int
    minimum_usd: Decimal
    max_units: Decimal
    fractional: bool
    observed_at: datetime
    underlying_long: bool


@dataclass(frozen=True)
class ProductEvidence:
    instrument_id: int
    currency: str
    unleveraged: bool
    underlying: bool
    source: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionEvidence:
    instrument_id: int
    is_open: bool
    observed_at: datetime
    valid_until: datetime
    source: str


@dataclass(frozen=True)
class Features:
    sma: float
    ema: float
    rsi: float
    macd: float
    macd_signal: float
    atr: float
    relative_volume: float | None
    volatility: float
    momentum: float
    previous_high: float
    close: float


@dataclass(frozen=True)
class FundamentalAnalysis:
    instrument_id: int
    version: str
    source: str
    as_of: datetime
    expires_at: datetime
    # Immutable facts for a future Earnings Agent; no inferred earnings data.
    facts: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Opportunity:
    instrument: Instrument
    score: float
    contributions: tuple[tuple[str, float], ...]
    features: Features
    quote: Quote
    created_at: datetime
    expires_at: datetime
    minimum_cash_usd: Decimal
    budget_usd: Decimal
    fundamentals: FundamentalAnalysis | None = None
    execution_authorized: bool = False
    contract: BarContract = HOURLY_BASELINE

    def valid_at(self, now: datetime) -> bool:
        return aware(now) and self.created_at <= now < self.expires_at


@dataclass(frozen=True)
class ScanResult:
    opportunities: tuple[Opportunity, ...]
    rejected: tuple[tuple[int, str], ...]
    discovered: int


class MarketSource(Protocol):
    async def discover(self) -> tuple[Instrument, ...]: ...
    async def quotes(self, ids: tuple[int, ...]) -> dict[int, Quote]: ...
    async def history(self, instrument_id: int) -> tuple[Candle, ...]: ...
    async def eligibility(self, ids: tuple[int, ...]) -> dict[int, Eligibility]: ...


class EvidenceProvider(Protocol):
    async def product(self, instrument: Instrument, now: datetime) -> ProductEvidence: ...
    async def session(self, instrument: Instrument, now: datetime) -> SessionEvidence: ...
    async def history_complete(
        self, instrument: Instrument, candles: tuple[Candle, ...], now: datetime
    ) -> bool: ...


class EarningsProvider(Protocol):
    async def analysis(self, instrument_id: int, now: datetime) -> FundamentalAnalysis | None: ...


class StrategyAgent(Protocol):
    # Consumer must recheck expiry and produce its own stop/size; no order authority.
    def consider(self, opportunity: Opportunity, now: datetime) -> Proposal | None: ...


class RiskReviewer(Protocol):
    def evaluate(
        self, proposal: Proposal, account: AccountSnapshot, *, now: datetime
    ) -> Decision: ...
