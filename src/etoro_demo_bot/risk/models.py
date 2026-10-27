"""Normalized USD inputs; no broker requests or order payloads."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


def money(value: object, *, positive: bool = False) -> bool:
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and len(value.as_tuple().digits) <= 24
        and abs(int(value.as_tuple().exponent)) <= 12
        and (value > 0 if positive else value >= 0)
    )


def identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value.isascii()
        and all(c.isalnum() or c in "_-" for c in value)
    )


@dataclass(frozen=True)
class RiskPolicy:
    max_position_fraction: Decimal = Decimal("0.20")
    max_exposure_fraction: Decimal = Decimal("0.80")
    max_instrument_fraction: Decimal = Decimal("0.25")
    max_concurrent_positions: int = 5
    max_age_seconds: int = 60

    def __post_init__(self) -> None:
        for value in (
            self.max_position_fraction,
            self.max_exposure_fraction,
            self.max_instrument_fraction,
        ):
            if not money(value, positive=True) or value > 1:
                raise ValueError("Exposure limits must be Decimal fractions in (0, 1].")
        for count in (self.max_concurrent_positions, self.max_age_seconds):
            if type(count) is not int or not 1 <= count <= 86400:
                raise ValueError("Count and age limits must be positive bounded integers.")


@dataclass(frozen=True)
class Exposure:
    instrument_id: int
    notional: Decimal
    positions: int


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    equity: Decimal
    available_balance: Decimal
    exposures: tuple[Exposure, ...]
    observed_at: datetime
    demo: bool = False
    currency: str = "USD"
    complete: bool = False
    cash_flows_reconciled: bool = False


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    instrument_id: int
    units: Decimal
    price: Decimal | None
    stop_loss: Decimal | None
    quoted_at: datetime
    # Conservative total fee/slippage estimate, supplied explicitly by caller.
    cost_buffer: Decimal
    leverage: Decimal = Decimal("1")
    side: str = "buy"
    settlement: str = "real"
    underlying_verified: bool = False
    quote_type: str = "realtime"


@dataclass(frozen=True)
class Decision:
    passed: bool
    reasons: tuple[str, ...]
    risk_amount: Decimal | None = None
    notional: Decimal | None = None
    # A risk pass is never permission to send an order.
    execution_authorized: bool = False
