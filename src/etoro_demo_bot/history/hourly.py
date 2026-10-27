"""Offline hourly study qualification. Coverage is not proof of licensing or profitability."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from ..backtest.engine import Result
from ..backtest.models import Dataset, Plan
from ..scanner.models import aware
from ..strategy.models import Strategy
from .archive import Archive
from .models import ExchangeCalendar, History
from .providers import CSVHistory
from .quality import inspect
from .replay import blockers, run_verified

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class CoveragePolicy:
    # Calendar days, not an unsupported guarantee of "six months" from a vendor.
    minimum_days: int = 183
    minimum_sessions: int = 120
    warmup_bars: int = 35
    minimum_partition_sessions: int = 20

    def __post_init__(self) -> None:
        values = (
            self.minimum_days,
            self.minimum_sessions,
            self.warmup_bars,
            self.minimum_partition_sessions,
        )
        if any(type(v) is not int or v < 1 for v in values) or self.warmup_bars < 35:
            raise ValueError("Invalid hourly coverage policy; strategies require 35 warm-up bars.")


@dataclass(frozen=True)
class StudyWindow:
    start: date
    end: date  # Inclusive requested calendar coverage, including warm-up.
    train_at: datetime
    validation_at: datetime
    test_at: datetime
    finish_at: datetime  # Exclusive evaluation boundary.

    def __post_init__(self) -> None:
        times = (self.train_at, self.validation_at, self.test_at, self.finish_at)
        if (
            self.end < self.start
            or not all(aware(t) for t in times)
            or not all(a < b for a, b in zip(times, times[1:], strict=False))
            or self.train_at.date() < self.start
            or self.finish_at.date() > self.end
        ):
            raise ValueError("Study boundaries must be aware, chronological and inside coverage.")


@dataclass(frozen=True)
class HourlyAudit:
    symbol: str
    observed_start: datetime | None
    observed_end: datetime | None
    expected_bars: int
    observed_bars: int
    complete_sessions: int
    omitted_partial_minutes: int
    coverage_errors: tuple[str, ...]
    replay_blockers: tuple[str, ...]
    partition_sessions: tuple[int, ...]
    warmup_counts: tuple[int, ...]

    @property
    def coverage_ok(self) -> bool:
        return not self.coverage_errors


def audit_hourly(
    history: History,
    calendar: ExchangeCalendar,
    window: StudyWindow,
    policy: CoveragePolicy,
    *,
    audit_at: datetime,
) -> HourlyAudit:
    if not aware(audit_at) or not aware(history.source.retrieved_at):
        raise ValueError("Audit and retrieval times must be aware.")
    errors: list[str] = []
    sessions = calendar.sessions(window.start, window.end)
    quality = inspect(history, calendar, start=window.start, end=window.end, as_of=audit_at)
    errors.extend(f.code for f in quality.findings if f.blocking)
    if history.resolution != "1h":
        errors.append("HOURLY_RESOLUTION_REQUIRED")
    if history.exchange != "XNYS" or history.currency != "USD":
        errors.append("UNSUPPORTED_MARKET")
    if history.source.retrieved_at > audit_at:
        errors.append("FUTURE_RETRIEVAL")
    if window.finish_at > audit_at:
        errors.append("INCOMPLETE_STUDY_WINDOW")
    grid: set[datetime] = set()
    session_grids = []
    partial_minutes = 0
    for session in sessions:
        points = set()
        point = session.opens
        while point + HOUR <= session.closes:
            points.add(point)
            point += HOUR
        partial_minutes += int((session.closes - point).total_seconds() // 60)
        session_grids.append((session, points))
        grid.update(points)
    observed = {b.start for b in history.bars if aware(b.start)}
    if observed - grid:
        errors.append("OFF_GRID_OR_PARTIAL_CANDLE")
    if grid - observed:
        errors.append("MISSING_HOURLY_CANDLES")
    if any(aware(b.known_at) and b.known_at > history.source.retrieved_at for b in history.bars):
        errors.append("AVAILABILITY_AFTER_RETRIEVAL")
    complete = sum(bool(points) and points <= observed for _, points in session_grids)
    days = (max(observed).date() - min(observed).date()).days + 1 if observed else 0
    if days < policy.minimum_days:
        errors.append("INSUFFICIENT_CALENDAR_SPAN")
    if complete < policy.minimum_sessions:
        errors.append("INSUFFICIENT_SESSIONS")
    boundaries = (window.train_at, window.validation_at, window.test_at, window.finish_at)
    partitions = tuple(
        sum(start <= s.opens and s.closes <= end for s in sessions)
        for start, end in zip(boundaries, boundaries[1:], strict=False)
    )
    if any(n < policy.minimum_partition_sessions for n in partitions):
        errors.append("INSUFFICIENT_PARTITION_SESSIONS")
    warmups = tuple(
        sum(
            aware(b.end) and aware(b.known_at) and b.end <= at and b.known_at <= at
            for b in history.bars
        )
        for at in boundaries[:-1]
    )
    if any(n < policy.warmup_bars for n in warmups):
        errors.append("INSUFFICIENT_POINT_IN_TIME_WARMUP")
    return HourlyAudit(
        history.symbol,
        min(observed) if observed else None,
        max((b.end for b in history.bars if aware(b.end)), default=None),
        len(grid),
        len(observed & grid),
        complete,
        partial_minutes,
        tuple(sorted(set(errors))),
        blockers(history),
        partitions,
        warmups,
    )


def cached_hourly(
    archive: Archive, snapshot: str, *, exchange: str, currency: str, basis: str
) -> History:
    """Import an already licensed normalized CSV snapshot; no remote provider is implied.

    Source metadata is supplied by the importer and must be independently reviewed.
    This never promotes historical_observation to point-in-time verified evidence.
    """
    raw, source = archive.get(snapshot)
    return CSVHistory(
        symbol=source.symbol, exchange=exchange, currency=currency, resolution="1h", basis=basis
    ).parse(raw, source)


def run_hourly_study(
    history: History,
    calendar: ExchangeCalendar,
    data: Dataset,
    plan: Plan,
    directory: Path,
    *,
    window: StudyWindow,
    policy: CoveragePolicy,
    audit_at: datetime,
    review_reference: str,
) -> Result:
    """Gate a single predeclared replay; train-only selection remains in backtest.evaluation."""
    audit = audit_hourly(history, calendar, window, policy, audit_at=audit_at)
    if not audit.coverage_ok or audit.replay_blockers:
        raise ValueError("Hourly study evidence or coverage is insufficient.")
    if not window.train_at <= data.start < data.end < window.finish_at:
        raise ValueError("Replay must stay inside the predeclared evaluation window.")
    return run_verified(
        history,
        calendar,
        data,
        plan,
        directory,
        review_reference=review_reference,
        coverage_start=window.start,
        coverage_end=window.end,
        audit_at=audit_at,
    )


def readiness_manifest(
    history: History,
    calendar: ExchangeCalendar,
    window: StudyWindow,
    policy: CoveragePolicy,
    *,
    audit_at: datetime,
    snapshot: str,
) -> dict[str, object]:
    audit = audit_hourly(history, calendar, window, policy, audit_at=audit_at)
    return {
        "schema": "hourly-readiness-v1",
        "snapshot": snapshot,
        "audit_at": audit_at,
        "source": asdict(history.source),
        "window": asdict(window),
        "policy": asdict(policy),
        "calendar_url": calendar.source_url,
        "calendar_verified_at": calendar.verified_at,
        "timezone": "America/New_York",
        "bar_alignment": "regular-session-open/full-hours-only",
        "audit": asdict(audit),
        "strategies": [s.value for s in Strategy],
        "comparisons": [
            {
                "strategy": s,
                "initial_eur": eur,
                "status": "not_run",
                "total_return": None,
                "maximum_drawdown": None,
                "win_rate": None,
                "profit_factor": None,
                "number_of_trades": None,
                "costs": None,
            }
            for eur in (500, 1000)
            for s in [*(s.value for s in Strategy), "buy_and_hold", "cash"]
        ],
        "limitations": [
            "Coverage audit only: no performance results or execution permission.",
            "Quote/FX/eligibility/earnings/cost review remains required.",
            "Fixed-symbol studies do not eliminate survivorship bias.",
        ],
    }
