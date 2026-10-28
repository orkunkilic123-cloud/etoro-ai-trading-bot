"""Offline five-minute research qualification. No conversion into strategy/order inputs."""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from ..risk.models import money
from ..scanner.models import aware
from ..timeframes import FIVE_MINUTE_RESEARCH, BarContract
from .alpaca import load_download
from .archive import Archive
from .calendar import NYSE2026
from .models import Bar, Source
from .replay import blockers


@dataclass(frozen=True)
class SessionWindow:
    day: date
    opens: datetime
    closes: datetime
    calendar_source: str
    calendar_verified_at: datetime
    version: str = "XNYS-regular-2026-v1"
    exchange: str = "XNYS"
    timezone: str = "America/New_York"

    def __post_init__(self) -> None:
        if (
            self.version != "XNYS-regular-2026-v1"
            or self.exchange != "XNYS"
            or self.timezone != "America/New_York"
            or self.day.year != 2026
            or not all(aware(t) for t in (self.opens, self.closes, self.calendar_verified_at))
            or not self.opens < self.closes
            or not self.calendar_source
        ):
            raise ValueError("INVALID_RESEARCH_SESSION")
        expected = NYSE2026(verified_at=self.calendar_verified_at).sessions(self.day, self.day)
        if (
            len(expected) != 1
            or self.opens != expected[0].opens
            or self.closes != expected[0].closes
            or self.calendar_source != NYSE2026.source_url
        ):
            raise ValueError("RESEARCH_SESSION_DISAGREES_WITH_CALENDAR")


@dataclass(frozen=True)
class ResearchBar:
    observation: Bar
    completed_at: datetime  # Economic interval completion, NOT original publication/finality.
    first_known_at: datetime
    session: SessionWindow
    source_snapshot: str

    def __post_init__(self) -> None:
        bar = self.observation
        self.session.__post_init__()
        if (
            not all(aware(t) for t in (bar.start, bar.end, self.completed_at, self.first_known_at))
            or self.completed_at != bar.end
            or self.first_known_at != bar.known_at
            or not self.session.opens <= bar.start < bar.end <= self.session.closes
            or bar.end - bar.start != timedelta(minutes=5)
            or (bar.start - self.session.opens).total_seconds() % 300 != 0
            or self.first_known_at < self.completed_at
            or not re.fullmatch(r"[0-9a-f]{64}", self.source_snapshot)
        ):
            raise ValueError("INVALID_RESEARCH_BAR_CONTRACT")


@dataclass(frozen=True)
class ResearchSeries:
    contract: BarContract
    symbol: str
    source: Source
    snapshot: str
    bars: tuple[ResearchBar, ...]
    sessions: tuple[SessionWindow, ...]
    replay_blockers: tuple[str, ...]

    @property
    def execution_authorized(self) -> bool:
        return False

    def visible_at(
        self, decision_at: datetime, *, max_age_seconds: int = 300
    ) -> tuple[ResearchBar, ...]:
        """Future research consumers get only demonstrably available, completed observations."""
        if (
            not aware(decision_at)
            or type(max_age_seconds) is not int
            or not 1 <= max_age_seconds <= 86400
        ):
            raise ValueError("INVALID_RESEARCH_DECISION_TIME")
        at = decision_at.astimezone(UTC)
        visible = tuple(b for b in self.bars if b.completed_at <= at and b.first_known_at <= at)
        if not visible or at - visible[-1].completed_at > timedelta(seconds=max_age_seconds):
            raise ValueError("RESEARCH_DATA_UNAVAILABLE_OR_STALE")
        return visible


def qualify_download(
    archive: Archive,
    snapshot: str,
    symbol: str,
    *,
    start: date,
    end: date,
    audit_at: datetime,
    calendar: NYSE2026,
    contract: BarContract = FIVE_MINUTE_RESEARCH,
    max_snapshot_age_seconds: int = 86400,
) -> ResearchSeries:
    """Fail closed on any missing/off-grid session bar; retain original source availability.

    This is structural coverage of the specified window, never eligibility, licensing,
    original publication verification, strategy readiness or performance evidence.
    """
    if type(contract) is not BarContract:
        raise ValueError("INVALID_TEMPORAL_CONTRACT")
    contract.__post_init__()
    if (
        contract != FIVE_MINUTE_RESEARCH
        or type(calendar) is not NYSE2026
        or not aware(audit_at)
        or type(max_snapshot_age_seconds) is not int
        or not 1 <= max_snapshot_age_seconds <= 7 * 86400
        or not 0 <= (end - start).days <= 365
        or not aware(calendar.verified_at)
        or calendar.verified_at > audit_at
    ):
        raise ValueError("INVALID_RESEARCH_QUALIFICATION_CONTRACT")
    history = load_download(archive, snapshot, symbol, exchange=contract.exchange)
    source = history.source
    if (
        history.resolution != contract.timeframe.resolution
        or history.basis != "raw"
        or source.provider != "alpaca-iex-download-5min-v1"
        or not aware(source.retrieved_at)
        or not timedelta(0)
        <= audit_at - source.retrieved_at
        <= timedelta(seconds=max_snapshot_age_seconds)
        or not re.fullmatch(r"[0-9a-f]{64}", source.raw_sha256)
    ):
        raise ValueError("RESEARCH_SOURCE_STALE_OR_INCOMPATIBLE")
    sessions = tuple(
        SessionWindow(s.day, s.opens, s.closes, calendar.source_url, calendar.verified_at)
        for s in calendar.sessions(start, end)
    )
    if not sessions or any(s.closes > audit_at for s in sessions):
        raise ValueError("RESEARCH_WINDOW_INCOMPLETE")
    grid: dict[datetime, SessionWindow] = {}
    for session in sessions:
        point = session.opens
        while point + contract.timeframe.duration <= session.closes:
            grid[point] = session
            point += contract.timeframe.duration
    result = []
    previous_end: datetime | None = None
    for bar in history.bars:
        if not all(aware(t) for t in (bar.start, bar.end, bar.known_at)):
            raise ValueError("INVALID_RESEARCH_BAR_TIME")
        begin, finish, known = (t.astimezone(UTC) for t in (bar.start, bar.end, bar.known_at))
        if (
            begin not in grid
            or finish != begin + contract.timeframe.duration
            or not finish <= known <= source.retrieved_at <= audit_at
            or previous_end is not None
            and begin < previous_end
            or not all(money(v, positive=True) for v in (bar.open, bar.high, bar.low, bar.close))
            or bar.volume is None
            or not money(bar.volume)
            or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            or bar.basis != "raw"
        ):
            raise ValueError("INVALID_OR_INCOMPLETE_RESEARCH_BAR")
        result.append(ResearchBar(bar, finish, known, grid[begin], snapshot))
        previous_end = finish
    if len(result) != len(grid) or {b.observation.start for b in result} != set(grid):
        raise ValueError("MISSING_RESEARCH_SESSION_BARS")
    # Five-minute research qualification does not relax the existing hourly replay gate.
    return ResearchSeries(
        contract, symbol, source, snapshot, tuple(result), sessions, blockers(history)
    )


def research_report(series: ResearchSeries) -> dict[str, object]:
    """A small provenance/coverage report, never a profitability or execution report."""
    return {
        "schema": "intraday-qualification-v1",
        "contract": asdict(series.contract),
        "symbol": series.symbol,
        "snapshot": series.snapshot,
        "source": asdict(series.source),
        "sessions": [asdict(s) for s in series.sessions],
        "bars": len(series.bars),
        "first_start": series.bars[0].observation.start,
        "last_end": series.bars[-1].observation.end,
        "structural_qualification": True,
        "execution_authorized": False,
        "replay_blockers": series.replay_blockers,
        "availability": "retrieval-backed; original publication and revisions unverified",
    }
