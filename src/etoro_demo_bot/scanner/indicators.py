"""Deterministic SMA-seeded EMA and Wilder RSI/ATR, using completed OHLCV bars."""

import math
import statistics
from datetime import timedelta

from .models import Candle, Features, ScanError, aware


def sma(values: tuple[float, ...], period: int) -> float:
    if period < 1 or len(values) < period or not all(math.isfinite(x) for x in values):
        raise ScanError("INVALID_INDICATOR_INPUT")
    return statistics.fmean(values[-period:])


def ema_series(values: tuple[float, ...], period: int) -> tuple[float, ...]:
    seed = sma(values[:period], period)
    result = [seed]
    alpha = 2 / (period + 1)
    for value in values[period:]:
        if not math.isfinite(value):
            raise ScanError("INVALID_INDICATOR_INPUT")
        result.append(alpha * value + (1 - alpha) * result[-1])
    return tuple(result)


def wilder(values: tuple[float, ...], period: int) -> float:
    result = sma(values[:period], period)
    for value in values[period:]:
        result = (result * (period - 1) + value) / period
    return result


def calculate(candles: tuple[Candle, ...], *, interval_seconds: int = 3600) -> Features:
    if len(candles) < 35 or interval_seconds <= 0:
        raise ScanError("INSUFFICIENT_HISTORY")
    for index, bar in enumerate(candles):
        prices = (bar.open, bar.high, bar.low, bar.close)
        if (
            not aware(bar.start)
            or not all(math.isfinite(x) and x > 0 for x in prices)
            or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            or bar.volume is not None
            and (not math.isfinite(bar.volume) or bar.volume < 0)
            or index > 0
            and bar.start - candles[index - 1].start < timedelta(seconds=interval_seconds)
        ):
            raise ScanError("INVALID_HISTORY")
    closes = tuple(x.close for x in candles)
    changes = tuple(b - a for a, b in zip(closes, closes[1:], strict=False))
    gains = wilder(tuple(max(x, 0) for x in changes), 14)
    losses = wilder(tuple(max(-x, 0) for x in changes), 14)
    rsi = (
        50.0 if gains == losses == 0 else 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    )
    fast, slow = ema_series(closes, 12), ema_series(closes, 26)
    macds = tuple(a - b for a, b in zip(fast[14:], slow, strict=True))
    ranges = tuple(
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in zip(candles, candles[1:], strict=False)
    )
    volumes = tuple(x.volume for x in candles[-21:-1])
    relative = None
    if all(x is not None and x > 0 for x in volumes) and candles[-1].volume is not None:
        average = statistics.fmean(x for x in volumes if x is not None)
        relative = candles[-1].volume / average
    returns = tuple(math.log(b / a) for a, b in zip(closes[-21:-1], closes[-20:], strict=True))
    return Features(
        sma(closes, 20),
        ema_series(closes, 20)[-1],
        rsi,
        macds[-1],
        ema_series(macds, 9)[-1],
        wilder(ranges, 14),
        relative,
        statistics.pstdev(returns),
        closes[-1] / closes[-11] - 1,
        max(x.high for x in candles[-21:-1]),
        closes[-1],
    )
