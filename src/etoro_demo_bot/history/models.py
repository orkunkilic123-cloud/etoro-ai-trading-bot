"""Provider-neutral historical observations; retrieved history is not a point-in-time archive."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Source:
    provider: str
    url: str
    terms_url: str
    retrieved_at: datetime
    raw_sha256: str
    classification: str  # historical_observation or synthetic; never automatically verified replay
    license_note: str
    redistribution_allowed: bool = False
    symbol: str = ""


@dataclass(frozen=True)
class Bar:
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    # First demonstrable availability, not an assumed publication time at session close.
    known_at: datetime
    basis: str


@dataclass(frozen=True)
class Action:
    symbol: str
    kind: str  # split or cash_dividend
    effective_at: datetime
    known_at: datetime
    value: Decimal  # new shares per old share, or cash per share
    source: str


@dataclass(frozen=True)
class History:
    symbol: str
    exchange: str
    currency: str
    resolution: str
    basis: str
    bars: tuple[Bar, ...]
    source: Source
    actions: tuple[Action, ...] = ()
    actions_complete: bool = False
    point_in_time_verified: bool = False


class HistoricalProvider(Protocol):
    def parse(self, raw: bytes, source: Source) -> History: ...


@dataclass(frozen=True)
class Session:
    day: date
    opens: datetime
    closes: datetime


class ExchangeCalendar(Protocol):
    source_url: str
    verified_at: datetime

    def sessions(self, start: date, end: date) -> tuple[Session, ...]: ...


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str
    blocking: bool = True


@dataclass(frozen=True)
class Quality:
    findings: tuple[Finding, ...]
    rows: int
    first: date | None
    last: date | None

    @property
    def clean(self) -> bool:
        return not any(f.blocking for f in self.findings)
