"""Position monitoring produces advice only; no broker stop modification or closing API."""

import sqlite3
from datetime import datetime, timedelta
from decimal import Context as DecimalContext
from decimal import Decimal, DecimalException, localcontext

from ..risk.models import identifier, money
from ..scanner.indicators import calculate
from ..scanner.models import Quote, aware, fresh
from ..timeframes import require_hourly_baseline
from .engine import earnings_safe
from .journal import Journal, digest
from .models import Evidence, ExitAdvice, ObservedBar, Position, Strategy, StrategyError

D = Decimal


class ExitMonitor:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    def evaluate(
        self,
        position: Position,
        quote: Quote,
        bars: tuple[ObservedBar, ...],
        evidence: Evidence,
        *,
        now: datetime,
    ) -> ExitAdvice:
        if not aware(now):
            return ExitAdvice("blocked", ("INVALID_TIME",))
        signal = digest({"position": position.position_id})
        try:
            with localcontext(DecimalContext(prec=60)):
                advice = self._evaluate(position, quote, bars, evidence, now)
        except StrategyError as error:
            advice = ExitAdvice("blocked", (str(error),))
        except (ValueError, TypeError, AttributeError, DecimalException, OverflowError):
            advice = ExitAdvice("blocked", ("INVALID_POSITION_INPUT",))
        try:
            self.journal.record(
                signal,
                "exit_" + advice.action,
                {"reasons": advice.reasons, "proposed_stop": advice.proposed_stop},
                now,
            )
        except (sqlite3.Error, OSError, StrategyError):
            return ExitAdvice("blocked", ("JOURNAL_UNAVAILABLE",))
        return advice

    def _evaluate(
        self, p: Position, q: Quote, bars: tuple[ObservedBar, ...], e: Evidence, now: datetime
    ) -> ExitAdvice:
        for observed in bars:
            require_hourly_baseline(observed.candle.contract)
        c, r = p.candidate, p.candidate.rules
        if (
            not identifier(p.position_id)
            or not aware(p.opened_at)
            or not c.decision_at <= p.opened_at <= now
            or c.proposal.leverage != 1
            or c.proposal.side != "buy"
            or c.proposal.underlying_verified is not True
            or not fresh(p.observed_at, now, 60)
            or not fresh(p.risk_observed_at, now, 60)
            or not aware(p.peak_observed_at)
            or not p.opened_at <= p.peak_observed_at <= now
            or not all(
                money(v, positive=True) for v in (p.units, p.entry, p.active_stop, p.peak_bid)
            )
            or c.proposal.stop_loss is None
            or p.active_stop < c.proposal.stop_loss
            or p.units > c.proposal.units
        ):
            raise StrategyError("POSITION_OR_RISK_EVIDENCE_INVALID")
        if (
            q.instrument_id != c.proposal.instrument_id
            or q.quote_type != "realtime"
            or not fresh(q.observed_at, now, 60)
            or not money(q.bid, positive=True)
            or not money(q.ask, positive=True)
            or q.bid > q.ask
        ):
            raise StrategyError("INVALID_OR_STALE_QUOTE")
        if (
            not fresh(e.available_at, now, 60)
            or e.session.instrument_id != q.instrument_id
            or e.session.is_open is not True
            or not fresh(e.session.observed_at, now, 60)
            or not e.session.source
            or not aware(e.session.valid_until)
            or e.session.valid_until <= now
        ):
            raise StrategyError("MARKET_CLOSED_OR_UNKNOWN")
        # Safety exits do not depend on a still-valid scanner entry signal or profitable outcome.
        if q.bid <= p.active_stop:
            return ExitAdvice("propose_close", ("STOP_LOSS",), p.active_stop)
        if p.risk_valid is not True:
            return ExitAdvice("propose_close", ("RISK_REVIEW_REQUIRED",), p.active_stop)
        if c.exit_deadline is not None and now >= c.exit_deadline:
            return ExitAdvice("propose_close", ("INTRADAY_SESSION_EXIT",), p.active_stop)
        through = c.exit_deadline or now + timedelta(seconds=r.swing_horizon_seconds)
        try:
            earnings_safe(e.earnings, q.instrument_id, now, through, r.earnings_buffer_seconds)
        except StrategyError as error:
            if str(error) == "EARNINGS_BLACKOUT":
                return ExitAdvice("propose_close", ("EARNINGS_BLACKOUT",), p.active_stop)
            raise
        usable = []
        for bar in bars:
            if not aware(bar.available_at) or not aware(bar.candle.start):
                raise StrategyError("INVALID_BAR_TIME")
            end = bar.candle.start + timedelta(hours=1)
            if bar.available_at < end:
                raise StrategyError("BAR_AVAILABLE_BEFORE_COMPLETION")
            if end <= now and bar.available_at <= now:
                usable.append(bar.candle)
        if not usable or not fresh(usable[-1].start + timedelta(hours=1), now, 4 * 86400):
            raise StrategyError("STALE_HISTORY")
        f = calculate(tuple(usable))
        stop = p.active_stop
        if r.trailing_atr is not None:
            stop = max(stop, max(p.peak_bid, q.bid) - D(str(f.atr)) * r.trailing_atr)
        if q.bid <= stop:
            return ExitAdvice("propose_close", ("TRAILING_STOP",), stop)
        if c.take_profit is not None and q.bid >= c.take_profit:
            return ExitAdvice("propose_close", ("CONFIGURED_TAKE_PROFIT",), stop)
        if r.exit_at_mean and c.strategy == Strategy.REVERSION and q.bid >= D(str(f.sma)):
            return ExitAdvice("propose_close", ("MEAN_REVERSION_COMPLETE",), stop)
        if r.exit_on_trend_loss and c.strategy != Strategy.REVERSION and q.bid < D(str(f.ema)):
            return ExitAdvice("propose_close", ("TREND_INVALIDATED",), stop)
        return ExitAdvice("hold", ("EXIT_RULES_VALID",), stop)
