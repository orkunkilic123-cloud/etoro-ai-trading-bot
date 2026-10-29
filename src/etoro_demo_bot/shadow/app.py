"""Connect existing synthetic data, strategy/risk replay and reporting through durable runs."""

from datetime import datetime
from decimal import Decimal

from ..backtest.engine import Backtest, Result
from ..backtest.fixtures import synthetic_dataset as hourly_dataset
from ..backtest.intraday.engine import IntradayBacktest
from ..backtest.intraday.fixtures import synthetic_dataset as orb_dataset
from ..backtest.intraday.models import Plan as OrbPlan
from ..backtest.intraday.report import write_report
from ..backtest.models import Plan, Simulation
from ..strategy.models import Rules
from .reports import dashboard, write_summary
from .store import Runs, ShadowError


def run_once(store: Runs, pipeline: str, eur: int, *, now: datetime) -> str:
    """Claim before computation; exceptions leave a durable failed or running marker."""
    from datetime import UTC

    if now.tzinfo is None:
        raise ShadowError("INVALID_OR_MISSED_SLOT")
    identity = store.claim(pipeline, eur, now.astimezone(UTC).date(), now=now)
    destination = store.root / identity
    try:
        destination.mkdir(exist_ok=False)
        dashboard(store, now=now)
        simulation = Simulation(initial_eur=Decimal(eur))
        result: Result
        if pipeline == "hourly":
            result = Backtest(hourly_dataset(), Plan(Rules(), simulation)).run(
                destination / "state"
            )
        else:
            result = IntradayBacktest(orb_dataset(), OrbPlan(simulation=simulation)).run(
                destination / "state"
            )
        # Common result bundle already handles either engine; add status for the hourly baseline.
        result.manifest.setdefault("status", "synthetic")
        result.manifest["shadow_valuation_currency"] = "EUR" if pipeline == "orb" else "USD"
        write_report(result, destination / "report")
        write_summary(result, destination / "summary.json")
        store.finish(identity, "blocked" if result.manifest["status"] == "blocked" else "completed")
    except Exception:
        store.finish(identity, "failed")
        dashboard(store, now=now)
        raise
    dashboard(store, now=now)
    if result.manifest["status"] == "blocked":
        raise ShadowError("RESEARCH_BLOCKED")
    return identity
