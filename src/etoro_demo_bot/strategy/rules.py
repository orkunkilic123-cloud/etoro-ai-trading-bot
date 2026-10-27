"""Pure long-only entry rules over information already validated by the coordinator."""

from decimal import Decimal as D

from ..scanner.models import Features
from .models import Rules, Strategy


def regime(f: Features) -> str:
    if f.ema > f.sma and f.momentum > 0:
        return "uptrend"
    if f.ema < f.sma and f.momentum < -0.05:
        return "downtrend"
    return "range"


def matches(f: Features, rules: Rules) -> tuple[Strategy, ...]:
    state = regime(f)
    volume = f.relative_volume
    found: list[Strategy] = []
    if (
        state == "uptrend"
        and f.close > f.previous_high
        and D(str(f.momentum)) >= rules.minimum_momentum
        and volume is not None
        and D(str(volume)) >= rules.minimum_relative_volume
    ):
        found.append(Strategy.BREAKOUT)
    if (
        state == "uptrend"
        and f.close > f.ema > f.sma
        and f.macd > f.macd_signal
        and volume is not None
        and D(str(volume)) >= rules.minimum_relative_volume
    ):
        found.append(Strategy.TREND)
    if state == "range" and D(str(f.rsi)) <= rules.oversold_rsi and f.close < f.sma - f.atr:
        found.append(Strategy.REVERSION)
    return tuple(s for s in found if s in rules.enabled)
