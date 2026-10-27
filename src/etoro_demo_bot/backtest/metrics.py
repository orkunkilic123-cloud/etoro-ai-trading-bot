"""Explicit metric conventions; undefined/small-sample ratios are null, never infinity."""

import math
import statistics
from datetime import datetime
from typing import Any


def metrics(points: list[dict[str, Any]], pnls: list[float], costs: float) -> dict[str, Any]:
    initial = float(points[0]["equity"])
    final = float(points[-1]["equity"])
    start = datetime.fromisoformat(points[0]["at"])
    end = datetime.fromisoformat(points[-1]["at"])
    seconds = (end - start).total_seconds()
    peak = initial
    drawdown = 0.0
    exposure = 0.0
    daily: dict[str, float] = {}
    for i, p in enumerate(points):
        value = float(p["equity"])
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
        daily[datetime.fromisoformat(p["at"]).date().isoformat()] = value
        if i:
            prev = points[i - 1]
            delta = (
                datetime.fromisoformat(p["at"]) - datetime.fromisoformat(prev["at"])
            ).total_seconds()
            exposure += (
                delta * float(prev["exposure"]) / float(prev["equity"])
                if float(prev["equity"]) > 0
                else 0
            )
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    total = final / initial - 1
    annual = (
        (final / initial) ** (365.25 * 86400 / seconds) - 1
        if seconds >= 365.25 * 86400 and final > 0
        else None
    )
    closes = list(daily.values())
    dates = [datetime.fromisoformat(day) for day in daily]
    consecutive = all((b - a).days == 1 for a, b in zip(dates, dates[1:], strict=False))
    returns = [b / a - 1 for a, b in zip(closes, closes[1:], strict=False) if a > 0]
    sharpe = None
    if consecutive and len(returns) >= 30 and statistics.stdev(returns) > 0:
        sharpe = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(365)
    return {
        "total_return": total,
        "annualized_return": annual,
        "maximum_drawdown": drawdown,
        "closed_positions": len(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "expectancy_usd": statistics.mean(pnls) if pnls else None,
        "sharpe_daily_365": sharpe,
        "time_weighted_exposure": exposure / seconds if seconds else 0,
        "trading_costs_usd": costs,
    }
