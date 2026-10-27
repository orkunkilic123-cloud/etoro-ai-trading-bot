"""Passive comparators, not risk-approved strategy proposals or executable orders."""

from datetime import datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any

from .metrics import metrics
from .models import Dataset, Plan

D = Decimal
Q = D("0.000001")


def benchmarks(data: Dataset, plan: Plan) -> dict[str, Any]:
    from .engine import Backtest

    simulator = Backtest(data, plan)
    sim = plan.simulation
    initial = sim.initial_eur * data.initial_usd_per_eur
    conversion = (initial * sim.fx_fraction).quantize(Q, rounding=ROUND_UP)
    cash = initial - conversion
    units = D(0)
    cost = conversion
    pending_at: datetime | None = None
    attempted = False
    equity = [{"at": data.start.isoformat(), "equity": str(initial), "exposure": "0"}]
    cash_points = [{"at": data.start.isoformat(), "equity": str(initial), "exposure": "0"}]
    fills: list[dict[str, Any]] = []
    for tick in data.ticks:
        session = tick.evidence.session
        tradable = session.is_open is True and session.observed_at <= tick.at < session.valid_until
        if tradable and not attempted:
            if pending_at is None:
                pending_at = tick.at
            elif (
                tick.at - pending_at
            ).total_seconds() >= sim.delay_seconds and tick.quote.observed_at > pending_at:
                attempted = True
                price = (tick.quote.ask * (1 + sim.slippage_fraction)).quantize(
                    Q, rounding=ROUND_UP
                )
                possible = min(
                    (cash - sim.commission_fixed) / (price * (1 + sim.commission_fraction)),
                    tick.evidence.eligibility.max_units,
                )
                possible = max(D(0), possible)
                requested = (possible / tick.evidence.quantity_step).to_integral_value(
                    rounding=ROUND_DOWN
                ) * tick.evidence.quantity_step
                if simulator._eligible(tick, requested, price):
                    units = simulator._units(requested, tick)
                    if units > 0:
                        fee = simulator._fee(units, price)
                        if units * price + fee <= cash:
                            cash -= units * price + fee
                            cost += fee + units * (
                                (tick.quote.ask - tick.quote.bid) / 2 + price - tick.quote.ask
                            )
                            fills.append(
                                {
                                    "at": tick.at.isoformat(),
                                    "units": str(units),
                                    "price": str(price),
                                    "fee": str(fee),
                                }
                            )
                        else:
                            units = D(0)
        equity.append(
            {
                "at": tick.at.isoformat(),
                "equity": str(cash + units * tick.quote.bid),
                "exposure": str(units * tick.quote.bid),
            }
        )
        cash_points.append(
            {"at": tick.at.isoformat(), "equity": str(initial - conversion), "exposure": "0"}
        )
    return {
        "cash_usd": {
            "metrics": metrics(cash_points, [], float(conversion)),
            "assumption": "No interest; same initial EUR-to-USD conversion; no trades.",
        },
        "buy_and_hold": {
            "metrics": metrics(equity, [], float(cost)),
            "fills": fills,
            "equity": equity,
            "assumption": (
                "Passive all-cash allocation, later-quote entry and identical costs/eligibility; "
                "no strategy stops. Not a risk-approved strategy."
            ),
        },
    }
