"""Bounded observe-and-rank coordinator. Does not import or call execution or risk stores."""

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import DecimalException

from ..risk.models import money
from .analysis import Budget, ScoringRules
from .indicators import calculate
from .models import (
    Candle,
    EarningsProvider,
    EvidenceProvider,
    Features,
    FundamentalAnalysis,
    Instrument,
    MarketSource,
    Opportunity,
    ProductEvidence,
    ScanError,
    ScanResult,
    SessionEvidence,
    aware,
    fresh,
)


@dataclass(frozen=True)
class ScanPolicy:
    schedule_seconds: int = 300
    signal_ttl_seconds: int = 60
    quote_age_seconds: int = 60
    history_age_seconds: int = 4 * 86400
    max_instruments: int = 200
    concurrency: int = 4
    watchlist: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.schedule_seconds,
            self.signal_ttl_seconds,
            self.quote_age_seconds,
            self.history_age_seconds,
            self.max_instruments,
            self.concurrency,
        ):
            if type(value) is not int or not 1 <= value <= 604800:
                raise ScanError("INVALID_SCAN_POLICY")
        if any(type(i) is not int or i <= 0 for i in self.watchlist) or len(
            set(self.watchlist)
        ) != len(self.watchlist):
            raise ScanError("INVALID_WATCHLIST")
        if self.quote_age_seconds > 60 or self.signal_ttl_seconds > 60 or self.concurrency > 16:
            raise ScanError("INVALID_SCAN_POLICY")


class Scanner:
    def __init__(
        self,
        source: MarketSource,
        evidence: EvidenceProvider,
        budget: Budget,
        *,
        policy: ScanPolicy | None = None,
        rules: ScoringRules | None = None,
        earnings: EarningsProvider | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source, self.evidence, self.budget = source, evidence, budget
        self.policy, self.rules = policy or ScanPolicy(), rules or ScoringRules()
        self.earnings, self.clock = earnings, clock
        self._lock = asyncio.Lock()
        self._last_run: datetime | None = None
        self._last_observation: datetime | None = None
        self._features: dict[int, tuple[tuple[Candle, ...], Features]] = {}

    def _now(self) -> datetime:
        now = self.clock()
        if not aware(now) or self._last_observation is not None and now < self._last_observation:
            raise ScanError("INVALID_SCANNER_CLOCK")
        self._last_observation = now
        return now

    async def run_due(self) -> ScanResult | None:
        """Caller-driven schedule, no background trading loop or daily trade quota."""
        async with self._lock:
            now = self._now()
            if self._last_run is not None and now - self._last_run < timedelta(
                seconds=self.policy.schedule_seconds
            ):
                return None
            self._last_run = now
            return await self._scan()

    async def _scan(self) -> ScanResult:
        instruments = await self.source.discover()
        discovered = len(instruments)
        if self.policy.watchlist:
            available = {i.instrument_id for i in instruments}
            if not set(self.policy.watchlist) <= available:
                raise ScanError("WATCHLIST_INSTRUMENT_UNAVAILABLE")
            instruments = tuple(i for i in instruments if i.instrument_id in self.policy.watchlist)
        if len(instruments) > self.policy.max_instruments:
            raise ScanError("UNIVERSE_TOO_LARGE")
        if len({x.instrument_id for x in instruments}) != len(instruments):
            raise ScanError("DUPLICATE_INSTRUMENT")
        rejected: list[tuple[int, str]] = []
        semaphore = asyncio.Semaphore(self.policy.concurrency)
        prepared: dict[int, tuple[tuple[Candle, ...], ProductEvidence, SessionEvidence]] = {}

        async def prepare(instrument: Instrument) -> None:
            async with semaphore:
                try:
                    now = self._now()
                    if instrument.kind not in {"Stocks", "ETF"}:
                        raise ScanError("INSTRUMENT_FORBIDDEN")
                    product = await self.evidence.product(instrument, now)
                    session = await self.evidence.session(instrument, now)
                    self._check_evidence(instrument.instrument_id, product, session, self._now())
                    history = await self.source.history(instrument.instrument_id)
                    # Ignore the forming candle, never use it in indicator or volume comparisons.
                    if any(not aware(x.start) or x.start > self._now() for x in history):
                        raise ScanError("INVALID_HISTORY")
                    completed = tuple(
                        x for x in history if x.start + timedelta(hours=1) <= self._now()
                    )
                    if not completed or not fresh(
                        completed[-1].start + timedelta(hours=1),
                        self._now(),
                        self.policy.history_age_seconds,
                    ):
                        raise ScanError("STALE_HISTORY")
                    if (
                        await self.evidence.history_complete(instrument, completed, self._now())
                        is not True
                    ):
                        raise ScanError("HISTORY_COVERAGE_UNVERIFIED")
                    prepared[instrument.instrument_id] = (completed, product, session)
                except (ScanError, OSError, sqlite3.Error):
                    rejected.append((instrument.instrument_id, "DATA_OR_EVIDENCE_UNAVAILABLE"))

        await asyncio.gather(*(prepare(i) for i in instruments))
        ids = tuple(sorted(prepared))
        # Quotes fetched after slow history loads so batching does not refresh old timestamps.
        eligibility = await self.source.eligibility(ids) if ids else {}
        quotes = await self.source.quotes(ids) if ids else {}
        opportunities: list[Opportunity] = []
        for instrument in instruments:
            iid = instrument.instrument_id
            if iid not in prepared:
                continue
            try:
                now = self._now()
                history, product, session = prepared[iid]
                session = await self.evidence.session(instrument, now)
                now = self._now()
                self._check_evidence(iid, product, session, now)
                quote, eligible = quotes.get(iid), eligibility.get(iid)
                if (
                    quote is None
                    or quote.instrument_id != iid
                    or quote.quote_type != "realtime"
                    or not fresh(quote.observed_at, now, self.policy.quote_age_seconds)
                    or not money(quote.ask, positive=True)
                    or not money(quote.bid, positive=True)
                    or quote.bid > quote.ask
                ):
                    raise ScanError("PRICE_MISSING_OR_STALE")
                if (
                    eligible is None
                    or eligible.instrument_id != iid
                    or eligible.underlying_long is not True
                    or type(eligible.fractional) is not bool
                    or not fresh(eligible.observed_at, now, 60)
                ):
                    raise ScanError("ELIGIBILITY_UNVERIFIED")
                cash, budget = self.budget.minimum_cash(eligible, quote, now)
                cached = self._features.get(iid)
                features = (
                    cached[1] if cached is not None and cached[0] == history else calculate(history)
                )
                self._features[iid] = (history, features)
                contributions = self.rules.rank(features)
                score = sum(weight for _, weight in contributions)
                if not contributions or score < self.rules.minimum_score:
                    raise ScanError("NO_QUALIFYING_SETUP")
                facts: FundamentalAnalysis | None = None
                if self.earnings is not None:
                    facts = await self.earnings.analysis(iid, now)
                    if facts is not None and (
                        facts.instrument_id != iid
                        or not facts.source
                        or not facts.version
                        or not aware(facts.as_of)
                        or not aware(facts.expires_at)
                        or not facts.as_of <= now < facts.expires_at
                    ):
                        raise ScanError("INVALID_FUNDAMENTALS")
                expires = min(
                    now + timedelta(seconds=self.policy.signal_ttl_seconds),
                    quote.observed_at + timedelta(seconds=self.policy.quote_age_seconds),
                    eligible.observed_at + timedelta(seconds=60),
                    product.expires_at,
                    session.valid_until,
                    session.observed_at + timedelta(seconds=60),
                    self.budget.fx_observed_at + timedelta(seconds=60),
                    history[-1].start + timedelta(hours=1, seconds=self.policy.history_age_seconds),
                )
                if facts is not None:
                    expires = min(expires, facts.expires_at)
                if expires <= self._now():
                    raise ScanError("OPPORTUNITY_EXPIRED")
                opportunities.append(
                    Opportunity(
                        instrument,
                        score,
                        contributions,
                        features,
                        quote,
                        now,
                        expires,
                        cash,
                        budget,
                        facts,
                    )
                )
            except ScanError as error:
                rejected.append((iid, str(error)))
            except (DecimalException, OSError, sqlite3.Error):
                rejected.append((iid, "ANALYSIS_UNAVAILABLE"))
        # A slow provider can expire earlier instruments before the complete result is returned.
        now = self._now()
        current = []
        for opportunity in opportunities:
            if opportunity.valid_at(now):
                current.append(opportunity)
            else:
                rejected.append((opportunity.instrument.instrument_id, "OPPORTUNITY_EXPIRED"))
        return ScanResult(
            tuple(sorted(current, key=lambda o: (-o.score, o.instrument.instrument_id))),
            tuple(sorted(rejected)),
            discovered,
        )

    @staticmethod
    def _check_evidence(
        iid: int, product: ProductEvidence, session: SessionEvidence, now: datetime
    ) -> None:
        if (
            product.instrument_id != iid
            or product.currency != "USD"
            or product.unleveraged is not True
            or product.underlying is not True
            or not product.source
            or not aware(product.expires_at)
            or product.expires_at <= now
        ):
            raise ScanError("PRODUCT_UNVERIFIED")
        if (
            session.instrument_id != iid
            or session.is_open is not True
            or not session.source
            or not fresh(session.observed_at, now, 60)
            or not aware(session.valid_until)
            or session.valid_until <= now
        ):
            raise ScanError("MARKET_CLOSED_OR_UNKNOWN")
