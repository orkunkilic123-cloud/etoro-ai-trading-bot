"""Immutable execution tickets and explicit, expiring Demo identity evidence."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from ..risk import Proposal


class ExecutionError(Exception):
    """Sanitized failure. Never contains broker response bodies or secrets."""


class RateLimited(ExecutionError):
    """A local cooldown prevented dispatch; no request was sent."""


class OrderState(StrEnum):
    PROPOSED = "proposed"
    RISK_APPROVED = "risk-approved"
    SUBMITTED = "submitted"
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially-filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExecutionConfig:
    enabled: bool = False
    # Deliberately no autonomous authorization mode.


@dataclass(frozen=True)
class DemoIdentity:
    account_id: str
    customer_id: int
    broker_account_id: int
    credential_digest: str
    expires_at: datetime
    demo_confirmed: bool = False


@dataclass(frozen=True)
class PositionEvidence:
    account_id: str
    position_id: int
    instrument_id: int
    units: Decimal
    observed_at: datetime
    underlying_long_unleveraged: bool = False


@dataclass(frozen=True)
class Ticket:
    account_id: str
    proposal: Proposal
    action: str = "open"
    position_id: int | None = None
    asset_currency: str = "unknown"

    def canonical(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


@dataclass(frozen=True)
class OrderRecord:
    ticket_id: str
    state: OrderState
    reference_id: str
    broker_id: int | None
    terminal: bool
    broker_status: int | None
    executed_units: Decimal
    reason: str
