"""Evidence gate into Phase 6. Daily observations cannot impersonate hourly quote events."""

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from ..backtest.engine import Backtest, Result
from ..backtest.models import Dataset, Plan
from ..scanner.models import Candle
from ..strategy.models import ObservedBar
from .models import ExchangeCalendar, History
from .quality import inspect


def blockers(history: History) -> tuple[str, ...]:
    reasons = []
    if history.source.classification != "historical_observation":
        reasons.append("SYNTHETIC_SOURCE")
    if history.resolution != "1h":
        reasons.append("STRATEGY_REQUIRES_HOURLY_HISTORY")
    if history.basis != "raw":
        reasons.append("REPLAY_REQUIRES_RAW_PRICES")
    if not history.point_in_time_verified:
        reasons.append("ORIGINAL_AVAILABILITY_UNVERIFIED")
    if not history.actions_complete:
        reasons.append("CORPORATE_ACTION_COVERAGE_INCOMPLETE")
    if history.actions:
        reasons.append("REPLAY_CORPORATE_ACTION_ACCOUNTING_UNIMPLEMENTED")
    return tuple(reasons)


def run_verified(
    history: History,
    calendar: ExchangeCalendar,
    data: Dataset,
    plan: Plan,
    directory: Path,
    *,
    review_reference: str,
    coverage_start: date,
    coverage_end: date,
    audit_at: datetime,
) -> Result:
    """Caller supplies independently reviewed quote/FX/product/session/earnings events.

    This does not manufacture such evidence from candles, infer eligibility or relax risk.
    Review declarations are attestations, not cryptographic proof of a provider's history.
    """
    quality = inspect(history, calendar, start=coverage_start, end=coverage_end, as_of=audit_at)
    if (
        blockers(history)
        or not quality.clean
        or not review_reference.strip()
        or data.provenance.kind != "historical_verified"
        or data.provenance.review_reference != review_reference
        or data.instrument.symbol != history.symbol
        or history.currency != "USD"
        or not history.bars
        or history.bars[-1].end < data.end
    ):
        raise ValueError("Historical replay evidence incomplete or incompatible.")
    bars = tuple(
        ObservedBar(
            Candle(
                b.start,
                float(b.open),
                float(b.high),
                float(b.low),
                float(b.close),
                None if b.volume is None else float(b.volume),
            ),
            b.known_at,
        )
        for b in history.bars
    )
    sessions = calendar.sessions(data.start.date(), data.end.date())
    for tick in data.ticks:
        if tick.evidence.session.is_open and not any(
            session.opens <= tick.at < session.closes
            and tick.evidence.session_close == session.closes
            for session in sessions
        ):
            raise ValueError("Replay session evidence disagrees with reviewed calendar.")
    provenance = replace(
        data.provenance,
        source=f"{data.provenance.source}; candles={history.source.url}; "
        f"sha256={history.source.raw_sha256}",
        limitations=data.provenance.limitations
        + ("Candle availability and action completeness require external review.",),
    )
    candidate = replace(data, history=bars, provenance=provenance)
    candidate.validate()
    return Backtest(candidate, plan).run(directory)
