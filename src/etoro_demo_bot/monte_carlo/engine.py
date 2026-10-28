"""Conditional block bootstrap after the unchanged strategy/risk handoff."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Context as DecimalContext
from decimal import Decimal as D
from decimal import localcontext
from random import Random
from typing import Any

from ..risk import RiskEngine
from ..strategy import Context, StrategyEngine
from ..strategy.journal import digest
from ..strategy.models import Candidate
from .models import Block, Pool, Settings, Trial


@dataclass(frozen=True)
class Result:
    status: str
    reasons: tuple[str, ...]
    inputs_digest: str
    trials: tuple[Trial, ...]
    metrics: dict[str, Any]
    manifest: dict[str, Any]

    @property
    def execution_authorized(self) -> bool:
        return False


def path_outcome(
    candidate: Candidate,
    block: Block,
    context: Context,
    index: int,
    sampled: int,
) -> Trial:
    """Caller validates inputs. Prices are hypothetical, not broker fills."""
    p, b = candidate.proposal, context.evidence.budget
    assert p.price is not None and p.stop_loss is not None
    quote = context.opportunity.quote
    # Constant relative spread from the decision quote; price is already the ask.
    half_spread = (quote.ask - quote.bid) / (quote.ask + quote.bid)
    slippage = b.slippage_fraction / 2
    entry = p.price * (1 + slippage)
    mid = p.price / (1 + half_spread)
    outcome, exit_price, exit_mid, step = "horizon", D(0), D(0), 0
    for current_step, m in enumerate(block.moves, 1):
        step = current_step
        op, hi, lo, close = (mid * v for v in (m.open, m.high, m.low, m.close))
        bid_open, bid_high, bid_low = (v * (1 - half_spread) for v in (op, hi, lo))
        # Opening events precede later intrabar extrema. Ambiguous intrabar hits lose first.
        if bid_open <= p.stop_loss:
            outcome, exit_price, exit_mid = "gap_stop", bid_open, op
        elif candidate.take_profit is not None and bid_open >= candidate.take_profit:
            outcome, exit_price = "target", candidate.take_profit
            exit_mid = exit_price / (1 - half_spread)
        elif bid_low <= p.stop_loss:
            outcome, exit_price = "stop", p.stop_loss
            exit_mid = exit_price / (1 - half_spread)
        elif candidate.take_profit is not None and bid_high >= candidate.take_profit:
            outcome, exit_price = "target", candidate.take_profit
            exit_mid = exit_price / (1 - half_spread)
        else:
            mid = close
            exit_price, exit_mid = close * (1 - half_spread), close
            continue
        break
    before_slip = exit_price
    exit_price *= 1 - slippage
    fees = b.round_trip_fixed_usd + p.units * (entry + exit_price) * b.round_trip_fee_fraction / 2
    pnl = p.units * (exit_price - entry) - fees
    # Spread/slippage are attribution, not an additional cash deduction.
    costs = fees + p.units * (
        p.price
        - p.price / (1 + half_spread)
        + entry
        - p.price
        + exit_mid
        - before_slip
        + before_slip
        - exit_price
    )
    funding_fx = b.equity_eur * b.usd_per_eur * b.conversion_cost_fraction
    return Trial(
        index, sampled, outcome, step, exit_price, pnl, costs, (pnl - funding_fx) / b.usd_per_eur
    )


def summarize(trials: tuple[Trial, ...]) -> dict[str, Any]:
    values = sorted(t.pnl_usd for t in trials)
    n = D(len(values))
    return {
        "expected_pnl_usd": sum(values) / n,
        "expected_portfolio_pnl_eur": sum(t.portfolio_pnl_eur for t in trials) / n,
        "mean_cost_usd": sum(t.costs_usd for t in trials) / n,
        "loss_frequency": D(sum(v < 0 for v in values)) / n,
        "worst_pnl_usd": values[0],
        "p05_pnl_usd": values[499],
        "p50_pnl_usd": values[4999],
        "p95_pnl_usd": values[9499],
        "var95_usd": max(D(0), -values[499]),
        "expected_shortfall95_usd": max(D(0), -sum(values[:500]) / 500),
        "var99_usd": max(D(0), -values[99]),
        "expected_shortfall99_usd": max(D(0), -sum(values[:100]) / 100),
        "outcomes": {
            name: sum(t.outcome == name for t in trials)
            for name in ("stop", "gap_stop", "target", "horizon")
        },
    }


class MonteCarloAgent:
    """Research only. One journalled candidate review, not 10,000 reservations."""

    def run(
        self,
        context: Context,
        pool: Pool,
        strategy: StrategyEngine,
        risk: RiskEngine,
        *,
        now: datetime,
        settings: Settings | None = None,
    ) -> Result:
        settings = settings or Settings()
        settings.__post_init__()
        pool.validate(now, context.opportunity.instrument.instrument_id)
        with localcontext(DecimalContext(prec=60)):
            manifest = {
                "model": "conditional-whole-block-bootstrap-v1",
                "classification": pool.classification,
                "settings": asdict(settings),
                "pool": asdict(pool),
                "context": asdict(context),
                "rules": asdict(strategy.rules),
                "risk_policy": asdict(risk.policy),
                "decision_at": now,
                "execution_authorized": False,
                "limitations": [
                    "SYNTHETIC engineering scenarios; not profitability evidence.",
                    "Conditional on an entry; not historical strategy performance.",
                    "Empirical resampling cannot invent unseen tail events.",
                    "Fixed spread/fees/FX and full fills are assumptions.",
                    "Static stop/optional target; no trailing/earnings/session exit replay.",
                    "No real-data qualification, parameter optimization or order authorization.",
                ],
            }
            identity = digest(manifest)
            outcome = strategy.propose(context, now=now)
            if outcome.candidate is None:
                return Result("blocked", outcome.reasons, identity, (), {}, manifest)
            candidate = outcome.candidate
            if candidate.exit_deadline is not None and (
                now + timedelta(seconds=pool.horizon_seconds) > candidate.exit_deadline
            ):
                return Result(
                    "blocked", ("HORIZON_EXCEEDS_EXIT_DEADLINE",), identity, (), {}, manifest
                )
            if pool.horizon_seconds > candidate.rules.swing_horizon_seconds:
                return Result(
                    "blocked",
                    ("HORIZON_EXCEEDS_REVIEWED_PLANNING_WINDOW",),
                    identity,
                    (),
                    {},
                    manifest,
                )
            b, p = context.evidence.budget, candidate.proposal
            assert p.price is not None and p.stop_loss is not None
            if b.equity_eur not in (D(500), D(1000)):
                return Result("blocked", ("UNSUPPORTED_PORTFOLIO",), identity, (), {}, manifest)
            entry = p.price * (1 + b.slippage_fraction / 2)
            entry_cash = p.units * entry * (1 + b.round_trip_fee_fraction / 2)
            entry_cash += b.round_trip_fixed_usd / 2
            funding_fx = b.equity_eur * b.usd_per_eur * b.conversion_cost_fraction
            if entry_cash > min(
                context.account.available_balance, b.equity_eur * b.usd_per_eur - funding_fx
            ):
                return Result(
                    "blocked", ("SIMULATED_ENTRY_UNAFFORDABLE",), identity, (), {}, manifest
                )
            review = strategy.review(candidate, context.account, risk, now=now)
            manifest["candidate"] = asdict(candidate)
            manifest["risk_decision"] = asdict(review.decision)
            # State-dependent risk result participates in the report identity.
            identity = digest(manifest)
            if not review.decision.passed:
                return Result("blocked", review.decision.reasons, identity, (), {}, manifest)
            rng = Random(settings.seed)
            draws = [rng.randrange(len(pool.blocks)) for _ in range(settings.trials)]
            trials = tuple(
                path_outcome(candidate, pool.blocks[j], context, i, j) for i, j in enumerate(draws)
            )
            metrics = summarize(trials)
            metrics["funding_fx_cost_usd"] = funding_fx
            metrics["mean_total_cost_usd"] = metrics["mean_cost_usd"] + funding_fx
            metrics["starting_equity_eur"] = b.equity_eur
            metrics["expected_final_equity_eur"] = (
                b.equity_eur + metrics["expected_portfolio_pnl_eur"]
            )
            metrics["exceeds_planned_risk_frequency"] = (
                D(sum(t.pnl_usd < -(review.decision.risk_amount or D(0)) for t in trials))
                / settings.trials
            )
            return Result(
                "simulated",
                ("RESEARCH_ONLY_EXECUTION_DISABLED",),
                identity,
                trials,
                metrics,
                manifest,
            )
