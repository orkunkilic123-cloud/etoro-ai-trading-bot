"""Daily/weekly diagnostics derived from existing replay journals; local escaped HTML."""

import html
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

from ..backtest.engine import Result
from ..strategy.journal import encode
from .store import Runs


def decision_counts(
    result: Result,
    events: tuple[dict[str, Any], ...],
    decisions: tuple[dict[str, Any], ...],
) -> dict[str, int]:
    """Count stage observations once, not unique economic opportunities.

    Hourly journal decisions duplicate strategy_decision events; use only events.
    ORB proposal decisions live in Result.decisions, with later risk/fill failures in events.
    """
    counts: Counter[str] = Counter()
    proposals = (
        decisions
        if result.manifest.get("model") == "orb-event-replay-v1"
        else tuple(event for event in events if event["kind"] == "strategy_decision")
    )
    for proposal in proposals:
        status = proposal.get("status")
        if status in ("blocked", "rejected"):
            counts["proposal_rejected"] += 1
        elif status == "missed":
            counts["proposal_missed"] += 1
        elif status not in ("proposed", "waiting"):
            counts["unknown_decision_status"] += 1
    for event in events:
        kind = event["kind"]
        if kind in ("signal_rejected", "signal_missed", "entry_rejected"):
            counts[str(kind)] += 1
        elif kind == "risk_review" and event.get("passed") is False:
            counts["risk_rejected"] += 1
        elif kind == "entry_cancelled":
            reason = event.get("reason")
            if reason in ("FILL_REVALIDATION", "FILL_RISK_OR_CAPACITY"):
                counts["fill_rejected"] += 1
            elif reason in (
                "EXPIRY_OR_RISK_HALT",
                "END_OF_DATA",
                "SIGNAL_EXPIRED",
                "END_OF_REPLAY",
            ):
                counts["entry_missed"] += 1
            else:
                counts["unknown_cancelled_entries"] += 1
    return dict(sorted(counts.items()))


def rejection_total(counts: dict[str, int]) -> int:
    return sum(value for key, value in counts.items() if key.endswith(("rejected", "missed")))


def periods(result: Result, *, weekly: bool) -> list[dict[str, Any]]:
    """Partition actual replay times, not the scheduler's current date."""

    def key(stamp: str) -> str:
        at = datetime.fromisoformat(stamp).astimezone(UTC)
        year, week, _ = at.isocalendar()
        return f"{year}-W{week:02d}" if weekly else at.date().isoformat()

    groups: dict[str, list[dict[str, Any]]] = {}
    for point in result.equity:
        groups.setdefault(key(point["at"]), []).append(point)
    if not groups:
        return []
    currency = result.manifest.get("shadow_valuation_currency")
    if currency not in ("USD", "EUR"):
        raise ValueError("Explicit replay valuation currency required")
    previous = D(result.equity[0]["equity"])
    output = []
    for label, points in groups.items():
        events = tuple(e for e in result.events if key(e["at"]) == label)
        decisions = tuple(d for d in result.decisions if key(d["at"]) == label)
        decision_totals = decision_counts(result, events, decisions)
        first_at = datetime.fromisoformat(points[0]["at"]).astimezone(UTC)
        last_at = datetime.fromisoformat(points[-1]["at"]).astimezone(UTC)
        period_start = first_at.replace(hour=0, minute=0, second=0, microsecond=0)
        if weekly:
            period_start -= timedelta(days=period_start.weekday())
        period_end = period_start + timedelta(days=7 if weekly else 1)
        peak, drawdown = previous, D(0)
        for p in points:
            value = D(p["equity"])
            peak = max(peak, value)
            if peak > 0:
                drawdown = max(drawdown, 1 - value / peak)
        final = D(points[-1]["equity"])
        counts = Counter(str(e["kind"]) for e in events)
        trades = [t for t in result.trades if key(t["at"]) == label]
        # Entry/funding events plus exit trade rows, never both trade and duplicate exit event.
        charges = [
            e.get("fx_cost") if e["kind"] == "funding" else e.get("commission", e.get("fee_usd"))
            for e in events
            if e["kind"] in ("funding", "entry_fill")
        ]
        charges += [t.get("commission", t.get("fee_usd")) for t in trades]
        fees = None if any(v is None for v in charges) else sum(D(str(v)) for v in charges)
        output.append(
            {
                "period": label,
                "period_start_at": period_start.isoformat(),
                "period_end_at_exclusive": period_end.isoformat(),
                "observed_start_at": first_at.isoformat(),
                "observed_end_at": last_at.isoformat(),
                "coverage_status": "partial"
                if first_at > period_start or last_at < period_end
                else "unverified",
                "coverage_limitation": "Observed marks do not prove continuous period coverage",
                "valuation_currency": currency,
                "net_equity_change": str(final - previous),
                "ending_equity": str(final),
                "drawdown_fraction": str(drawdown),
                "max_observed_exposure": str(max(D(p["exposure"]) for p in points)),
                "attributed_fees_and_funding_usd": None if fees is None else str(fees),
                "total_cost_usd": result.metrics.get("trading_costs_usd")
                if len(groups) == 1
                else None,
                "cost_limitation": "Period spread/slippage allocation unavailable",
                "event_counts": dict(sorted(counts.items())),
                "decision_counts": decision_totals,
                "rejected_or_missed": rejection_total(decision_totals),
                "risk_halts": counts.get("risk_halt", 0),
            }
        )
        previous = final
    return output


def recommendations(result: Result) -> list[dict[str, str]]:
    counts = decision_counts(result, result.events, result.decisions)
    proposals = [
        {
            "priority": "1",
            "observation": "All inputs are synthetic engineering fixtures",
            "hypothesis": "Qualified point-in-time input may materially change outcomes",
            "validation": "Qualify licensed data then compare frozen rules on held-out sessions",
        }
    ]
    if rejection_total(counts):
        proposals.append(
            {
                "priority": "2",
                "observation": (
                    f"Journal contains {rejection_total(counts)} rejected/missed stage observations"
                ),
                "hypothesis": "Evidence timing or coverage is limiting eligible observations",
                "validation": "Test data adapters by reason code; preserve gates",
            }
        )
    if result.metrics.get("trading_costs_usd", 0):
        proposals.append(
            {
                "priority": "3",
                "observation": "Simulation charges explicit trading costs",
                "hypothesis": "Net results are sensitive to execution friction",
                "validation": "Run predeclared cost/delay sensitivity cases on held-out inputs",
            }
        )
    return proposals


def write_summary(result: Result, path: Path) -> None:
    payload = {
        "mode": "SHADOW",
        "evidence": "SYNTHETIC",
        "execution_enabled": False,
        "broker_unresolved_orders": "UNVERIFIED — no broker connected",
        "metrics": result.metrics,
        "daily": periods(result, weekly=False),
        "weekly": periods(result, weekly=True),
        "improvement_proposals": recommendations(result),
        "limitations": result.manifest.get("limitations", []),
    }
    path.write_text(encode(payload) + "\n", encoding="utf-8", newline="\n")


def dashboard(store: Runs, *, now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("Aware dashboard time required")
    today = now.astimezone(UTC).date().isoformat()
    rows = []
    for identity, pipeline, eur, slot, status in store.rows():
        freshness = "STALE RUN" if slot != today else "TODAY'S RUN — synthetic data"
        values = (pipeline, str(eur), slot, status, freshness)
        cells = "".join("<td>" + html.escape(v) + "</td>" for v in values)
        link = (
            f'<a href="{identity}/summary.json">Daily/weekly report</a>'
            if status == "completed" and re.fullmatch("[0-9a-f]{24}", identity)
            else "No completed report"
        )
        metrics = "No completed metrics"
        if status == "completed" and re.fullmatch("[0-9a-f]{24}", identity):
            try:
                raw = (store.root / identity / "summary.json").read_bytes()
                if len(raw) > 1024 * 1024:
                    raise ValueError("Report too large")
                summary = json.loads(raw)
                metrics = "; ".join(
                    f"{name}: {summary['metrics'].get(name, 'unavailable')}"
                    for name in (
                        "total_return",
                        "maximum_drawdown",
                        "trading_costs_usd",
                        "closed_positions",
                        "time_weighted_exposure",
                    )
                )
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                metrics = "REPORT UNAVAILABLE — review required"
        rows.append(f"<tr>{cells}<td>{link}</td><td>{html.escape(metrics)}</td></tr>")
    content = (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>Shadow research dashboard</title><style>body{font:16px system-ui;margin:2em}"
        "td,th{padding:.6em;border:1px solid #aaa}table{border-collapse:collapse}</style>"
        "<h1>SHADOW / SYNTHETIC — broker execution disabled</h1>"
        "<p>Broker identity and unresolved orders: UNVERIFIED. No broker connected.</p>"
        "<p>Live news and earnings coverage: UNVERIFIED. Fixture timestamps are "
        "historical software inputs, never fresh market quotes. "
        "Running rows after a restart require review; they are never retried automatically.</p>"
        "<p>This static dashboard is refreshed only when a local command runs. "
        "No task runs while the PC is off.</p><table><tr><th>Pipeline</th><th>EUR</th>"
        "<th>UTC run slot</th><th>Status</th><th>Freshness</th><th>Report</th>"
        "<th>Synthetic metrics</th></tr>" + "".join(rows) + "</table></html>\n"
    )
    # Replace only the generated view; reports and run claims are immutable.
    (store.root / "dashboard.html").write_text(content, encoding="utf-8", newline="\n")
