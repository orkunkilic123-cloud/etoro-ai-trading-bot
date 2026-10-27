"""Explicit diagnostics and point-in-time split adjustment without future-event leakage."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from ..scanner.models import aware
from .models import Action, Bar, ExchangeCalendar, Finding, History, Quality

D = Decimal
DEFAULT_JUMP = D(".25")


def inspect(
    history: History,
    calendar: ExchangeCalendar,
    *,
    start: date,
    end: date,
    as_of: datetime,
    require_current: bool = False,
    jump_fraction: Decimal = DEFAULT_JUMP,
) -> Quality:
    if not aware(as_of) or not jump_fraction.is_finite() or jump_fraction <= 0:
        raise ValueError("Invalid quality policy.")
    findings = []
    seen = set()
    previous = None
    if history.resolution not in ("1d", "1h") or history.basis not in (
        "raw",
        "split_adjusted",
        "total_return_adjusted",
        "unknown",
    ):
        raise ValueError("Unsupported historical resolution or price basis.")
    sessions = calendar.sessions(start, end)
    expected = {s.opens: s for s in sessions if s.closes <= as_of}
    if history.basis == "unknown":
        findings.append(Finding("UNKNOWN_ADJUSTMENTS", "Price basis not verified."))
    if history.basis != "raw" and not history.actions_complete:
        findings.append(
            Finding(
                "ADJUSTMENT_PROVENANCE_MISSING", "Adjusted values lack a complete action ledger."
            )
        )
    if not history.actions_complete:
        findings.append(Finding("ACTIONS_INCOMPLETE", "Split/dividend coverage unknown.", False))
    for bar in history.bars:
        if not all(aware(t) for t in (bar.start, bar.end, bar.known_at)):
            findings.append(Finding("NAIVE_TIME", "Timezone missing."))
            continue
        if bar.start in seen:
            findings.append(Finding("DUPLICATE", "Duplicate candle start."))
        if previous is not None and bar.start <= previous.start:
            findings.append(Finding("UNORDERED", "Unordered candles."))
        seen.add(bar.start)
        if bar.basis != history.basis:
            findings.append(Finding("MIXED_ADJUSTMENTS", "Mixed raw and adjusted candles."))
        values = (bar.open, bar.high, bar.low, bar.close)
        if (
            not all(v.is_finite() and v > 0 for v in values)
            or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        ):
            findings.append(Finding("INVALID_OHLC", "Invalid finite OHLC range."))
            continue
        if bar.volume is None or not bar.volume.is_finite() or bar.volume <= 0:
            findings.append(Finding("MISSING_VOLUME", "Missing, invalid or zero volume."))
        if bar.end <= bar.start or bar.known_at < bar.end:
            findings.append(
                Finding("INVALID_AVAILABILITY", "Candle not complete when allegedly available.")
            )
        if bar.end > as_of:
            findings.append(Finding("INCOMPLETE_CANDLE", "Future or still-forming candle."))
        if history.resolution == "1d" and (
            bar.start not in expected or expected[bar.start].closes != bar.end
        ):
            findings.append(
                Finding(
                    "SESSION_MISMATCH", "Daily boundaries differ from reviewed regular session."
                )
            )
        if history.resolution == "1h":
            inside = any(s.opens <= bar.start < bar.end <= s.closes for s in sessions)
            if not inside or bar.end - bar.start != timedelta(hours=1):
                findings.append(
                    Finding("SESSION_MISMATCH", "Hourly bar outside session or incomplete hour.")
                )
        if previous is not None and abs(bar.open / previous.close - 1) > jump_fraction:
            explaining = [
                a
                for a in history.actions
                if a.kind == "split"
                and a.symbol == history.symbol
                and aware(a.known_at)
                and a.known_at <= as_of
                and a.effective_at == bar.start
                and a.value.is_finite()
                and a.value > 0
                and abs(bar.open * a.value / previous.close - 1) <= D(".02")
            ]
            findings.append(
                Finding(
                    "SPLIT_JUMP" if explaining else "SUSPICIOUS_JUMP",
                    "Opening discontinuity requires action/source review.",
                    not bool(explaining),
                )
            )
        previous = bar
    if history.resolution == "1d":
        missing = set(expected) - seen
    else:
        grid = set()
        for session in sessions:
            point = session.opens
            while point + timedelta(hours=1) <= min(session.closes, as_of):
                grid.add(point)
                point += timedelta(hours=1)
        missing = grid - seen
    if missing:
        findings.append(Finding("MISSING_CANDLES", f"{len(missing)} expected candles absent."))
    if not history.bars:
        findings.append(Finding("EMPTY", "No bars supplied."))
    elif require_current:
        complete = [
            s for s in calendar.sessions(date(as_of.year, 1, 1), as_of.date()) if s.closes <= as_of
        ]
        if complete and max(b.end for b in history.bars) < complete[-1].closes:
            findings.append(Finding("STALE", "Latest completed session is missing."))
    dates = [b.start.date() for b in history.bars if aware(b.start)]
    return Quality(
        tuple(findings),
        len(history.bars),
        min(dates) if dates else None,
        max(dates) if dates else None,
    )


def split_adjust_as_of(
    history: History, actions: tuple[Action, ...], *, as_of: datetime
) -> tuple[Bar, ...]:
    if history.basis != "raw" or not history.actions_complete or not aware(as_of):
        raise ValueError(
            "Point-in-time adjustment requires raw history and a complete action ledger."
        )
    if any(
        not aware(a.known_at)
        or not aware(a.effective_at)
        or not a.source
        or a.symbol != history.symbol
        or a.kind not in ("split", "cash_dividend")
        or not a.value.is_finite()
        or a.value <= 0
        for a in actions
    ):
        raise ValueError("Invalid corporate action evidence.")
    if len({(a.symbol, a.kind, a.effective_at) for a in actions}) != len(actions):
        raise ValueError("Duplicate corporate actions.")
    result = []
    with localcontext() as context:
        context.prec = 60
        for bar in history.bars:
            if bar.end > as_of or bar.known_at > as_of:
                continue
            ratio = D(1)
            available = bar.known_at
            for action in actions:
                if (
                    action.kind == "split"
                    and action.known_at <= as_of
                    and bar.end <= action.effective_at <= as_of
                ):
                    ratio *= action.value
                    available = max(available, action.known_at, action.effective_at)
            result.append(
                replace(
                    bar,
                    open=bar.open / ratio,
                    high=bar.high / ratio,
                    low=bar.low / ratio,
                    close=bar.close / ratio,
                    volume=None if bar.volume is None else bar.volume * ratio,
                    basis="split_adjusted",
                    known_at=available,
                )
            )
    return tuple(result)
