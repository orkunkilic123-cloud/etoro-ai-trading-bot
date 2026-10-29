"""Daily/weekly diagnostics derived from existing replay journals; local escaped HTML."""

import csv
import hashlib
import html
import io
import json
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

from ..backtest.engine import Result
from ..news.archive import NewsSummary
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


def reason_counts(
    result: Result, events: tuple[dict[str, Any], ...], decisions: tuple[dict[str, Any], ...]
) -> dict[str, int]:
    """Keep observed reasons; multiple reason codes can describe one stage observation."""
    proposals = (
        decisions
        if result.manifest.get("model") == "orb-event-replay-v1"
        else tuple(event for event in events if event["kind"] == "strategy_decision")
    )
    rows = [
        ("proposal", row)
        for row in proposals
        if row.get("status") in ("rejected", "missed", "blocked")
    ]
    rows += [
        (str(row["kind"]), row)
        for row in events
        if (
            row["kind"] in ("signal_rejected", "signal_missed", "entry_rejected", "entry_cancelled")
            or (row["kind"] == "risk_review" and row.get("passed") is False)
        )
    ]
    counts: Counter[str] = Counter()
    for stage, row in rows:
        reasons = row.get("reasons", ())
        reasons = (reasons,) if isinstance(reasons, str) else tuple(reasons)
        if row.get("reason"):
            reasons += (row["reason"],)
        for reason in set(str(reason) for reason in reasons) or {"UNSPECIFIED_REASON"}:
            counts[f"{stage}: {reason}"] += 1
    return dict(sorted(counts.items()))


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
        pnls = [t.get("pnl", t.get("pnl_usd")) for t in trades]
        realized = None if any(v is None for v in pnls) else sum(D(str(v)) for v in pnls)
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
                "reason_counts": reason_counts(result, events, decisions),
                "rejected_or_missed": rejection_total(decision_totals),
                "risk_halts": counts.get("risk_halt", 0),
                "exit_fill_count": len(trades),
                "realized_exit_pnl_usd": None if realized is None else str(realized),
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


EXPORTS = ("summary.json", "daily.md", "weekly.md", "periods.csv")
PERIOD_COLUMNS = (
    "period",
    "valuation_currency",
    "observed_start_at",
    "observed_end_at",
    "coverage_status",
    "net_equity_change",
    "ending_equity",
    "drawdown_fraction",
    "max_observed_exposure",
    "attributed_fees_and_funding_usd",
    "total_cost_usd",
    "realized_exit_pnl_usd",
    "exit_fill_count",
    "rejected_or_missed",
    "risk_halts",
)


def atomic_text(path: Path, content: str) -> None:
    """Publish a complete UTF-8/LF file; close before replacement for Windows."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".shadow-", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(content.encode("utf-8"))
            file.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def display(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def markdown(value: Any) -> str:
    return html.escape(display(value)).replace("|", "&#124;").replace("\n", " ")


def period_markdown(payload: dict[str, Any], cadence: str) -> str:
    lines = [
        f"# {cadence.title()} shadow research report",
        "",
        "**SHADOW / SYNTHETIC — broker execution disabled.**",
        "",
        "Historical fixture periods below are not today's market observations. "
        "Each run is an independent simulated portfolio, not a continuous account.",
        "",
        "Broker identity and unresolved orders: **UNVERIFIED**. No broker connected.",
        "",
        "Net change/equity/exposure use the stated valuation currency. Fees, total costs "
        "and realized exit P&L are USD. Realized exit P&L is after allocated entry and exit "
        "fees, excludes initial FX funding and is not total portfolio P&L. Exit rows may be "
        "partial fills, not closed positions. Missing values are unavailable, never assumed zero.",
        "",
        "| " + " | ".join(PERIOD_COLUMNS) + " |",
        "| " + " | ".join("---" for _ in PERIOD_COLUMNS) + " |",
    ]
    for row in payload[cadence]:
        lines.append("| " + " | ".join(markdown(row.get(k)) for k in PERIOD_COLUMNS) + " |")
    if not payload[cadence]:
        lines += ["", "No equity observations; performance unavailable."]
    lines += [
        "",
        "Period coverage is partial/unverified; observed marks do not establish continuous "
        "coverage. Multi-period spread/slippage attribution is unavailable. Rejections/misses "
        "count stage observations, not unique economic opportunities.",
        "",
        "## Journal stage observations",
        "",
    ]
    for row in payload[cadence]:
        lines.append(f"- {markdown(row['period'])}: {markdown(encode(row['decision_counts']))}")
        lines.append("  Observed reasons: " + markdown(encode(row.get("reason_counts", {}))))
    lines += ["", "## Proposed experiments — review required", ""]
    for proposal in payload["improvement_proposals"]:
        lines.append(
            f"- Priority {markdown(proposal['priority'])}: {markdown(proposal['observation'])}. "
            f"Hypothesis: {markdown(proposal['hypothesis'])}. "
            f"Validation: {markdown(proposal['validation'])}."
        )
    lines += ["", "These proposals never change strategies, risk limits or authorization.", ""]
    for limitation in payload["limitations"]:
        lines.append("- " + markdown(limitation))
    return "\n".join(lines) + "\n"


def periods_csv(payload: dict[str, Any]) -> str:
    stream = io.StringIO(newline="")
    keys = ("cadence", *PERIOD_COLUMNS, "decision_counts", "reason_counts")
    writer = csv.DictWriter(stream, fieldnames=keys, lineterminator="\n")
    writer.writeheader()
    for cadence in ("daily", "weekly"):
        for row in payload[cadence]:
            cells = {key: display(row.get(key)) for key in PERIOD_COLUMNS}
            cells.update(cadence=cadence, decision_counts=encode(row["decision_counts"]))
            cells["reason_counts"] = encode(row.get("reason_counts", {}))
            # Keep signed numeric values numeric; prevent spreadsheet formulas in text columns.
            for key, value in cells.items():
                if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                    try:
                        numeric = D(value).is_finite()
                    except ArithmeticError:
                        numeric = False
                    if not numeric:
                        cells[key] = "'" + value
            writer.writerow(cells)
    return stream.getvalue()


def write_summary(result: Result, path: Path) -> None:
    payload = {
        "schema_version": 1,
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
    contents = {
        "summary.json": encode(payload) + "\n",
        "daily.md": period_markdown(payload, "daily"),
        "weekly.md": period_markdown(payload, "weekly"),
        "periods.csv": periods_csv(payload),
    }
    for name, content in contents.items():
        atomic_text(path.parent / name, content)
    checksums = {
        name: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for name, content in contents.items()
    }
    # Written last; a completed run must have a whole verified report bundle.
    atomic_text(path.parent / "shadow-checksums.json", encode(checksums) + "\n")


def bounded_bytes(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("Report symlink blocked")
    with path.open("rb") as file:
        raw = file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Report too large")
    return raw


def load_summary(directory: Path) -> tuple[dict[str, Any], str]:
    if directory.is_symlink():
        raise ValueError("Report directory symlink blocked")
    raw = bounded_bytes(directory / "summary.json")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or (
        payload.get("mode") != "SHADOW"
        or payload.get("evidence") != "SYNTHETIC"
        or payload.get("execution_enabled") is not False
        or not isinstance(payload.get("metrics"), dict)
        or not isinstance(payload.get("improvement_proposals"), list)
    ):
        raise ValueError("Invalid report schema")
    for cadence in ("daily", "weekly"):
        rows = payload.get(cadence)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or row.get("valuation_currency") not in ("USD", "EUR")
            or row.get("coverage_status") not in ("partial", "unverified")
            for row in rows
        ):
            raise ValueError("Invalid period schema")
    if "schema_version" not in payload:
        return payload, "LEGACY — export integrity unverified"
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported report schema")
    checksums = json.loads(bounded_bytes(directory / "shadow-checksums.json"))
    if not isinstance(checksums, dict) or set(checksums) != set(EXPORTS):
        raise ValueError("Invalid report checksum manifest")
    for name in EXPORTS:
        content = raw if name == "summary.json" else bounded_bytes(directory / name)
        if hashlib.sha256(content).hexdigest() != checksums[name]:
            raise ValueError("Report checksum mismatch")
    return payload, "Local export checksums verified — not broker verification"


def period_html(payload: dict[str, Any], cadence: str) -> str:
    columns = (
        "period",
        "valuation_currency",
        "net_equity_change",
        "ending_equity",
        "drawdown_fraction",
        "max_observed_exposure",
        "attributed_fees_and_funding_usd",
        "rejected_or_missed",
        "coverage_status",
    )
    heads = "".join(f"<th>{html.escape(key.replace('_', ' '))}</th>" for key in columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(display(row.get(k)))}</td>" for k in columns) + "</tr>"
        for row in payload[cadence]
    )
    bounds = "".join(
        f"<li>{html.escape(display(row.get('period')))}: "
        f"{html.escape(display(row.get('observed_start_at')))} to "
        f"{html.escape(display(row.get('observed_end_at')))}</li>"
        for row in payload[cadence]
    )
    reasons = "".join(
        f"<li>{html.escape(display(row.get('period')))}: "
        f"{html.escape(encode(row.get('reason_counts', {})))}</li>"
        for row in payload[cadence]
    )
    return (
        f"<h3>{cadence.title()} replay periods</h3><div class='scroll'><table><tr>{heads}</tr>"
        f"{rows}</table></div><p>Observed equity marks (UTC):</p><ul>{bounds}</ul>"
        "<p>Observed rejection/miss reasons (multiple codes may describe one stage):</p>"
        f"<ul>{reasons}</ul>"
    )


def news_html(news: NewsSummary | None) -> str:
    heading = "<h2>Saved news archive — informational only</h2>"
    if news is None:
        return (
            heading + "<p>UNAVAILABLE — no verified local summary supplied. No live news feed.</p>"
        )
    observed = news.observed_through.isoformat() if news.observed_through else "unknown"
    details = (
        f"Status: {news.status}; as of {news.as_of.isoformat()}; observed through {observed}; "
        f"{news.total_events} archive events; displayed list truncated: {news.truncated}."
    )
    rows = "".join(
        "<tr>"
        + "".join(
            "<td>" + html.escape(display(value)) + "</td>"
            for value in (
                item.title,
                item.form,
                item.published_at.isoformat() if item.published_at else None,
                item.updated_at.isoformat(),
                item.observed_at.isoformat(),
                item.source_feed,
                item.source_url,
                item.revision_sha256,
                ", ".join(item.keyword_tags),
            )
        )
        + "</tr>"
        for item in news.items
    )
    return (
        heading + "<p>" + html.escape(details) + "</p>"
        "<p>Source authenticity UNVERIFIED; earnings coverage UNKNOWN. Saved public filing facts "
        "and keyword tags are not sentiment or predictions. This current archive view never enters "
        "historical strategy decisions and never grants execution authority. "
        "No remote/live feed.</p>"
        "<div class='scroll'><table><tr><th>Title</th><th>Form</th><th>Published</th>"
        "<th>Updated</th><th>Observed</th><th>Source feed</th><th>Source URL (text only)</th>"
        "<th>Revision SHA-256</th><th>Keyword tags</th></tr>" + rows + "</table></div>"
    )


def dashboard(store: Runs, *, now: datetime, news: NewsSummary | None = None) -> None:
    if now.tzinfo is None:
        raise ValueError("Aware dashboard time required")
    today = now.astimezone(UTC).date().isoformat()
    records = store.rows()
    counts = Counter(row[-1] for row in records)
    rows, reports = [], []
    unavailable = 0
    for identity, pipeline, eur, slot, status in records:
        freshness = "STALE RUN" if slot != today else "TODAY'S RUN — synthetic data"
        values = (pipeline, str(eur), slot, status, freshness)
        cells = "".join("<td>" + html.escape(v) + "</td>" for v in values)
        details = {
            "running": "Active or interrupted — inspect locally; never automatically retried",
            "failed": "Failed — preserved state requires review; no automatic retry",
            "blocked": "Blocked by existing research gates; no performance approval",
            "missed": "Missed UTC slot — no backfill or catch-up trades",
        }.get(status, "Unknown run state — review required")
        links = "No completed report"
        if status == "completed" and re.fullmatch("[0-9a-f]{24}", identity):
            try:
                payload, integrity = load_summary(store.root / identity)
                details = integrity
                names = EXPORTS if payload.get("schema_version") == 1 else ()
                links = " · ".join(f'<a href="{identity}/{name}">{name}</a>' for name in names)
                if not links:
                    links = "Legacy inline view only — export integrity unverified"
                metrics = "".join(
                    f"<li>{html.escape(key)}: {html.escape(display(value))}</li>"
                    for key, value in payload["metrics"].items()
                )
                proposals = "".join(
                    "<li>"
                    + html.escape("; ".join(f"{k}: {v}" for k, v in proposal.items()))
                    + "</li>"
                    for proposal in payload["improvement_proposals"]
                    if isinstance(proposal, dict)
                )
                reports.append(
                    f"<details><summary>{html.escape(pipeline)} · EUR {html.escape(str(eur))} · "
                    f"run {html.escape(slot)} · SYNTHETIC</summary>"
                    f"<p>{html.escape(integrity)}</p><p>{links}</p><h3>Full-run metrics</h3>"
                    f"<ul>{metrics}</ul>{period_html(payload, 'daily')}"
                    f"{period_html(payload, 'weekly')}"
                    "<h3>Proposed experiments — review required</h3>"
                    f"<ul>{proposals}</ul></details>"
                )
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                unavailable += 1
                details = "REPORT UNAVAILABLE — missing, corrupt or incomplete; review required"
        elif status == "completed":
            unavailable += 1
            details = "REPORT UNAVAILABLE — invalid run identity; review required"
        rows.append(f"<tr>{cells}<td>{html.escape(details)}</td><td>{links}</td></tr>")
    cards = "".join(
        f"<section class='card'><strong>{value}</strong><span>{html.escape(label)}</span></section>"
        for label, value in (
            ("Completed replay runs", counts["completed"]),
            ("Active or interrupted", counts["running"]),
            ("Failed / blocked", counts["failed"] + counts["blocked"]),
            ("Recorded missed slots", counts["missed"]),
            ("Reports unavailable", unavailable),
        )
    )
    content = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>Shadow research dashboard</title><style>"
        "body{font:16px system-ui;background:#101827;color:#edf2f9;margin:0}"
        "main{max-width:1200px;margin:auto;padding:2rem}a{color:#8ec9ff}"
        ".notice,details,.card{border:1px solid #415169;border-radius:8px;padding:1rem;"
        "background:#1b283c}.notice{border-left:5px solid #ffcf75}"
        ".cards{display:flex;flex-wrap:wrap;gap:1rem;margin:1rem 0}.card{flex:1;min-width:130px}"
        ".card strong{display:block;font-size:2rem}.card span{color:#c8d4e6}"
        "td,th{padding:.6rem;border-bottom:1px solid #415169;text-align:left;vertical-align:top}"
        "table{border-collapse:collapse;width:100%}.scroll{overflow:auto}"
        "details{margin:1rem 0}summary{cursor:pointer;font-weight:bold}li{margin:.5rem 0}"
        "</style></head><body><main><h1>SHADOW / SYNTHETIC — broker execution disabled</h1>"
        "<div class='notice'><p>Broker identity and unresolved orders: UNVERIFIED. "
        "No broker connected. Live news and earnings coverage: UNVERIFIED.</p>"
        "<p>Fixture timestamps are historical software inputs, never fresh market quotes. "
        "Independent research runs are not a continuous account or evidence of profitability.</p>"
        "<p>Running rows may be active or interrupted after a restart; inspect locally. "
        "No run is automatically retried. No task runs while the PC is off.</p></div>"
        f"<p>View generated UTC: {html.escape(now.astimezone(UTC).isoformat())}. "
        "Static snapshot; refresh only after a local command generates a new view.</p>"
        f"<div class='cards'>{cards}</div><h2>Run monitoring</h2><div class='scroll'>"
        "<table><tr><th>Pipeline</th><th>EUR budget</th><th>UTC run slot</th><th>Status</th>"
        "<th>Freshness</th><th>Monitoring</th><th>Reports</th></tr>"
        + "".join(rows)
        + "</table></div>"
        + (
            "<p>No runs recorded. No prior schedule or market activity is assumed.</p>"
            if not rows
            else ""
        )
        + "<h2>Research reports</h2><p>Daily/weekly periods use replay timestamps. "
        "Equity/exposure use the displayed USD or EUR valuation; fees/costs are USD. "
        "Coverage is partial/unverified. Missing costs remain unavailable. "
        "Stage rejection counts are not unique opportunities. Proposals never change rules.</p>"
        + "".join(reports)
        + news_html(news)
        + "</main></body></html>\n"
    )
    atomic_text(store.root / "dashboard.html", content)
