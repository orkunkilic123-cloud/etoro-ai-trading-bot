"""Long-only, point-in-time ORB research proposals. No execution or network boundary."""

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, localcontext
from decimal import Context as DecimalContext
from decimal import Decimal as D
from typing import TYPE_CHECKING

from ..history.intraday import ResearchBar, ResearchSeries, SessionWindow
from ..risk.models import AccountSnapshot, Proposal, identifier, money
from ..scanner.models import Instrument, Quote, aware, fresh
from ..timeframes import FIVE_MINUTE_RESEARCH
from .journal import digest
from .models import Evidence, Rules, Style

if TYPE_CHECKING:
    from ..risk.engine import RiskEngine
    from .journal import Journal
    from .models import RiskReview


class OrbError(ValueError):
    def __init__(self, reason: str, status: str = "blocked") -> None:
        super().__init__(reason)
        self.status = status


@dataclass(frozen=True)
class OrbRules:
    version: str = "orb-15m-v1"
    entry_ttl_seconds: int = 60
    last_entry_minutes: int = 90  # From session open, clipped to exit deadline.
    close_buffer_seconds: int = 900
    max_chase_fraction: D = D(".002")
    max_extension_fraction: D = D(".01")
    max_range_fraction: D = D(".05")
    volume_ratio: D | None = None
    stop_rule: str = "midpoint"
    target_r: D = D(2)

    def __post_init__(self) -> None:
        if (
            self.version != "orb-15m-v1"
            or self.stop_rule not in ("midpoint", "low")
            or type(self.entry_ttl_seconds) is not int
            or not 1 <= self.entry_ttl_seconds <= 60
            or type(self.last_entry_minutes) is not int
            or not 20 <= self.last_entry_minutes <= 180
            or type(self.close_buffer_seconds) is not int
            or not 60 <= self.close_buffer_seconds <= 3600
            or not all(
                money(v, positive=True) and v < 1
                for v in (
                    self.max_chase_fraction,
                    self.max_extension_fraction,
                    self.max_range_fraction,
                )
            )
            or not money(self.target_r, positive=True)
            or not 1 <= self.target_r <= 10
            or self.volume_ratio is not None
            and (not money(self.volume_ratio, positive=True) or not 1 <= self.volume_ratio <= 10)
        ):
            raise OrbError("INVALID_ORB_RULES")


@dataclass(frozen=True)
class VolumeEvidence:
    snapshot: str
    available_at: datetime
    review_reference: str
    feed: str = "iex"
    complete: bool = False  # Native same-feed bar volumes, never consolidated volume.


@dataclass(frozen=True)
class OrbContext:
    series: ResearchSeries
    instrument: Instrument
    quote: Quote
    evidence: Evidence
    account: AccountSnapshot
    volume: VolumeEvidence | None = None


@dataclass(frozen=True)
class OrbProposal:
    proposal: Proposal
    account_id: str
    signal_id: str
    rules: OrbRules
    safety_digest: str
    inputs_digest: str
    session_day: str
    session_opens: datetime
    session_closes: datetime
    range_end: datetime
    range_high: D
    range_low: D
    confirmation_start: datetime
    confirmation_end: datetime
    confirmation_known_at: datetime
    confirmation_close: D
    decided_at: datetime
    expires_at: datetime
    entry_deadline: datetime
    exit_deadline: datetime
    target: D
    invalidates_at_or_below: D
    snapshot: str
    classification: str
    evidence_times: tuple[tuple[str, datetime], ...]
    replay_blockers: tuple[str, ...]

    @property
    def execution_authorized(self) -> bool:
        return False

    @property
    def research_only(self) -> bool:
        return True


@dataclass(frozen=True)
class OrbOutcome:
    status: str
    reasons: tuple[str, ...]
    candidate: OrbProposal | None = None


def session_prefix(
    series: ResearchSeries, now: datetime
) -> tuple[SessionWindow, tuple[ResearchBar, ...]]:
    """Validate exactly the visible completed prefix of the current regular session.

    This does not weaken the Phase 1 full-session archive qualifier. Later-retrieved
    historical bars remain invisible; future OHLC values are never inspected as features.
    """
    if not aware(now) or series.contract != FIVE_MINUTE_RESEARCH:
        raise OrbError("ORB_CONTRACT_OR_TIME_INVALID")
    series.contract.__post_init__()
    if series.source.classification not in ("synthetic", "historical_observation"):
        raise OrbError("ORB_SOURCE_INVALID")
    if (
        series.source.provider != "alpaca-iex-download-5min-v1"
        or not re.fullmatch(r"[0-9a-f]{64}", series.snapshot)
        or not re.fullmatch(r"[0-9a-f]{64}", series.source.raw_sha256)
        or not aware(series.source.retrieved_at)
        or series.source.retrieved_at > now
    ):
        raise OrbError("ORB_SOURCE_INVALID")
    sessions = tuple(s for s in series.sessions if s.opens <= now < s.closes)
    if len(sessions) != 1:
        raise OrbError("ORB_SESSION_CLOSED_OR_AMBIGUOUS")
    session = sessions[0]
    session.__post_init__()
    if session.calendar_verified_at > now:
        raise OrbError("ORB_CALENDAR_FROM_FUTURE")
    visible = series.visible_at(now, max_age_seconds=300)
    bars = tuple(b for b in visible if b.session.day == session.day)
    expected = []
    point = session.opens
    while point + timedelta(minutes=5) <= now:
        expected.append(point)
        point += timedelta(minutes=5)
    if tuple(b.observation.start for b in bars) != tuple(expected):
        raise OrbError("ORB_PREFIX_MISSING_DUPLICATED_OR_UNORDERED")
    for b in bars:
        b.__post_init__()
        v = b.observation
        if (
            b.session != session
            or b.source_snapshot != series.snapshot
            or v.basis != "raw"
            or not all(money(x, positive=True) for x in (v.open, v.high, v.low, v.close))
            or not v.low <= min(v.open, v.close) <= max(v.open, v.close) <= v.high
        ):
            raise OrbError("ORB_BAR_OR_PROVENANCE_INVALID")
    return session, bars


def market_evidence(
    c: OrbContext, safety: Rules, now: datetime, session: SessionWindow, deadline: datetime
) -> None:
    """Reuse existing evidence contracts and earnings gate, without fabricating hourly features."""
    from .engine import earnings_safe

    safety.__post_init__()
    i, q, e, a = c.instrument, c.quote, c.evidence, c.account
    if (
        safety.style is not Style.INTRADAY
        or type(i.instrument_id) is not int
        or i.instrument_id <= 0
        or i.kind not in ("Stocks", "ETF")
        or i.symbol != c.series.symbol
        or not identifier(a.account_id)
        or a.demo is not True
        or a.currency != "USD"
        or a.complete is not True
        or a.cash_flows_reconciled is not True
        or not fresh(a.observed_at, now, 60)
        or not money(a.equity, positive=True)
        or not money(a.available_balance)
    ):
        raise OrbError("ORB_ACCOUNT_OR_INSTRUMENT_UNVERIFIED")
    if (
        not fresh(e.available_at, now, 60)
        or e.product.instrument_id != i.instrument_id
        or e.product.currency != "USD"
        or e.product.underlying is not True
        or e.product.unleveraged is not True
        or not e.product.source
        or not aware(e.product.expires_at)
        or e.product.expires_at <= now
        or e.eligibility.instrument_id != i.instrument_id
        or e.eligibility.underlying_long is not True
        or not fresh(e.eligibility.observed_at, now, 60)
        or not money(e.eligibility.minimum_usd, positive=True)
        or not money(e.eligibility.max_units, positive=True)
        or type(e.eligibility.fractional) is not bool
    ):
        raise OrbError("ORB_PRODUCT_OR_ELIGIBILITY_UNVERIFIED")
    if (
        q.instrument_id != i.instrument_id
        or q.quote_type != "realtime"
        or not fresh(q.observed_at, now, 60)
        or not money(q.bid, positive=True)
        or not money(q.ask, positive=True)
        or q.bid > q.ask
        or (q.ask - q.bid) / q.ask > safety.max_spread_fraction
    ):
        raise OrbError("ORB_QUOTE_INVALID_OR_STALE")
    if (
        e.session.instrument_id != i.instrument_id
        or e.session.is_open is not True
        or not fresh(e.session.observed_at, now, 60)
        or not e.session.source
        or not aware(e.session.valid_until)
        or e.session.valid_until <= now
        or e.session_close != session.closes
        or not session.opens <= now < deadline
        or not fresh(e.liquidity_observed_at, now, 86400)
        or not money(e.daily_dollar_volume, positive=True)
        or e.daily_dollar_volume < safety.min_daily_dollar_volume
        or e.quantity_step_verified is not True
        or not money(e.quantity_step, positive=True)
        or e.quantity_step > 1
        or not e.eligibility.fractional
        and e.quantity_step != 1
    ):
        raise OrbError("ORB_SESSION_LIQUIDITY_OR_QUANTITY_UNVERIFIED")
    e.budget.minimum_cash(e.eligibility, q, now)
    earnings_safe(e.earnings, i.instrument_id, now, deadline, safety.earnings_buffer_seconds)


def make_proposal(c: OrbContext, *, now: datetime, rules: OrbRules, safety: Rules) -> OrbProposal:
    """Pure deterministic research proposal. Callers journal before any explicit risk review."""
    rules.__post_init__()
    if not aware(now):
        raise OrbError("ORB_TIME_INVALID")
    now = now.astimezone(UTC)
    session, bars = session_prefix(c.series, now)
    deadline = session.closes - timedelta(
        seconds=max(rules.close_buffer_seconds, safety.close_buffer_seconds)
    )
    entry_deadline = min(session.opens + timedelta(minutes=rules.last_entry_minutes), deadline)
    if now >= entry_deadline:
        raise OrbError("ORB_ENTRY_WINDOW_EXPIRED", "expired")
    if len(bars) < 3:
        raise OrbError("ORB_RANGE_FORMING", "waiting")
    high = max(b.observation.high for b in bars[:3])
    low = min(b.observation.low for b in bars[:3])
    if high <= low or (high - low) / high > rules.max_range_fraction:
        raise OrbError("ORB_RANGE_INVALID_OR_TOO_WIDE")
    volumes: tuple[D, ...] = ()
    if rules.volume_ratio is not None:
        v = c.volume
        if (
            v is None
            or v.snapshot != c.series.snapshot
            or v.complete is not True
            or v.feed != "iex"
            or not v.review_reference
            or not fresh(v.available_at, now, 86400)
        ):
            raise OrbError("ORB_VOLUME_EVIDENCE_UNQUALIFIED")
        if any(b.observation.volume is None or not money(b.observation.volume) for b in bars):
            raise OrbError("ORB_VOLUME_MISSING_OR_INVALID")
        volumes = tuple(b.observation.volume for b in bars if b.observation.volume is not None)
        if sum(volumes[:3]) == 0:
            raise OrbError("ORB_VOLUME_BASELINE_ZERO")
    trigger = next(
        (
            b
            for j, b in enumerate(bars[3:], 3)
            if b.observation.close > high
            and (
                rules.volume_ratio is None
                or volumes[j] * 3 >= sum(volumes[:3]) * rules.volume_ratio
            )
        ),
        None,
    )
    if trigger is None:
        raise OrbError("ORB_NO_CONFIRMED_BREAKOUT", "waiting")
    if now >= trigger.completed_at + timedelta(seconds=rules.entry_ttl_seconds):
        raise OrbError("ORB_SIGNAL_EXPIRED_NO_CHASE", "expired")
    if any(b.observation.close <= high for b in bars if b.completed_at > trigger.completed_at):
        raise OrbError("ORB_BREAKOUT_INVALIDATED", "invalidated")
    market_evidence(c, safety, now, session, deadline)
    if c.quote.bid <= high:
        raise OrbError("ORB_QUOTE_BACK_INSIDE_RANGE", "invalidated")
    if c.quote.ask > min(
        trigger.observation.close * (1 + rules.max_chase_fraction),
        high * (1 + rules.max_extension_fraction),
    ):
        raise OrbError("ORB_PRICE_EXTENSION_NO_CHASE")
    with localcontext(DecimalContext(prec=60)):
        q, e, a, b = c.quote, c.evidence, c.account, c.evidence.budget
        unit_places = max(0, -int(e.quantity_step.normalize().as_tuple().exponent))
        stop_quantum = D(1).scaleb(-(12 - unit_places))
        stop = (low if rules.stop_rule == "low" else (high + low) / 2).quantize(
            stop_quantum, rounding=ROUND_DOWN
        )
        price = q.ask
        equity = min(a.equity, b.equity_eur * b.usd_per_eur * (1 - b.conversion_cost_fraction))
        per_unit_cost = (
            q.ask
            - q.bid
            + price
            * (
                b.round_trip_fee_fraction
                + b.slippage_fraction
                + b.conversion_cost_fraction / (1 - b.conversion_cost_fraction)
            )
        )
        risk_cash = equity * safety.risk_fraction - b.round_trip_fixed_usd
        allocation = (
            min(
                equity * min(safety.allocation_fraction, b.max_allocation_fraction),
                a.available_balance,
            )
            - b.round_trip_fixed_usd
        )
        if not money(stop, positive=True) or stop >= price or min(risk_cash, allocation) <= 0:
            raise OrbError("ORB_STOP_OR_BUDGET_INVALID")
        units = min(
            risk_cash / (price - stop + per_unit_cost),
            allocation / (price + per_unit_cost),
            e.eligibility.max_units,
        )
        units = (units / e.quantity_step).to_integral_value(rounding=ROUND_DOWN) * e.quantity_step
        costs = (b.round_trip_fixed_usd + units * per_unit_cost).quantize(
            D("1e-12"), rounding=ROUND_UP
        )
        target = (price + (price - stop) * rules.target_r).quantize(D("1e-12"))
        if (
            not money(units, positive=True)
            or not money(costs)
            or not money(target, positive=True)
            or units * price < e.eligibility.minimum_usd
            or costs > units * price * min(safety.max_cost_fraction, b.max_cost_fraction)
            or units * (price - stop) + costs > equity * safety.risk_fraction
        ):
            raise OrbError("ORB_SIZE_MINIMUM_COST_OR_RISK_LIMIT")
        expires = min(
            trigger.completed_at + timedelta(seconds=rules.entry_ttl_seconds),
            entry_deadline,
            q.observed_at + timedelta(seconds=60),
            a.observed_at + timedelta(seconds=60),
            e.available_at + timedelta(seconds=60),
            e.eligibility.observed_at + timedelta(seconds=60),
            e.product.expires_at,
            e.session.valid_until,
            e.session.observed_at + timedelta(seconds=60),
            b.fx_observed_at + timedelta(seconds=60),
        )
        if expires <= now:
            raise OrbError("ORB_PROPOSAL_EXPIRED", "expired")
        signal = digest(
            {
                "research": "orb-15m-v1",
                "account": a.account_id,
                "instrument": c.instrument.instrument_id,
                "day": session.day.isoformat(),
            }
        )
        inputs = digest(
            {
                "snapshot": c.series.snapshot,
                "source_sha256": c.series.source.raw_sha256,
                "account": asdict(a),
                "quote": asdict(q),
                "evidence": asdict(e),
                "volume": None if c.volume is None else asdict(c.volume),
                "bars": [asdict(x.observation) for x in bars],
            }
        )
        identity = digest(
            {"signal": signal, "rules": asdict(rules), "safety": asdict(safety), "inputs": inputs}
        )
        proposal = Proposal(
            identity,
            c.instrument.instrument_id,
            units,
            price,
            stop,
            q.observed_at,
            costs,
            underlying_verified=True,
        )
        return OrbProposal(
            proposal,
            a.account_id,
            signal,
            rules,
            digest(asdict(safety)),
            inputs,
            session.day.isoformat(),
            session.opens,
            session.closes,
            session.opens + timedelta(minutes=15),
            high,
            low,
            trigger.observation.start,
            trigger.completed_at,
            trigger.first_known_at,
            trigger.observation.close,
            now,
            expires,
            entry_deadline,
            deadline,
            target,
            high,
            c.series.snapshot,
            c.series.source.classification,
            (
                ("quote", q.observed_at),
                ("account", a.observed_at),
                ("evidence", e.available_at),
                ("range_known", max(x.first_known_at for x in bars[:3])),
                ("confirmation_known", trigger.first_known_at),
            ),
            c.series.replay_blockers,
        )


class OrbResearchEngine:
    """Journalled proposal/review adapter; callers supply a dedicated research journal/store."""

    def __init__(self, journal: "Journal", safety: Rules) -> None:
        self.journal, self.safety = journal, safety

    def propose(
        self, context: OrbContext, *, now: datetime, rules: OrbRules | None = None
    ) -> OrbOutcome:
        if not aware(now):
            return OrbOutcome("blocked", ("ORB_TIME_INVALID",))
        now = now.astimezone(UTC)
        try:
            candidate = make_proposal(
                context, now=now, rules=rules or OrbRules(), safety=self.safety
            )
            if not self.journal.claim_research(
                candidate.signal_id, candidate.proposal.proposal_id, asdict(candidate), now
            ):
                return OrbOutcome("blocked", ("ORB_DUPLICATE_SESSION_SIGNAL",))
            return OrbOutcome("proposed", ("ORB_RESEARCH_REQUIRES_RISK",), candidate)
        except OrbError as error:
            status, reason = error.status, str(error)
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            status, reason = "blocked", "ORB_INPUT_OR_EVIDENCE_INVALID"
        except (OSError, sqlite3.Error):
            return OrbOutcome("blocked", ("ORB_JOURNAL_UNAVAILABLE",))
        try:
            self.journal.record("orb-rejected", "orb_" + status, {"reasons": [reason]}, now)
        except (OSError, sqlite3.Error, ValueError):
            return OrbOutcome("blocked", ("ORB_JOURNAL_UNAVAILABLE",))
        return OrbOutcome(status, (reason,))

    def review(
        self, candidate: OrbProposal, context: OrbContext, risk: "RiskEngine", *, now: datetime
    ) -> "RiskReview":
        from ..risk.models import Decision
        from .models import RiskReview

        rejected = RiskReview(Decision(False, ("ORB_REVIEW_BLOCKED",)), candidate.proposal)
        try:
            if not aware(now) or not candidate.decided_at <= now < candidate.expires_at:
                return rejected
            fresh_candidate = make_proposal(
                context, now=now, rules=candidate.rules, safety=self.safety
            )
            if (
                fresh_candidate.proposal != candidate.proposal
                or fresh_candidate.inputs_digest != candidate.inputs_digest
                or fresh_candidate.safety_digest != candidate.safety_digest
            ):
                return rejected
            self.journal.begin_research_review(candidate.signal_id, asdict(candidate), now)
            decision = risk.evaluate(candidate.proposal, context.account, now=now)
            self.journal.finish_research_review(
                candidate.signal_id, decision.passed, decision.reasons, now
            )
            return RiskReview(decision, candidate.proposal)
        except (ValueError, TypeError, AttributeError, ArithmeticError, OSError, sqlite3.Error):
            return rejected
