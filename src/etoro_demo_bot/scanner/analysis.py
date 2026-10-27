"""Transparent ranking and conservative minimum-allocation feasibility, not trade sizing."""

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, localcontext

from ..risk.models import money
from .models import Eligibility, Features, Quote, ScanError, fresh

D = Decimal


@dataclass(frozen=True)
class Budget:
    equity_eur: Decimal
    usd_per_eur: Decimal
    fx_observed_at: datetime
    fx_source: str
    # Explicit conservative conversion haircut, commissions, spread and slippage.
    conversion_cost_fraction: Decimal
    round_trip_fixed_usd: Decimal
    round_trip_fee_fraction: Decimal
    slippage_fraction: Decimal
    max_allocation_fraction: Decimal = D("0.20")
    max_cost_fraction: Decimal = D("0.02")

    def minimum_cash(
        self, eligibility: Eligibility, quote: Quote, now: datetime
    ) -> tuple[Decimal, Decimal]:
        positive = (
            self.equity_eur,
            self.usd_per_eur,
            self.max_allocation_fraction,
            self.max_cost_fraction,
        )
        costs = (
            self.conversion_cost_fraction,
            self.round_trip_fixed_usd,
            self.round_trip_fee_fraction,
            self.slippage_fraction,
        )
        if (
            not all(money(v, positive=True) for v in positive)
            or not all(money(v) for v in costs)
            or not self.fx_source
            or not fresh(self.fx_observed_at, now, 60)
            or self.max_allocation_fraction > 1
            or self.max_cost_fraction > 1
            or any(
                v >= 1
                for v in (
                    self.conversion_cost_fraction,
                    self.round_trip_fee_fraction,
                    self.slippage_fraction,
                )
            )
            or not money(eligibility.minimum_usd, positive=True)
            or not money(eligibility.max_units, positive=True)
            or not money(quote.ask, positive=True)
            or not money(quote.bid, positive=True)
            or quote.bid > quote.ask
        ):
            raise ScanError("INVALID_BUDGET_OR_COST_EVIDENCE")
        with localcontext() as context:
            context.prec = 60
            budget = self.equity_eur * self.usd_per_eur * (1 - self.conversion_cost_fraction)
            units = eligibility.minimum_usd / quote.ask
            if not eligibility.fractional:
                units = units.to_integral_value(rounding=ROUND_CEILING)
            if units > eligibility.max_units:
                raise ScanError("MINIMUM_EXCEEDS_MAX_UNITS")
            notional = units * quote.ask
            cost = (
                self.round_trip_fixed_usd
                + notional * (self.round_trip_fee_fraction + self.slippage_fraction)
                + units * (quote.ask - quote.bid)
            )
            # FX conversion cost is also included in the cost-efficiency screen, pro rata.
            fx_cost = notional * self.conversion_cost_fraction / (1 - self.conversion_cost_fraction)
            if cost + fx_cost > notional * self.max_cost_fraction:
                raise ScanError("COSTS_TOO_HIGH")
            cash = notional + cost
            if cash > budget * self.max_allocation_fraction:
                raise ScanError("MINIMUM_UNAFFORDABLE")
            return cash, budget


@dataclass(frozen=True)
class ScoringRules:
    breakout_weight: float = 35
    trend_weight: float = 30
    volume_weight: float = 20
    reversion_weight: float = 15
    volume_threshold: float = 2
    momentum_threshold: float = 0.02
    oversold_rsi: float = 30
    max_bar_volatility: float = 0.1
    minimum_score: float = 15

    def __post_init__(self) -> None:
        weights = (
            self.breakout_weight,
            self.trend_weight,
            self.volume_weight,
            self.reversion_weight,
        )
        if (
            not all(math.isfinite(v) and v >= 0 for v in weights)
            or not 0 < sum(weights) <= 100
            or not all(
                math.isfinite(v)
                for v in (
                    self.volume_threshold,
                    self.momentum_threshold,
                    self.oversold_rsi,
                    self.max_bar_volatility,
                    self.minimum_score,
                )
            )
            or self.volume_threshold <= 1
            or self.momentum_threshold <= 0
            or not 0 < self.oversold_rsi < 50
            or self.max_bar_volatility <= 0
            or not 0 <= self.minimum_score <= 100
        ):
            raise ScanError("INVALID_SCORING_RULES")

    def rank(self, f: Features) -> tuple[tuple[str, float], ...]:
        if f.volatility > self.max_bar_volatility:
            raise ScanError("VOLATILITY_LIMIT")
        checks = (
            (
                "momentum_breakout",
                self.breakout_weight,
                f.close > f.previous_high and f.momentum >= self.momentum_threshold,
            ),
            (
                "trend_continuation",
                self.trend_weight,
                f.close > f.ema > f.sma and f.macd > f.macd_signal and f.momentum > 0,
            ),
            (
                "unusual_volume",
                self.volume_weight,
                f.relative_volume is not None and f.relative_volume >= self.volume_threshold,
            ),
            (
                "potential_mean_reversion",
                self.reversion_weight,
                f.rsi <= self.oversold_rsi and f.close < f.sma - f.atr,
            ),
        )
        return tuple((name, weight) for name, weight, matched in checks if matched and weight > 0)
