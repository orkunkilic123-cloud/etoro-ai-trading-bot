"""Event-driven ORB replay; exclusive simulation state, no broker boundary."""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from ...risk.models import AccountSnapshot, Exposure
from ...strategy import Journal, StrategyEngine
from ...strategy.journal import digest, encode
from ...strategy.orb import OrbContext, OrbProposal, market_evidence
from ..engine import Result
from ..metrics import metrics
from ..models import Tick
from ..risk import SimulationRisk
from .fills import Q, Touch, bar_touch, fee, price, quantity
from .models import Dataset, Plan
from .serialization import normalized

D = Decimal


@dataclass
class Holding:
    candidate: OrbProposal
    units: D
    entry: D
    opened: datetime
    entry_fee: D
    pnl: D = D(0)


@dataclass(frozen=True)
class Exit:
    at: datetime
    touch: Touch


class IntradayBacktest:
    def __init__(self, data: Dataset, plan: Plan | None = None) -> None:
        self.data, self.plan = data, plan or Plan()

    def run(self, new_directory: Path) -> Result:
        new_directory.mkdir(parents=True, exist_ok=False)
        self.plan.validate()
        manifest: dict[str, Any] = {
            "model": "orb-event-replay-v1",
            "execution_authorized": False,
            "dataset_digest": digest(normalized(asdict(self.data))),
            "plan_digest": digest(normalized(asdict(self.plan))),
            "provenance": {"kind": self.data.classification},
            "dataset": asdict(self.data),
            "original_bar_timestamps": [
                {
                    "start": b.observation.start.isoformat(),
                    "end": b.observation.end.isoformat(),
                    "completed_at": b.completed_at.isoformat(),
                    "first_known_at": b.first_known_at.isoformat(),
                }
                for b in self.data.series.bars
            ],
            "original_source_retrieved_at": self.data.series.source.retrieved_at.isoformat(),
            "plan": asdict(self.plan),
            "limitations": [
                "Modelled fills, not verified eToro profitability.",
                "No queue, halt duration or unseen liquidity inference.",
                "OHLC bid path uses the last observed relative spread.",
                "Entry-bar extremes before the fill are never used.",
                "No new entries after insolvency or a risk halt.",
                *self.data.review.assumptions,
                *self.data.review.limitations,
            ],
        }
        manifest = normalized(manifest)
        try:
            blockers = self.data.validate()
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            blockers = ("INVALID_OR_UNQUALIFIED_INTRADAY_DATASET",)
        if blockers:
            manifest.update(status="blocked", blockers=blockers)
            return Result(manifest, {}, (), (), (), (), {})
        (new_directory / "inputs.json").write_text(encode(manifest) + "\n", encoding="utf-8")
        with localcontext(Context(prec=60)):
            return self._run(new_directory, manifest)

    def _run(self, directory: Path, manifest: dict[str, Any]) -> Result:
        data, sim, safety = self.data, self.plan.simulation, self.plan.safety
        ticks, iid = data.ticks, data.instrument.instrument_id
        strategy = StrategyEngine(Journal.initialize(directory / "strategy.sqlite"), safety)
        # SimulationRisk refuses existing paths and binds only to backtest-demo.
        risk = SimulationRisk(directory / "simulation-risk.sqlite", killed=sim.kill_switch)
        manifest["risk_policy"] = normalized(asdict(risk.policy))
        manifest["hard_limits"] = {
            "estimated_trade_risk_fraction": "0.01",
            "daily_loss_fraction": "0.03",
        }
        initial_fx = ticks[0].evidence.budget.usd_per_eur
        initial = sim.initial_eur * initial_fx
        funding = price(initial * sim.fx_fraction, buy=True)
        cash, costs = initial - funding, funding
        holding: Holding | None = None
        pending: OrbProposal | None = None
        exit_request: Exit | None = None
        events: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        points = [{"at": ticks[0].at.isoformat(), "equity": str(sim.initial_eur), "exposure": "0"}]
        pnls: list[float] = []
        available_bars = iter(sorted(data.series.bars, key=lambda b: b.first_known_at))
        next_bar = next(available_bars, None)
        day = ticks[0].at.astimezone(UTC).date()
        last_equity = initial
        risk.store.establish_day(day, initial)
        missed = rejected = ambiguous = 0

        def log(at: datetime, kind: str, **detail: Any) -> None:
            events.append(
                {"sequence": len(events) + 1, "at": at.isoformat(), "kind": kind, **detail}
            )

        def account(tick: Tick) -> AccountSnapshot:
            value = D(0) if holding is None else holding.units * tick.quote.bid
            return AccountSnapshot(
                "backtest-demo",
                (cash + value).quantize(Q),
                max(D(0), cash).quantize(Q),
                () if holding is None else (Exposure(iid, value, 1),),
                tick.at,
                demo=True,
                complete=True,
                cash_flows_reconciled=True,
            )

        log(ticks[0].at, "funding", gross_usd=str(initial), fx_cost=str(funding))
        for tick in ticks:
            tick = replace(tick, at=tick.at.astimezone(UTC))
            now, q = tick.at, tick.quote
            window = next(w for w in data.series.sessions if w.opens <= now <= w.closes)
            while day < now.date():
                day += timedelta(days=1)
                if last_equity <= 0:
                    break
                risk.store.establish_day(day, last_equity)
            a = account(tick)
            observation = risk.observe(a, iid, now=now)
            halted = any(
                x in observation.reasons for x in ("DAILY_LOSS_LIMIT", "KILL_SWITCH_ACTIVE")
            )
            if halted:
                log(now, "risk_halt", reasons=observation.reasons)
            active = (
                window.opens <= now < window.closes
                and tick.evidence.session.is_open is True
                and tick.evidence.session.instrument_id == iid
                and tick.evidence.session.observed_at <= now < tick.evidence.session.valid_until
                and tick.evidence.session_close == window.closes
            )
            # Process only newly available, fully completed bars; never retroactively fill.
            while next_bar is not None and next_bar.first_known_at <= now:
                bar = next_bar
                next_bar = next(available_bars, None)
                if (
                    holding is not None
                    and exit_request is None
                    and bar.observation.start >= holding.opened
                ):
                    assert holding.candidate.proposal.stop_loss is not None
                    touch = bar_touch(
                        bar,
                        holding.candidate.proposal.stop_loss,
                        holding.candidate.target,
                        (q.ask - q.bid) / (q.ask + q.bid),
                    )
                    if touch is not None:
                        ambiguous += int(touch.ambiguous)
                        # Detection is at this event, not a backdated executable bar high/low.
                        exit_request = Exit(now, touch)
                        log(
                            now,
                            "exit_trigger",
                            reason=touch.reason,
                            bar_known_at=bar.first_known_at.isoformat(),
                        )
            if holding is not None and exit_request is None:
                p = holding.candidate
                assert p.proposal.stop_loss is not None
                touch = None
                if q.bid <= p.proposal.stop_loss:
                    touch = Touch("quote_gap_stop", q.bid)
                elif q.bid >= p.target:
                    touch = Touch("quote_target_capped", p.target)
                elif now >= p.exit_deadline:
                    touch = Touch("session_deadline", q.bid)
                elif halted:
                    touch = Touch("risk_halt_exit", q.bid)
                if touch is not None:
                    exit_request = Exit(now, touch)
                    log(now, "exit_trigger", reason=touch.reason)
            if holding is not None and exit_request is not None and active and tick.close_allowed:
                if (
                    now >= exit_request.at + timedelta(seconds=sim.delay_seconds)
                    and q.observed_at > exit_request.at
                ):
                    units = quantity(holding.units, tick, sim)
                    if units > 0:
                        fill = price(
                            min(q.bid, exit_request.touch.ceiling) * (1 - sim.slippage_fraction),
                            buy=False,
                        )
                        charge = fee(units, fill, sim)
                        allocated = holding.entry_fee * units / holding.units
                        pnl = units * (fill - holding.entry) - allocated - charge
                        implicit = units * ((q.ask - q.bid) / 2 + q.bid - fill)
                        costs += charge + implicit
                        cash += units * fill - charge
                        holding.pnl += pnl
                        holding.entry_fee -= allocated
                        holding.units -= units
                        trade = {
                            "at": now.isoformat(),
                            "opened_at": holding.opened.isoformat(),
                            "units": str(units),
                            "entry": str(holding.entry),
                            "exit": str(fill),
                            "pnl_usd": str(pnl),
                            "fee_usd": str(charge),
                            "reason": exit_request.touch.reason,
                            "deadline_breached": now > holding.candidate.exit_deadline,
                            "overnight": now.date() > holding.opened.date(),
                        }
                        trades.append(trade)
                        log(now, "exit_fill", **{k: v for k, v in trade.items() if k != "at"})
                        if holding.units == 0:
                            pnls.append(float(holding.pnl))
                            holding, exit_request = None, None
            if pending is not None:
                if now >= pending.expires_at or halted or a.equity <= 0:
                    risk.retire(pending.proposal.proposal_id)
                    missed += 1
                    log(now, "entry_cancelled", reason="EXPIRY_OR_RISK_HALT")
                    pending = None
                elif (
                    active
                    and now >= pending.decided_at + timedelta(seconds=sim.delay_seconds)
                    and q.observed_at > pending.decided_at
                ):
                    c = self._context(tick, account(tick))
                    units = quantity(pending.proposal.units, tick, sim)
                    fill = price(q.ask * (1 + sim.slippage_fraction), buy=True)
                    charge = fee(units, fill, sim)
                    cost_buffer = price(
                        max(
                            2 * charge
                            + units * (fill - q.bid + fill * sim.slippage_fraction)
                            + units * fill * sim.fx_fraction / (1 - sim.fx_fraction),
                            pending.proposal.cost_buffer * units / pending.proposal.units,
                        ),
                        buy=True,
                    )
                    filled_proposal = replace(
                        pending.proposal,
                        units=units,
                        price=fill,
                        cost_buffer=cost_buffer,
                        quoted_at=q.observed_at,
                    )
                    valid = (
                        units > 0
                        and fill * units >= c.evidence.eligibility.minimum_usd
                        and fill * units + charge <= cash
                    )
                    valid = (
                        valid
                        and fill
                        <= min(
                            pending.confirmation_close * (1 + pending.rules.max_chase_fraction),
                            pending.range_high * (1 + pending.rules.max_extension_fraction),
                        )
                        and q.bid > pending.range_high
                    )
                    valid = valid and (
                        units <= c.evidence.eligibility.max_units
                        and cost_buffer
                        <= units
                        * fill
                        * min(safety.max_cost_fraction, c.evidence.budget.max_cost_fraction)
                    )
                    try:
                        market_evidence(c, safety, now, window, pending.exit_deadline)
                    except ValueError:
                        valid = False
                    outcome = (
                        risk.admit_fill(filled_proposal, account(tick), now=now) if valid else None
                    )
                    if outcome is not None and outcome.passed:
                        cash -= units * fill + charge
                        costs += charge + units * ((q.ask - q.bid) / 2 + fill - q.ask)
                        holding = Holding(pending, units, fill, now, charge)
                        log(
                            now,
                            "entry_fill",
                            units=str(units),
                            price=str(fill),
                            fee_usd=str(charge),
                            unfilled_cancelled=str(pending.proposal.units - units),
                            signal_at=pending.decided_at.isoformat(),
                        )
                    else:
                        risk.retire(pending.proposal.proposal_id)
                        rejected += 1
                        log(
                            now,
                            "entry_cancelled",
                            reason="FILL_REVALIDATION",
                            reasons=() if outcome is None else outcome.reasons,
                        )
                    pending = None
            a = account(tick)
            risk.observe(a, iid, now=now)
            if tick.decide and active and pending is None and holding is None and a.equity > 0:
                c = self._context(tick, a)
                signal = strategy.propose_orb(c, now=now, rules=self.plan.orb)
                decisions.append(
                    {"at": now.isoformat(), "status": signal.status, "reasons": signal.reasons}
                )
                if signal.candidate is not None:
                    review = strategy.review_orb(signal.candidate, c, risk, now=now)
                    if review.decision.passed:
                        pending = signal.candidate
                        log(now, "signal_admitted", proposal=asdict(pending))
                    else:
                        rejected += 1
                        log(now, "signal_rejected", reasons=review.decision.reasons)
                elif signal.status not in ("waiting",):
                    rejected += 1
            value = D(0) if holding is None else holding.units * q.bid
            last_equity = (cash + value).quantize(Q)
            fx = tick.evidence.budget.usd_per_eur
            points.append(
                {
                    "at": now.isoformat(),
                    "equity": str((last_equity / fx).quantize(Q)),
                    "exposure": str((value / fx).quantize(Q)),
                    "equity_usd": str(last_equity),
                }
            )
        if pending is not None:
            risk.retire(pending.proposal.proposal_id)
            missed += 1
            log(ticks[-1].at, "entry_cancelled", reason="END_OF_DATA")
        summary = metrics(points, pnls, float(costs))
        final_fx = ticks[-1].evidence.budget.usd_per_eur
        summary.update(
            net_return=summary["total_return"],
            gross_return=float((last_equity + costs) / final_fx / sim.initial_eur - 1),
            average_win_usd=sum(x for x in pnls if x > 0) / len([x for x in pnls if x > 0])
            if any(x > 0 for x in pnls)
            else None,
            average_loss_usd=sum(x for x in pnls if x < 0) / len([x for x in pnls if x < 0])
            if any(x < 0 for x in pnls)
            else None,
            rejected_opportunities=rejected,
            missed_opportunities=missed,
            ambiguous_stop_first=ambiguous,
            open_units=str(D(0) if holding is None else holding.units),
        )
        manifest.update(
            status="synthetic" if data.classification == "synthetic_fixture" else "conditional",
            blockers=(),
            session_count=len(data.series.sessions),
            bars=len(data.series.bars),
            start=ticks[0].at.isoformat(),
            end=ticks[-1].at.isoformat(),
            available_at=max(b.first_known_at for b in data.series.bars).isoformat(),
            unresolved_inventory=holding is not None,
        )
        benchmarks = {
            "cash_eur": {"return": 0, "assumption": "Unconverted cash, zero interest."},
            "cash_usd": {"return": str((initial - funding) / final_fx / sim.initial_eur - 1)},
            "buy_and_hold": {
                "status": "blocked",
                "reason": "PASSIVE_OVERNIGHT_ELIGIBILITY_NOT_REVIEWED",
            },
            "hourly_strategies": {
                "status": "blocked",
                "reason": "INDEPENDENT_TIMEFRAME_COMPATIBILITY_REQUIRED",
            },
        }
        return Result(
            manifest,
            summary,
            tuple(events),
            tuple(points),
            tuple(trades),
            tuple(decisions),
            benchmarks,
        )

    def _context(self, tick: Tick, account: AccountSnapshot) -> OrbContext:
        sim = self.plan.simulation
        original = tick.evidence.budget
        budget = replace(
            original,
            equity_eur=(account.equity / original.usd_per_eur).quantize(Q),
            round_trip_fixed_usd=max(original.round_trip_fixed_usd, 2 * sim.commission_fixed),
            round_trip_fee_fraction=max(
                original.round_trip_fee_fraction, 2 * sim.commission_fraction
            ),
            slippage_fraction=max(original.slippage_fraction, 2 * sim.slippage_fraction),
            conversion_cost_fraction=max(original.conversion_cost_fraction, sim.fx_fraction),
        )
        return OrbContext(
            self.data.series,
            self.data.instrument,
            tick.quote,
            replace(tick.evidence, budget=budget),
            account,
            self.data.volume,
        )
