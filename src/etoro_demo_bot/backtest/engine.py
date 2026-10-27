"""Chronological single-instrument portfolio replay; simulation has no broker boundary."""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from decimal import Context as DecimalContext
from pathlib import Path
from typing import Any

from ..risk import AccountSnapshot, Exposure
from ..scanner.analysis import ScoringRules
from ..scanner.indicators import calculate
from ..scanner.models import Opportunity, ScanError, fresh
from ..strategy import Context, ExitMonitor, Journal, Position, StrategyEngine
from ..strategy.engine import earnings_safe
from ..strategy.journal import digest, encode
from ..strategy.models import Candidate, Evidence, StrategyError
from .metrics import metrics
from .models import Dataset, Plan, Tick
from .risk import SimulationRisk

D = Decimal
Q = D("0.000001")  # simulation cash/price precision, recorded assumption, not broker tick size


@dataclass
class Holding:
    candidate: Candidate
    units: Decimal
    entry: Decimal
    entry_fee_remaining: Decimal
    opened_at: datetime
    stop: Decimal
    peak: Decimal
    pnl: Decimal = D(0)


@dataclass(frozen=True)
class Result:
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    equity: tuple[dict[str, Any], ...]
    trades: tuple[dict[str, Any], ...]
    decisions: tuple[dict[str, Any], ...]
    benchmarks: dict[str, Any]


class Backtest:
    def __init__(self, data: Dataset, plan: Plan) -> None:
        data.validate()
        self.data, self.plan = data, plan

    def run(self, new_directory: Path) -> Result:
        # Exclusive run directory is the only possible source of simulation safety state.
        new_directory.mkdir(parents=True, exist_ok=False)
        (new_directory / "inputs.json").write_text(
            encode({"dataset": asdict(self.data), "plan": asdict(self.plan)}) + "\n",
            encoding="utf-8",
        )
        with localcontext(DecimalContext(prec=60)):
            return self._run(new_directory)

    def _run(self, directory: Path) -> Result:
        data, sim = self.data, self.plan.simulation
        journal = Journal.initialize(directory / "strategy.sqlite")
        strategy = StrategyEngine(journal, self.plan.rules)
        monitor = ExitMonitor(journal)
        risk = SimulationRisk(directory / "simulation-risk.sqlite", killed=sim.kill_switch)
        initial = sim.initial_eur * data.initial_usd_per_eur
        fx_cost = (initial * sim.fx_fraction).quantize(Q, rounding=ROUND_UP)
        cash = initial - fx_cost
        costs = fx_cost
        events: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        pnls: list[float] = []
        points = [
            {
                "at": data.start.isoformat(),
                "equity": str(initial),
                "cash": str(initial),
                "exposure": "0",
            }
        ]
        points.append(
            {"at": data.start.isoformat(), "equity": str(cash), "cash": str(cash), "exposure": "0"}
        )

        def log(at: datetime, kind: str, **details: Any) -> None:
            events.append(
                {"sequence": len(events) + 1, "at": at.isoformat(), "kind": kind, **details}
            )

        log(
            data.start,
            "funding",
            initial_eur=str(sim.initial_eur),
            gross_usd=str(initial),
            fx_cost=str(fx_cost),
        )
        risk.store.establish_day(data.start.date(), initial)
        day = data.start.date()
        last_equity = cash
        holding: Holding | None = None
        pending: Candidate | None = None
        exit_at: datetime | None = None
        last_bid = data.ticks[0].quote.bid
        for tick in data.ticks:
            now = tick.at.astimezone(UTC)
            while day < now.date():
                day += timedelta(days=1)
                if last_equity <= 0:
                    raise ValueError("Insolvent simulation cannot establish next baseline.")
                risk.store.establish_day(day, last_equity)
                log(
                    datetime.combine(day, datetime.min.time(), UTC),
                    "daily_baseline",
                    equity=str(last_equity),
                )
            last_bid = tick.quote.bid
            evidence = self._evidence(tick)
            is_open = (
                evidence.session.is_open is True
                and bool(evidence.session.source)
                and now < evidence.session_close
                and fresh(evidence.session.observed_at, now, 60)
                and evidence.session.valid_until > now
                and evidence.session.instrument_id == data.instrument.instrument_id
            )
            account = self._account(cash, holding, last_bid, now)
            observed = risk.observe(account, data.instrument.instrument_id, now=now)
            halted = any(x in observed.reasons for x in ("DAILY_LOSS_LIMIT", "KILL_SWITCH_ACTIVE"))
            if halted:
                log(now, "risk_halt", reasons=observed.reasons)
            if pending is not None:
                if now >= pending.expires_at:
                    risk.retire(pending.proposal.proposal_id)
                    log(
                        now,
                        "entry_cancelled",
                        reason="SIGNAL_EXPIRED",
                        proposal=pending.proposal.proposal_id,
                    )
                    pending = None
                elif (
                    now > pending.decision_at
                    and tick.quote.observed_at > pending.decision_at
                    and (now - pending.decision_at).total_seconds() >= sim.delay_seconds
                    and is_open
                ):
                    units = self._units(pending.proposal.units, tick)
                    price = (tick.quote.ask * (1 + sim.slippage_fraction)).quantize(
                        Q, rounding=ROUND_UP
                    )
                    fee = self._fee(units, price)
                    cost_buffer = (
                        2 * fee
                        + units * (price - tick.quote.bid)
                        + units * price * sim.slippage_fraction
                    ).quantize(Q, rounding=ROUND_UP)
                    proposal = replace(
                        pending.proposal,
                        units=units,
                        price=price,
                        quoted_at=now,
                        cost_buffer=cost_buffer,
                    )
                    valid = (
                        units > 0
                        and self._eligible(tick, pending.proposal.units, price)
                        and price * units + fee <= cash
                    )
                    try:
                        earnings_safe(
                            evidence.earnings,
                            data.instrument.instrument_id,
                            now,
                            pending.exit_deadline
                            or now + timedelta(seconds=pending.rules.swing_horizon_seconds),
                            pending.rules.earnings_buffer_seconds,
                        )
                    except StrategyError:
                        valid = False
                    decision = risk.admit_fill(proposal, account, now=now) if valid else None
                    if decision is not None and decision.passed:
                        cash -= price * units + fee
                        implicit = units * (
                            (tick.quote.ask - tick.quote.bid) / 2 + price - tick.quote.ask
                        )
                        costs += fee + implicit
                        assert pending.proposal.stop_loss is not None
                        holding = Holding(
                            pending,
                            units,
                            price,
                            fee,
                            now,
                            pending.proposal.stop_loss,
                            tick.quote.bid,
                        )
                        log(
                            now,
                            "entry_fill",
                            proposal=proposal.proposal_id,
                            units=str(units),
                            price=str(price),
                            commission=str(fee),
                            spread_slippage=str(implicit),
                            unfilled_cancelled=str(pending.proposal.units - units),
                        )
                    else:
                        risk.retire(pending.proposal.proposal_id)
                        log(
                            now,
                            "entry_cancelled",
                            reason="FILL_RISK_OR_CAPACITY",
                            reasons=decision.reasons
                            if decision
                            else ("ELIGIBILITY_CASH_OR_LIQUIDITY",),
                        )
                    pending = None
            if (
                holding is not None
                and exit_at is not None
                and is_open
                and now > exit_at
                and tick.quote.observed_at > exit_at
                and tick.close_allowed is True
                and (now - exit_at).total_seconds() >= sim.delay_seconds
            ):
                units = self._units(holding.units, tick)
                if units > 0:
                    price = (tick.quote.bid * (1 - sim.slippage_fraction)).quantize(
                        Q, rounding=ROUND_DOWN
                    )
                    fee = self._fee(units, price)
                    allocated = holding.entry_fee_remaining * units / holding.units
                    pnl = units * (price - holding.entry) - allocated - fee
                    cash += units * price - fee
                    implicit = units * (
                        (tick.quote.ask - tick.quote.bid) / 2 + tick.quote.bid - price
                    )
                    costs += fee + implicit
                    holding.pnl += pnl
                    holding.entry_fee_remaining -= allocated
                    holding.units -= units
                    trade = {
                        "at": now.isoformat(),
                        "opened_at": holding.opened_at.isoformat(),
                        "units": str(units),
                        "entry": str(holding.entry),
                        "exit": str(price),
                        "commission": str(fee),
                        "allocated_entry_fee": str(allocated),
                        "pnl": str(pnl),
                    }
                    trades.append(trade)
                    log(now, "exit_fill", **{k: v for k, v in trade.items() if k != "at"})
                    if holding.units == 0:
                        pnls.append(float(holding.pnl))
                        holding = None
                        exit_at = None
            account = self._account(cash, holding, last_bid, now)
            observation = risk.observe(account, data.instrument.instrument_id, now=now)
            halted = any(
                x in observation.reasons for x in ("DAILY_LOSS_LIMIT", "KILL_SWITCH_ACTIVE")
            )
            history = tuple(
                b
                for b in data.history
                if b.available_at <= now and b.candle.start + timedelta(hours=1) <= now
            )
            if holding is not None and exit_at is None:
                p = Position(
                    "simulated-position",
                    holding.candidate,
                    holding.opened_at,
                    now,
                    holding.units,
                    holding.entry,
                    holding.stop,
                    holding.peak,
                    now,
                    not halted,
                    now,
                )
                advice = monitor.evaluate(p, tick.quote, history, evidence, now=now)
                log(now, "exit_advice", action=advice.action, reasons=advice.reasons)
                if advice.action == "propose_close":
                    exit_at = now
                elif advice.action == "hold" and advice.proposed_stop is not None:
                    # Simulated stop-state change only, effective after this observed quote.
                    holding.stop = max(holding.stop, advice.proposed_stop)
                holding.peak = max(holding.peak, tick.quote.bid)
            if tick.decide and pending is None and holding is None:
                if not is_open:
                    log(now, "signal_rejected", reason="MARKET_CLOSED")
                elif len(history) < 35:
                    log(now, "signal_missed", reason="HISTORY_WARMUP")
                else:
                    try:
                        features = calculate(tuple(b.candle for b in history))
                        parts = ScoringRules().rank(features)
                        opportunity = Opportunity(
                            data.instrument,
                            sum(v for _, v in parts),
                            parts,
                            features,
                            tick.quote,
                            now,
                            now + timedelta(seconds=60),
                            D(0),
                            account.equity,
                        )
                        context = Context(opportunity, history, evidence, account)
                        outcome = strategy.propose(context, now=now)
                        log(
                            now, "strategy_decision", status=outcome.status, reasons=outcome.reasons
                        )
                        if outcome.candidate is not None:
                            review = strategy.review(outcome.candidate, account, risk, now=now)
                            log(
                                now,
                                "risk_review",
                                passed=review.decision.passed,
                                reasons=review.decision.reasons,
                            )
                            if review.decision.passed:
                                pending = outcome.candidate
                    except ScanError as error:
                        log(now, "signal_rejected", reason=str(error))
            elif tick.decide:
                log(now, "signal_missed", reason="POSITION_OR_INTENT_ALREADY_ACTIVE")
            last_equity = account.equity
            point = {
                "at": now.isoformat(),
                "equity": str(account.equity),
                "cash": str(cash),
                "exposure": str(holding.units * last_bid if holding else D(0)),
            }
            points.append(point)
            log(now, "valuation", **{k: v for k, v in point.items() if k != "at"})
        if pending is not None:
            risk.retire(pending.proposal.proposal_id)
            log(data.end, "entry_cancelled", reason="END_OF_REPLAY")
        manifest = {
            "engine_version": "1",
            "source_digest": digest(
                {
                    p.relative_to(Path(__file__).parents[1]).as_posix(): p.read_text(
                        encoding="utf-8"
                    )
                    for folder in ("backtest", "strategy", "risk", "scanner")
                    for p in sorted((Path(__file__).parents[1] / folder).glob("*.py"))
                }
            ),
            "dataset_digest": digest(asdict(data)),
            "plan": asdict(self.plan),
            "plan_digest": digest(asdict(self.plan)),
            "provenance": asdict(data.provenance),
            "open_units": str(holding.units if holding else D(0)),
            "limitations": [
                "Single-instrument USD underlying portfolio; no corporate-action engine.",
                "Quotes drive fills; no inferred intrabar paths or exchange microstructure.",
                "Synthetic fixtures are not evidence of profitability."
                if data.provenance.kind == "synthetic"
                else (
                    "Historical provenance needs independent review; no profitability conclusion."
                ),
                "Open positions are marked at final bid, not forcibly liquidated.",
            ],
        }
        from .benchmark import benchmarks

        return Result(
            manifest,
            metrics(points, pnls, float(costs)),
            tuple(events),
            tuple(points),
            tuple(trades),
            journal.events(),
            benchmarks(data, self.plan),
        )

    def _evidence(self, tick: Tick) -> Evidence:
        sim = self.plan.simulation
        budget = replace(
            tick.evidence.budget,
            equity_eur=sim.initial_eur,
            conversion_cost_fraction=sim.fx_fraction,
            round_trip_fixed_usd=2 * sim.commission_fixed,
            round_trip_fee_fraction=2 * sim.commission_fraction,
            slippage_fraction=2 * sim.slippage_fraction,
        )
        return replace(tick.evidence, budget=budget)

    def _eligible(self, tick: Tick, requested: Decimal, price: Decimal) -> bool:
        e = tick.evidence
        iid = self.data.instrument.instrument_id
        return (
            e.eligibility.instrument_id == iid
            and fresh(e.eligibility.observed_at, tick.at, 60)
            and e.eligibility.underlying_long is True
            and e.product.instrument_id == iid
            and e.product.underlying is True
            and e.product.unleveraged is True
            and e.product.currency == "USD"
            and bool(e.product.source)
            and e.quantity_step <= 1
            and e.product.expires_at > tick.at
            and e.quantity_step_verified is True
            and e.quantity_step > 0
            and requested <= e.eligibility.max_units
            and requested * price >= e.eligibility.minimum_usd
            and (e.eligibility.fractional or requested == requested.to_integral_value())
        )

    def _units(self, requested: Decimal, tick: Tick) -> Decimal:
        step = tick.evidence.quantity_step
        if not tick.evidence.quantity_step_verified or step <= 0:
            return D(0)
        amount = min(
            requested,
            tick.available_units,
            max(step, requested * self.plan.simulation.fill_fraction),
        )
        return (amount / step).to_integral_value(rounding=ROUND_DOWN) * step

    def _fee(self, units: Decimal, price: Decimal) -> Decimal:
        sim = self.plan.simulation
        return (sim.commission_fixed + units * price * sim.commission_fraction).quantize(
            Q, rounding=ROUND_UP
        )

    @staticmethod
    def _account(
        cash: Decimal, holding: Holding | None, bid: Decimal, now: datetime
    ) -> AccountSnapshot:
        value = holding.units * bid if holding else D(0)
        exposures = (
            (Exposure(holding.candidate.proposal.instrument_id, value, 1),) if holding else ()
        )
        return AccountSnapshot(
            "backtest-demo",
            cash + value,
            cash,
            exposures,
            now,
            demo=True,
            complete=True,
            cash_flows_reconciled=True,
        )
