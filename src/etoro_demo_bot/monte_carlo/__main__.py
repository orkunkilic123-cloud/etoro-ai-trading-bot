"""Offline synthetic demo. Never opens existing safety state or loads credentials."""

import argparse
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from ..risk import RiskEngine, RiskStore
from ..strategy import Journal, Rules, StrategyEngine
from .engine import MonteCarloAgent
from .fixtures import synthetic_inputs
from .models import Settings
from .report import write_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory only")
    parser.add_argument("--eur", type=int, choices=(500, 1000), default=500)
    parser.add_argument("--seed", type=int, default=19)
    args = parser.parse_args()
    settings = Settings(seed=args.seed)
    context, pool = synthetic_inputs(args.eur)
    args.output.mkdir(parents=True, exist_ok=False)
    store = RiskStore.initialize(args.output / "synthetic-risk.sqlite", context.account.account_id)
    store.establish_day(context.account.observed_at.date(), context.account.equity)
    # Explicitly arm only the newly created synthetic research store, never production state.
    store.set_kill_switch(False, acknowledged=True)
    strategy = StrategyEngine(
        Journal.initialize(args.output / "strategy.sqlite"),
        replace(Rules(), take_profit_r=Decimal(2)),
    )
    result = MonteCarloAgent().run(
        context,
        pool,
        strategy,
        RiskEngine(store),
        now=context.account.observed_at,
        settings=settings,
    )
    write_report(result, args.output / "report")
    print(
        f"SYNTHETIC research only: {result.status}; {len(result.trials)} trials; seed {args.seed}"
    )
    return 0 if result.status == "simulated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
