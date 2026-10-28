"""Conservative analytical fills. No order type, broker adapter or network."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP
from decimal import Decimal as D

from ...history.intraday import ResearchBar
from ..models import Simulation, Tick

Q = D(".000001")


def price(value: D, *, buy: bool) -> D:
    return value.quantize(Q, rounding=ROUND_UP if buy else ROUND_DOWN)


def fee(units: D, fill: D, sim: Simulation) -> D:
    return (sim.commission_fixed + units * fill * sim.commission_fraction).quantize(
        Q, rounding=ROUND_UP
    )


def quantity(requested: D, tick: Tick, sim: Simulation) -> D:
    step = tick.evidence.quantity_step
    possible = min(requested, requested * sim.fill_fraction, tick.available_units)
    return (possible / step).to_integral_value(rounding=ROUND_DOWN) * step


@dataclass(frozen=True)
class Touch:
    reason: str
    ceiling: D  # Long exit cannot receive better than this modelled bid.
    ambiguous: bool = False


def bar_touch(bar: ResearchBar, stop: D, target: D, half_spread: D) -> Touch | None:
    """OHLC mid-to-bid is an explicit spread assumption, not observed executable quotes."""
    b = bar.observation
    opening, low, high = (x * (1 - half_spread) for x in (b.open, b.low, b.high))
    if opening <= stop:
        return Touch("gap_stop", opening)
    if opening >= target:
        return Touch("gap_target_capped", target)
    if low <= stop:
        return Touch("ambiguous_stop_first" if high >= target else "stop", stop, high >= target)
    if high >= target:
        return Touch("target_capped", target)
    return None
