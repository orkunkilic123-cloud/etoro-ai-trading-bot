"""Synthetic prices, eligibility, FX, sessions and gaps; never market evidence."""

from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal as D

from ..backtest.fixtures import synthetic_dataset
from ..risk import AccountSnapshot
from ..scanner.analysis import ScoringRules
from ..scanner.indicators import calculate
from ..scanner.models import Opportunity
from ..strategy import Context
from ..strategy.journal import digest
from .models import Block, Move, Pool


def synthetic_inputs(eur: int = 500) -> tuple[Context, Pool]:
    if eur not in (500, 1000):
        raise ValueError("EUR_500_OR_1000_REQUIRED")
    data = synthetic_dataset(1)
    tick, now = data.ticks[0], data.start
    bars = tuple(b for b in data.history if b.available_at <= now)
    features = calculate(tuple(b.candle for b in bars))
    parts = ScoringRules().rank(features)
    evidence = replace(tick.evidence, budget=replace(tick.evidence.budget, equity_eur=D(eur)))
    equity = D(eur) * evidence.budget.usd_per_eur
    account = AccountSnapshot(
        "synthetic-mc",
        equity,
        equity,
        (),
        now,
        demo=True,
        complete=True,
        cash_flows_reconciled=True,
    )
    opportunity = Opportunity(
        data.instrument,
        sum(p[1] for p in parts),
        parts,
        features,
        tick.quote,
        now,
        now + timedelta(seconds=60),
        D(10),
        equity,
    )
    variants = (
        Move(D(1), D("1.04"), D(".999"), D("1.03")),
        Move(D(1), D("1.001"), D(".96"), D(".97")),
        Move(D(".90"), D(".92"), D(".88"), D(".91")),
        Move(D(1), D("1.001"), D(".999"), D(1)),
        Move(D(1), D("1.04"), D(".96"), D(1)),
    )
    blocks = tuple(
        Block(
            now - timedelta(hours=(20 - i) * 6),
            now - timedelta(hours=(19 - i) * 6),
            now - timedelta(hours=(19 - i) * 6),
            (variants[i % 5],) * 6,
        )
        for i in range(20)
    )
    pool = Pool(
        1,
        "synthetic",
        "SYNTHETIC_OHLC_GAP_SCENARIOS",
        digest([asdict(b) for b in blocks]),
        6 * 3600,
        blocks,
    )
    return Context(opportunity, bars, evidence, account), pool
