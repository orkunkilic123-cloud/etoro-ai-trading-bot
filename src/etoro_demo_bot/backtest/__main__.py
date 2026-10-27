"""Offline synthetic demonstration only. No credential or data downloads."""

import argparse
from decimal import Decimal
from pathlib import Path

from ..strategy.models import Rules, Strategy, Style
from .engine import Backtest
from .fixtures import synthetic_dataset
from .models import Plan, Simulation
from .report import comparison, write_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SYNTHETIC software demonstration; no profitability evidence."
    )
    parser.add_argument("--synthetic", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--eur", choices=("500", "1000"), default="500")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = {}
    for strategy in Strategy:
        for style in Style:
            name = f"{strategy.value}-{style.value}"
            plan = Plan(
                Rules(enabled=(strategy,), style=style), Simulation(initial_eur=Decimal(args.eur))
            )
            results[name] = Backtest(synthetic_dataset(), plan).run(args.output / name)
            write_report(results[name], args.output / f"{name}-report")
    comparison(results, args.output / "comparison.md")
    print("Synthetic reports written. These fixtures provide no evidence of profitability.")


if __name__ == "__main__":
    main()
