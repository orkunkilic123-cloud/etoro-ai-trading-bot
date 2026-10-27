"""Deterministic strategy selection, conservative sizing and explicit risk-only review."""

import math
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, DecimalException, localcontext
from decimal import Context as DecimalContext

from ..risk.engine import RiskEngine
from ..risk.models import AccountSnapshot, Decision, Proposal, identifier, money
from ..scanner.indicators import calculate
from ..scanner.models import Features, aware, fresh
from .journal import Journal, digest
from .models import (
    Candidate,
    Context,
    EarningsWindow,
    Outcome,
    RiskReview,
    Rules,
    Strategy,
    StrategyError,
    Style,
)
from .rules import matches, regime

D = Decimal
PRECISION = D("0.000000000001")


def earnings_safe(
    window: EarningsWindow, iid: int, now: datetime, through: datetime, buffer: int
) -> None:
    if (
        window.instrument_id != iid
        or window.complete is not True
        or not window.source
        or not fresh(window.known_at, now, 86400)
        or not aware(window.covered_from)
        or not aware(window.covered_until)
        or window.covered_from > now
        or window.covered_until < through + timedelta(seconds=buffer)
    ):
        raise StrategyError("EARNINGS_COVERAGE_UNKNOWN")
    for event in window.announcements:
        if not aware(event):
            raise StrategyError("INVALID_EARNINGS_TIME")
        if now - timedelta(seconds=buffer) <= event <= through + timedelta(seconds=buffer):
            raise StrategyError("EARNINGS_BLACKOUT")


def point_in_time(context: Context, now: datetime) -> tuple[Features, datetime]:
    opportunity = context.opportunity
    if (
        not aware(now)
        or not aware(opportunity.created_at)
        or not aware(opportunity.expires_at)
        or not opportunity.valid_at(now)
        or opportunity.execution_authorized
    ):
        raise StrategyError("EXPIRED_OR_FUTURE_SIGNAL")
    usable = []
    for bar in context.bars:
        if not aware(bar.available_at) or not aware(bar.candle.start):
            raise StrategyError("INVALID_BAR_TIME")
        end = bar.candle.start + timedelta(hours=1)
        if bar.available_at < end:
            raise StrategyError("BAR_AVAILABLE_BEFORE_COMPLETION")
        if end <= opportunity.created_at and bar.available_at <= opportunity.created_at:
            usable.append(bar.candle)
    features = calculate(tuple(usable))
    if features != opportunity.features:
        raise StrategyError("FEATURE_PROVENANCE_MISMATCH")
    if not fresh(usable[-1].start + timedelta(hours=1), now, 4 * 86400):
        raise StrategyError("STALE_HISTORY")
    facts = opportunity.fundamentals
    if facts is not None and (
        facts.instrument_id != opportunity.instrument.instrument_id
        or not aware(facts.as_of)
        or not aware(facts.expires_at)
        or facts.as_of > opportunity.created_at
        or facts.expires_at <= now
    ):
        raise StrategyError("FUTURE_OR_STALE_FUNDAMENTALS")
    return features, usable[-1].start


def validate(
    context: Context, rules: Rules, now: datetime
) -> tuple[Features, datetime, datetime | None]:
    f, bar_start = point_in_time(context, now)
    o, e, a = context.opportunity, context.evidence, context.account
    iid = o.instrument.instrument_id
    if (
        type(iid) is not int
        or iid <= 0
        or o.instrument.kind not in ("Stocks", "ETF")
        or not identifier(a.account_id)
        or a.demo is not True
        or a.complete is not True
        or a.cash_flows_reconciled is not True
        or a.currency != "USD"
        or not fresh(a.observed_at, now, 60)
        or not money(a.equity, positive=True)
        or not money(a.available_balance)
    ):
        raise StrategyError("ACCOUNT_OR_INSTRUMENT_UNVERIFIED")
    if (
        not fresh(e.available_at, now, 60)
        or e.product.instrument_id != iid
        or e.product.currency != "USD"
        or e.product.underlying is not True
        or e.product.unleveraged is not True
        or not e.product.source
        or not aware(e.product.expires_at)
        or e.product.expires_at <= now
        or e.eligibility.instrument_id != iid
        or e.eligibility.underlying_long is not True
        or not fresh(e.eligibility.observed_at, now, 60)
        or not money(e.eligibility.minimum_usd, positive=True)
        or not money(e.eligibility.max_units, positive=True)
        or type(e.eligibility.fractional) is not bool
    ):
        raise StrategyError("ELIGIBILITY_OR_PRODUCT_UNVERIFIED")
    if (
        e.session.instrument_id != iid
        or e.session.is_open is not True
        or not e.session.source
        or not fresh(e.session.observed_at, now, 60)
        or not aware(e.session.valid_until)
        or e.session.valid_until <= now
        or not aware(e.session_close)
        or e.session_close <= now
    ):
        raise StrategyError("MARKET_CLOSED_OR_UNKNOWN")
    q = o.quote
    if (
        q.instrument_id != iid
        or q.quote_type != "realtime"
        or not fresh(q.observed_at, now, 60)
        or q.observed_at > o.created_at
        or not money(q.bid, positive=True)
        or not money(q.ask, positive=True)
        or q.bid > q.ask
    ):
        raise StrategyError("INVALID_OR_STALE_QUOTE")
    if (
        not fresh(e.liquidity_observed_at, now, 86400)
        or not money(e.daily_dollar_volume, positive=True)
        or e.daily_dollar_volume < rules.min_daily_dollar_volume
    ):
        raise StrategyError("LIQUIDITY_UNVERIFIED_OR_LOW")
    if (
        not math.isfinite(o.score)
        or D(str(o.score)) < rules.minimum_score
        or o.score > 100
        or not math.isfinite(f.volatility)
        or D(str(f.volatility)) > rules.max_volatility
    ):
        raise StrategyError("SIGNAL_QUALITY_OR_VOLATILITY")
    names = [name for name, _ in o.contributions]
    if (
        len(set(names)) != len(names)
        or any(not math.isfinite(v) or v < 0 for _, v in o.contributions)
        or not math.isclose(sum(v for _, v in o.contributions), o.score, abs_tol=1e-9)
    ):
        raise StrategyError("INVALID_SCORE_CONTRIBUTIONS")
    if "potential_mean_reversion" in names and any(
        n in names for n in ("momentum_breakout", "trend_continuation")
    ):
        raise StrategyError("CONFLICTING_SIGNALS")
    if (q.ask - q.bid) / q.ask > rules.max_spread_fraction:
        raise StrategyError("SPREAD_TOO_WIDE")
    if (
        e.quantity_step_verified is not True
        or not money(e.quantity_step, positive=True)
        or e.quantity_step > 1
        or not e.eligibility.fractional
        and e.quantity_step != 1
    ):
        raise StrategyError("QUANTITY_STEP_UNVERIFIED")
    exit_deadline = (
        e.session_close - timedelta(seconds=rules.close_buffer_seconds)
        if rules.style == Style.INTRADAY
        else None
    )
    if exit_deadline is not None and exit_deadline <= now:
        raise StrategyError("TOO_LATE_FOR_INTRADAY_ENTRY")
    horizon = exit_deadline or now + timedelta(seconds=rules.swing_horizon_seconds)
    earnings_safe(e.earnings, iid, now, horizon, rules.earnings_buffer_seconds)
    return f, bar_start, exit_deadline


class StrategyEngine:
    def __init__(self, journal: Journal, rules: Rules | None = None) -> None:
        self.journal, self.rules = journal, rules or Rules()

    def propose(self, context: Context, *, now: datetime) -> Outcome:
        if not aware(now):
            return Outcome("rejected", ("INVALID_TIME",))
        now = now.astimezone(UTC)
        signal = digest(
            {
                "instrument": context.opportunity.instrument.instrument_id,
                "account": context.account.account_id,
                "created": context.opportunity.created_at.isoformat(),
            }
        )
        try:
            with localcontext(DecimalContext(prec=60)):
                f, bar_start, deadline = validate(context, self.rules, now)
                # One signal per account/instrument/bar across rule versions and styles.
                signal = digest(
                    {
                        "account": context.account.account_id,
                        "instrument": context.opportunity.instrument.instrument_id,
                        "bar": bar_start,
                    }
                )
                selected = matches(f, self.rules)
                if not selected:
                    return self._reject(signal, "missed", "NO_ENTRY_SETUP", now)
                if Strategy.REVERSION in selected and len(selected) > 1:
                    return self._reject(signal, "rejected", "CONFLICTING_SIGNALS", now)
                # Compatible trend and breakout signals consolidate into one breakout candidate.
                strategy = Strategy.BREAKOUT if Strategy.BREAKOUT in selected else selected[0]
                candidate = self._size(context, strategy, signal, deadline, now)
                details = {
                    "strategy": strategy.value,
                    "style": self.rules.style.value,
                    "rules_digest": candidate.rules_digest,
                    "rules": asdict(self.rules),
                    "regime": regime(f),
                    "features": asdict(f),
                    "score": context.opportunity.score,
                    "reasons": ["PROPOSAL_REQUIRES_RISK"],
                    "proposal": asdict(candidate.proposal),
                    "expires_at": candidate.expires_at,
                }
                if not self.journal.record(signal, "proposed", details, now, candidate):
                    return Outcome("rejected", ("DUPLICATE_SIGNAL",))
                return Outcome("proposed", ("PROPOSAL_REQUIRES_RISK",), candidate)
        except StrategyError as error:
            return self._reject(signal, "rejected", str(error), now)
        except (ValueError, TypeError, AttributeError, DecimalException, OverflowError):
            return self._reject(signal, "rejected", "INVALID_INPUT", now)
        except (sqlite3.Error, OSError):
            return Outcome("rejected", ("JOURNAL_UNAVAILABLE",))

    def _reject(self, signal: str, status: str, reason: str, now: datetime) -> Outcome:
        try:
            self.journal.record(
                signal,
                status,
                {"reasons": [reason], "rules_digest": digest(asdict(self.rules))},
                now,
            )
        except (sqlite3.Error, OSError, StrategyError):
            return Outcome("rejected", ("JOURNAL_UNAVAILABLE",))
        return Outcome(status, (reason,))

    def _size(
        self, c: Context, strategy: Strategy, signal: str, deadline: datetime | None, now: datetime
    ) -> Candidate:
        e, a, o, r = c.evidence, c.account, c.opportunity, self.rules
        # Validate explicit FX/cost inputs using the scanner's established contract.
        e.budget.minimum_cash(e.eligibility, o.quote, now)
        b = e.budget
        usable = b.equity_eur * b.usd_per_eur * (1 - b.conversion_cost_fraction)
        equity = min(a.equity, usable)
        price = o.quote.ask
        unit_places = max(0, -int(e.quantity_step.normalize().as_tuple().exponent))
        stop_quantum = D(1).scaleb(-(12 - unit_places))
        stop = (price - D(str(o.features.atr)) * r.stop_atr).quantize(
            stop_quantum, rounding=ROUND_DOWN
        )
        if not money(stop, positive=True) or stop >= price:
            raise StrategyError("INVALID_STOP")
        unit_cost = (price - o.quote.bid) + price * (
            b.round_trip_fee_fraction
            + b.slippage_fraction
            + b.conversion_cost_fraction / (1 - b.conversion_cost_fraction)
        )
        fixed = b.round_trip_fixed_usd
        risk_cash = equity * r.risk_fraction - fixed
        allocation = min(equity * r.allocation_fraction, a.available_balance) - fixed
        if risk_cash <= 0 or allocation <= 0:
            raise StrategyError("INSUFFICIENT_BUDGET")
        units = min(
            risk_cash / (price - stop + unit_cost),
            allocation / (price + unit_cost),
            e.eligibility.max_units,
        )
        units = (units / e.quantity_step).to_integral_value(rounding=ROUND_DOWN) * e.quantity_step
        costs = (fixed + units * unit_cost).quantize(PRECISION, rounding=ROUND_UP)
        if (
            not money(units, positive=True)
            or not money(costs)
            or units * price < e.eligibility.minimum_usd
        ):
            raise StrategyError("BELOW_BROKER_MINIMUM")
        if costs > units * price * r.max_cost_fraction:
            raise StrategyError("COSTS_TOO_HIGH")
        if units * (price - stop) + costs > equity * r.risk_fraction:
            raise StrategyError("ROUNDED_RISK_EXCEEDED")
        expires = min(
            o.expires_at,
            now + timedelta(seconds=r.signal_ttl_seconds),
            o.quote.observed_at + timedelta(seconds=60),
            a.observed_at + timedelta(seconds=60),
            e.available_at + timedelta(seconds=60),
            e.eligibility.observed_at + timedelta(seconds=60),
            e.product.expires_at,
            e.session.valid_until,
            e.session.observed_at + timedelta(seconds=60),
            b.fx_observed_at + timedelta(seconds=60),
            deadline or o.expires_at,
        )
        if expires <= now:
            raise StrategyError("EXPIRED_PROPOSAL")
        rd = digest(asdict(r))
        pid = digest({"signal": signal, "rules": rd})
        proposal = Proposal(
            pid,
            o.instrument.instrument_id,
            units,
            price,
            stop,
            o.quote.observed_at,
            costs,
            underlying_verified=True,
        )
        target = (
            None
            if r.take_profit_r is None
            else (price + (price - stop) * r.take_profit_r).quantize(PRECISION)
        )
        return Candidate(
            proposal,
            a.account_id,
            strategy,
            r,
            rd,
            now,
            expires,
            deadline or expires,
            deadline,
            target,
            signal,
        )

    def review(
        self, candidate: Candidate, account: AccountSnapshot, risk: RiskEngine, *, now: datetime
    ) -> RiskReview:
        """Explicit handoff: risk PASS reserves capacity; never creates a broker ticket."""
        rejected = Decision(False, ("STRATEGY_REVIEW_BLOCKED",))
        if (
            not aware(now)
            or not candidate.decision_at <= now < candidate.expires_at
            or candidate.account_id != account.account_id
        ):
            return RiskReview(rejected, candidate.proposal)
        try:
            self.journal.begin_review(candidate, now)
            decision = risk.evaluate(candidate.proposal, account, now=now)
            self.journal.finish_review(candidate, decision.passed, decision.reasons, now)
            return RiskReview(decision, candidate.proposal)
        except (sqlite3.Error, OSError, StrategyError):
            return RiskReview(rejected, candidate.proposal)
