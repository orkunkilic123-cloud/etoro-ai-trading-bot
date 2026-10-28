"""Separate 10,000-draw ORB outcome bootstrap, not the synthetic path Pool interface."""

import math
import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from typing import Any

from ..backtest.engine import Result
from ..scanner.models import aware
from ..strategy.journal import digest


@dataclass(frozen=True)
class Comparison:
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    scenarios: tuple[dict[str, Any], ...]


def compare(
    pool: tuple[Result, ...], held_out: Result, *, as_of: datetime, seed: int = 19
) -> Comparison:
    """Fail closed on incompatible, malformed or future result evidence."""
    try:
        return _compare(pool, held_out, as_of=as_of, seed=seed)
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        return Comparison(
            {
                "model": "orb-session-outcome-bootstrap-v1",
                "status": "blocked",
                "blockers": ["INVALID_REPLAY_RESULT_EVIDENCE"],
                "execution_authorized": False,
            },
            {},
            (),
        )


def _compare(
    pool: tuple[Result, ...], held_out: Result, *, as_of: datetime, seed: int = 19
) -> Comparison:
    """Each draw is a single same-capital session, never a compounded future portfolio.

    Reuse realized risk-admitted costs/sizes. No claim that evolving-equity admission can
    be reproduced by a return bootstrap. Whole-session dependence is preserved.
    """
    manifest: dict[str, Any] = {
        "model": "orb-session-outcome-bootstrap-v1",
        "status": "blocked",
        "seed": seed,
        "execution_authorized": False,
        "trials": 10000,
        "limitations": [
            "Model-based stress resampling, not a predictive probability.",
            "10,000 draws are not 10,000 independent historical observations.",
            "Same-capital single-session outcomes, no sequential portfolio risk rerun.",
            "No unseen tails, leverage, latency forecast or optimization.",
        ],
    }
    if type(seed) is not int or not 0 <= seed < 2**64 or not aware(as_of):
        manifest["blockers"] = ["INVALID_BOOTSTRAP_SETTINGS"]
        return Comparison(manifest, {}, ())
    if not 20 <= len(pool) <= 10000 or held_out.manifest.get("status") not in (
        "synthetic",
        "conditional",
    ):
        manifest["blockers"] = ["INSUFFICIENT_QUALIFIED_TRAINING_SESSIONS"]
        return Comparison(manifest, {}, ())
    if (
        held_out.manifest.get("session_count") != 1
        or held_out.manifest.get("unresolved_inventory") is not False
    ):
        manifest["blockers"] = ["HELD_OUT_HORIZON_OR_INVENTORY_INCOMPATIBLE"]
        return Comparison(manifest, {}, ())
    for result in (held_out, *pool):
        if not all(
            math.isfinite(float(result.metrics[k]))
            for k in ("net_return", "trading_costs_usd", "closed_positions", "maximum_drawdown")
        ):
            raise ValueError("Non-finite results")
        if digest(result.manifest["plan"]) != result.manifest["plan_digest"]:
            raise ValueError("Changed replay policy")
        if digest(result.manifest["dataset"]) != result.manifest["dataset_digest"]:
            raise ValueError("Changed replay inputs")
    previous_end = None
    for r in pool:
        m = r.manifest
        if (
            digest(m["plan"]) != m["plan_digest"]
            or digest(m["dataset"]) != m["dataset_digest"]
            or m.get("status") != held_out.manifest.get("status")
            or m.get("plan_digest") != held_out.manifest.get("plan_digest")
            or m.get("risk_policy") != held_out.manifest.get("risk_policy")
            or m.get("hard_limits") != held_out.manifest.get("hard_limits")
            or m.get("session_count") != 1
            or m.get("unresolved_inventory") is not False
            or not r.metrics
            or m.get("provenance") != held_out.manifest.get("provenance")
            or m.get("dataset", {}).get("instrument")
            != held_out.manifest.get("dataset", {}).get("instrument")
            or m.get("dataset", {}).get("review", {}).get("assumed_fields")
            != held_out.manifest.get("dataset", {}).get("review", {}).get("assumed_fields")
        ):
            manifest["blockers"] = ["INCOMPATIBLE_POOL_RISK_COST_OR_EVIDENCE"]
            return Comparison(manifest, {}, ())
        start, end = datetime.fromisoformat(m["start"]), datetime.fromisoformat(m["end"])
        known = datetime.fromisoformat(m["available_at"])
        test_start = datetime.fromisoformat(held_out.manifest["start"])
        if not all(aware(t) for t in (start, end, known, test_start)) or not start < end:
            raise ValueError("Invalid result chronology")
        if (
            not end <= as_of < test_start
            or known > as_of
            or previous_end is not None
            and start <= previous_end
        ):
            manifest["blockers"] = ["POOL_OVERLAP_OR_FUTURE_LEAKAGE"]
            return Comparison(manifest, {}, ())
        previous_end = end
    manifest.update(
        status="model_based_stress",
        blockers=[],
        evidence=held_out.manifest["provenance"],
        pool_digests=[r.manifest["dataset_digest"] for r in pool],
        plan_digest=held_out.manifest["plan_digest"],
        plan=held_out.manifest["plan"],
        risk_policy=held_out.manifest["risk_policy"],
        hard_limits=held_out.manifest["hard_limits"],
        held_out_digest=held_out.manifest["dataset_digest"],
        input_digest=digest(
            {
                "pool": [r.metrics for r in pool],
                "seed": seed,
                "test": held_out.manifest["dataset_digest"],
            }
        ),
    )
    rng = random.Random(seed)
    rows = []
    returns = []
    for index in range(10000):
        selected = rng.randrange(len(pool))
        result = pool[selected]
        value = float(result.metrics["net_return"])
        returns.append(value)
        rows.append(
            {
                "trial": index,
                "session_index": selected,
                "net_return": value,
                "costs_usd": result.metrics["trading_costs_usd"],
                "trades": result.metrics["closed_positions"],
                "maximum_drawdown": result.metrics["maximum_drawdown"],
                "rejected": result.metrics["rejected_opportunities"],
                "missed": result.metrics["missed_opportunities"],
            }
        )
    ordered = sorted(returns)
    observed = float(held_out.metrics["net_return"])
    return Comparison(
        manifest,
        {
            "mean_net_return": sum(returns) / 10000,
            "p05": ordered[499],
            "p50": ordered[4999],
            "p95": ordered[9499],
            "loss_frequency": sum(x < 0 for x in returns) / 10000,
            "value_at_risk_95_return": max(0.0, -ordered[499]),
            "expected_shortfall_95_return": max(0.0, -sum(ordered[:500]) / 500),
            "held_out_net_return": observed,
            "fraction_at_or_below_held_out": sum(x <= observed for x in returns) / 10000,
            "mean_costs_usd": float(sum(D(str(r["costs_usd"])) for r in rows) / 10000),
        },
        tuple(rows),
    )
