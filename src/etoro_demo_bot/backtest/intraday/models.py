"""Evidence-gated research contracts, independent of hourly Dataset and all execution."""

import re
from dataclasses import dataclass
from datetime import timedelta

from ...history.calendar import NYSE2026
from ...history.intraday import ResearchSeries
from ...risk.models import money
from ...scanner.models import Instrument, aware, fresh
from ...strategy.models import Rules
from ...strategy.orb import OrbRules, VolumeEvidence
from ...timeframes import FIVE_MINUTE_RESEARCH
from ..models import Simulation, Tick


@dataclass(frozen=True)
class Review:
    snapshot: str
    coverage: str = ""
    availability: str = ""
    usage_rights: str = ""
    corporate_actions: str = ""
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence: tuple[tuple[str, str], ...] = ()
    assumed_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    simulation: Simulation = Simulation()
    safety: Rules = Rules()
    orb: OrbRules = OrbRules()

    def validate(self) -> None:
        self.simulation.__post_init__()
        self.safety.__post_init__()
        self.orb.__post_init__()


@dataclass(frozen=True)
class Dataset:
    series: ResearchSeries
    instrument: Instrument
    ticks: tuple[Tick, ...]
    review: Review
    volume: VolumeEvidence | None = None

    def validate(self) -> tuple[str, ...]:
        """Reject structural errors and absent critical historical reviews."""
        s = self.series
        if s.contract != FIVE_MINUTE_RESEARCH or not s.sessions or not s.bars or not self.ticks:
            raise ValueError("INTRADAY_CONTRACT_OR_DATA_MISSING")
        s.contract.__post_init__()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", s.snapshot)
            or not re.fullmatch(r"[0-9a-f]{64}", s.source.raw_sha256)
            or s.source.provider != "alpaca-iex-download-5min-v1"
            or len(self.ticks) > 200000
            or len(s.bars) > 20000
        ):
            raise ValueError("INTRADAY_SOURCE_OR_SIZE_INVALID")
        calendar = NYSE2026(verified_at=s.sessions[0].calendar_verified_at)
        expected_sessions = calendar.sessions(s.sessions[0].day, s.sessions[-1].day)
        if tuple(w.day for w in s.sessions) != tuple(w.day for w in expected_sessions):
            raise ValueError("INTRADAY_TRADING_SESSION_MISSING")
        if s.source.classification not in ("synthetic", "historical_observation"):
            raise ValueError("INTRADAY_CLASSIFICATION_INVALID")
        if self.review.snapshot != s.snapshot or self.instrument.symbol != s.symbol:
            raise ValueError("INTRADAY_PROVENANCE_MISMATCH")
        if (
            not aware(s.source.retrieved_at)
            or not s.source.url
            or not s.source.license_note
            or not s.source.terms_url
        ):
            raise ValueError("INTRADAY_SOURCE_INCOMPLETE")
        expected = []
        previous = None
        for session in s.sessions:
            session.__post_init__()
            if previous is not None and session.opens <= previous:
                raise ValueError("INTRADAY_SESSIONS_UNORDERED")
            if session.calendar_verified_at > session.opens:
                raise ValueError("INTRADAY_CALENDAR_REVIEW_FROM_FUTURE")
            previous = session.closes
            at = session.opens
            while at < session.closes:
                expected.append((at, session))
                at += timedelta(minutes=5)
        if len(expected) != len(s.bars):
            raise ValueError("INTRADAY_SESSION_COVERAGE_INCOMPLETE")
        for b, (at, session) in zip(s.bars, expected, strict=True):
            b.__post_init__()
            v = b.observation
            if (
                v.start != at
                or b.session != session
                or b.source_snapshot != s.snapshot
                or v.basis != "raw"
                or not all(money(x, positive=True) for x in (v.open, v.high, v.low, v.close))
                or not v.low <= min(v.open, v.close) <= max(v.open, v.close) <= v.high
            ):
                raise ValueError("INTRADAY_BAR_INVALID_OR_UNQUALIFIED")
        previous_at = None
        for tick in self.ticks:
            q, e = tick.quote, tick.evidence
            if (
                not aware(tick.at)
                or previous_at is not None
                and tick.at <= previous_at
                or not fresh(q.observed_at, tick.at, 60)
                or q.instrument_id != self.instrument.instrument_id
                or q.quote_type != "realtime"
                or not all(money(x, positive=True) for x in (q.bid, q.ask))
                or q.bid > q.ask
                or not fresh(e.available_at, tick.at, 60)
                or not fresh(e.session.observed_at, tick.at, 60)
                or not aware(e.session.valid_until)
                or not e.session.source
                or not fresh(e.budget.fx_observed_at, tick.at, 60)
                or not money(e.budget.usd_per_eur, positive=True)
                or not money(e.quantity_step, positive=True)
                or e.quantity_step_verified is not True
                or not money(tick.available_units)
                or type(tick.decide) is not bool
                or type(tick.close_allowed) is not bool
                or not any(w.opens <= tick.at <= w.closes for w in s.sessions)
            ):
                raise ValueError("INTRADAY_TICK_STALE_UNORDERED_OR_OUTSIDE_SESSION")
            previous_at = tick.at
        if self.ticks[0].at != s.sessions[0].opens or self.ticks[-1].at != s.sessions[-1].closes:
            raise ValueError("INTRADAY_BOUNDARY_VALUATIONS_MISSING")
        if s.source.classification == "historical_observation":
            refs = (
                self.review.coverage,
                self.review.availability,
                self.review.usage_rights,
                self.review.corporate_actions,
            )
            blockers = []
            if not all(refs):
                blockers.append("CRITICAL_HISTORICAL_REVIEW_MISSING")
            if s.source.retrieved_at > self.ticks[0].at:
                blockers.append("SOURCE_RETRIEVED_AFTER_REPLAY_START")
            fields = {"quotes", "spreads", "fx", "eligibility", "costs", "liquidity", "earnings"}
            refs_by_field = dict(self.review.evidence)
            if (
                set(refs_by_field) - fields
                or set(self.review.assumed_fields) - fields
                or len(refs_by_field) != len(self.review.evidence)
                or any(
                    not isinstance(ref, str) or not ref.strip() for ref in refs_by_field.values()
                )
                or fields - set(refs_by_field) - set(self.review.assumed_fields)
            ):
                blockers.append("HISTORICAL_EXECUTION_EVIDENCE_OR_ASSUMPTIONS_MISSING")
            if "eligibility" in self.review.assumed_fields and any(
                t.evidence.eligibility.fractional is not False or t.evidence.quantity_step != 1
                for t in self.ticks
            ):
                blockers.append("FRACTIONAL_ELIGIBILITY_REQUIRES_REVIEWED_EVIDENCE")
            if s.replay_blockers:
                blockers.extend(s.replay_blockers)
            return tuple(sorted(set(blockers)))
        return ()

    @property
    def classification(self) -> str:
        if self.series.source.classification == "synthetic":
            return "synthetic_fixture"
        return "conditional_historical_research"
