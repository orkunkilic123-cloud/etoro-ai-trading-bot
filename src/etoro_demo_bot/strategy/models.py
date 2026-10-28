"""Immutable, offline strategy contracts. Nothing here represents a broker order."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from ..risk.models import AccountSnapshot, Decision, Proposal, money
from ..scanner.analysis import Budget
from ..scanner.models import Candle, Eligibility, Opportunity, ProductEvidence, SessionEvidence
from ..timeframes import HOURLY_BASELINE, BarContract

D = Decimal


class StrategyError(ValueError):
    """Stable, sanitized decision reason."""


class Style(StrEnum):
    INTRADAY = "intraday"
    SWING = "short_swing"


class Strategy(StrEnum):
    BREAKOUT = "momentum_breakout"
    TREND = "trend_following"
    REVERSION = "mean_reversion"


@dataclass(frozen=True)
class Rules:
    version: str = "v1"
    style: Style = Style.INTRADAY
    enabled: tuple[Strategy, ...] = tuple(Strategy)
    minimum_score: Decimal = D("15")
    minimum_momentum: Decimal = D("0.02")
    minimum_relative_volume: Decimal = D("1.2")
    oversold_rsi: Decimal = D("30")
    max_volatility: Decimal = D("0.05")
    max_spread_fraction: Decimal = D("0.005")
    min_daily_dollar_volume: Decimal = D("1000000")
    max_cost_fraction: Decimal = D("0.02")
    stop_atr: Decimal = D("2")
    trailing_atr: Decimal | None = D("3")
    # Optional target in multiples of initial risk; default lets winners run.
    take_profit_r: Decimal | None = None
    risk_fraction: Decimal = D("0.005")
    allocation_fraction: Decimal = D("0.20")
    signal_ttl_seconds: int = 30
    earnings_buffer_seconds: int = 86400
    swing_horizon_seconds: int = 3 * 86400
    close_buffer_seconds: int = 900
    exit_on_trend_loss: bool = True
    exit_at_mean: bool = True

    def __post_init__(self) -> None:
        if (
            not self.version
            or len(self.version) > 64
            or not self.version.isascii()
            or not all(c.isalnum() or c in "_-." for c in self.version)
            or not isinstance(self.style, Style)
            or not self.enabled
            or len(set(self.enabled)) != len(self.enabled)
            or any(not isinstance(s, Strategy) for s in self.enabled)
        ):
            raise StrategyError("INVALID_RULES")
        for value in (
            self.minimum_score,
            self.minimum_momentum,
            self.minimum_relative_volume,
            self.oversold_rsi,
            self.max_volatility,
            self.max_spread_fraction,
            self.min_daily_dollar_volume,
            self.max_cost_fraction,
            self.stop_atr,
            self.risk_fraction,
            self.allocation_fraction,
        ):
            if not money(value, positive=True):
                raise StrategyError("INVALID_RULES")
        for optional_value in (self.trailing_atr, self.take_profit_r):
            if optional_value is not None and not money(optional_value, positive=True):
                raise StrategyError("INVALID_RULES")
        if (
            self.minimum_score > 100
            or self.oversold_rsi >= 50
            or self.risk_fraction > D(".01")
            or self.allocation_fraction > 1
            or self.max_spread_fraction >= 1
            or self.max_cost_fraction >= 1
        ):
            raise StrategyError("INVALID_RULES")
        for count in (
            self.signal_ttl_seconds,
            self.earnings_buffer_seconds,
            self.swing_horizon_seconds,
            self.close_buffer_seconds,
        ):
            if type(count) is not int or not 1 <= count <= 7 * 86400:
                raise StrategyError("INVALID_RULES")
        if type(self.exit_on_trend_loss) is not bool or type(self.exit_at_mean) is not bool:
            raise StrategyError("INVALID_RULES")
        if self.signal_ttl_seconds > 60:
            raise StrategyError("INVALID_RULES")


@dataclass(frozen=True)
class ObservedBar:
    candle: Candle
    available_at: datetime


@dataclass(frozen=True)
class EarningsWindow:
    instrument_id: int
    known_at: datetime
    covered_from: datetime
    covered_until: datetime
    announcements: tuple[datetime, ...]
    source: str
    complete: bool = False


class EarningsCalendar(Protocol):
    def window(self, instrument_id: int, *, as_of: datetime) -> EarningsWindow: ...


@dataclass(frozen=True)
class Evidence:
    eligibility: Eligibility
    product: ProductEvidence
    session: SessionEvidence
    budget: Budget
    # Availability of this complete evidence snapshot, including revisions and costs.
    available_at: datetime
    session_close: datetime
    daily_dollar_volume: Decimal
    liquidity_observed_at: datetime
    quantity_step: Decimal
    quantity_step_verified: bool
    earnings: EarningsWindow


@dataclass(frozen=True)
class Context:
    opportunity: Opportunity
    bars: tuple[ObservedBar, ...]
    evidence: Evidence
    account: AccountSnapshot
    contract: BarContract = HOURLY_BASELINE


@dataclass(frozen=True)
class Candidate:
    proposal: Proposal
    account_id: str
    strategy: Strategy
    rules: Rules
    rules_digest: str
    decision_at: datetime
    expires_at: datetime
    entry_deadline: datetime
    exit_deadline: datetime | None
    take_profit: Decimal | None
    signal_id: str

    # No constructor switch can grant authority.
    @property
    def execution_authorized(self) -> bool:
        return False


@dataclass(frozen=True)
class Outcome:
    status: str
    reasons: tuple[str, ...]
    candidate: Candidate | None = None


@dataclass(frozen=True)
class RiskReview:
    decision: Decision
    proposal: Proposal

    @property
    def execution_authorized(self) -> bool:
        return False


@dataclass(frozen=True)
class Position:
    position_id: str
    candidate: Candidate
    opened_at: datetime
    observed_at: datetime
    units: Decimal
    entry: Decimal
    active_stop: Decimal
    peak_bid: Decimal
    peak_observed_at: datetime
    # Updated position-level/account-level risk monitoring is a separate trusted input.
    risk_valid: bool
    risk_observed_at: datetime


@dataclass(frozen=True)
class ExitAdvice:
    action: str  # hold, propose_close, blocked; never an order
    reasons: tuple[str, ...]
    proposed_stop: Decimal | None = None

    @property
    def execution_authorized(self) -> bool:
        return False
