"""Stable, local JSON/CSV/Markdown reports. No automatic publishing or telemetry."""

import csv
import hashlib
from pathlib import Path
from typing import Any

from ..strategy.journal import encode
from .engine import Result


def _csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    keys = sorted({key for row in rows for key in row})
    with path.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            # Prevent CSV spreadsheet formula injection in external provenance/reason text.
            values = {
                key: encode(value) if isinstance(value, dict | list | tuple) else str(value)
                for key, value in row.items()
            }
            writer.writerow(
                {k: "'" + v if v.startswith(("=", "+", "@")) else v for k, v in values.items()}
            )


def write_report(result: Result, new_directory: Path) -> None:
    new_directory.mkdir(parents=True, exist_ok=False)
    payload = {
        "manifest": result.manifest,
        "metrics": result.metrics,
        "benchmarks": result.benchmarks,
        "events": result.events,
        "equity": result.equity,
        "trades": result.trades,
        "decisions": result.decisions,
    }
    (new_directory / "report.json").write_text(encode(payload) + "\n", encoding="utf-8")
    for name, rows in (
        ("events", result.events),
        ("equity", result.equity),
        ("trades", result.trades),
        ("decisions", result.decisions),
    ):
        _csv(new_directory / f"{name}.csv", rows)
    label = result.manifest["provenance"]["kind"]
    lines = [
        "# Independent backtest report",
        "",
        f"Evidence classification: **{label}**.",
        "Synthetic fixtures are software tests, never evidence of "
        "profitability. No live or Demo orders were placed.",
        "",
        f"Dataset digest: `{result.manifest['dataset_digest']}`",
        f"Plan digest: `{result.manifest['plan_digest']}`",
        "",
        "| Metric | Strategy | Buy and hold | USD cash |",
        "| --- | --- | --- | --- |",
    ]
    for key, value in result.metrics.items():

        def cell(item: Any) -> str:
            return "undefined / insufficient observations" if item is None else str(item)

        lines.append(
            f"| {key} | {cell(value)} | "
            f"{cell(result.benchmarks['buy_and_hold']['metrics'][key])} | "
            f"{cell(result.benchmarks['cash_usd']['metrics'][key])} |"
        )
    lines += ["", "## Limitations", ""] + ["- " + x for x in result.manifest["limitations"]]
    lines += [
        "",
        "Open inventory is marked at the final bid. Ratios based on closed "
        "positions exclude unrealized P&L.",
        "Annualization requires at least a year; Sharpe requires at least 30 "
        "consecutive daily returns, zero risk-free rate.",
        "",
    ]
    (new_directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(new_directory.iterdir())
    }
    (new_directory / "checksums.json").write_text(encode(hashes) + "\n", encoding="utf-8")


def comparison(results: dict[str, Result], path: Path) -> None:
    lines = [
        "# Strategy comparison",
        "",
        "Not evidence of profitability; consult each run provenance and limitations.",
        "",
        "| Strategy | Evidence | Total return | Max drawdown | Closed positions |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, result in sorted(results.items()):
        safe = name.replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {safe} | {result.manifest['provenance']['kind']} | "
            f"{result.metrics['total_return']} | {result.metrics['maximum_drawdown']} | "
            f"{result.metrics['closed_positions']} |"
        )
    rows = tuple(
        {"strategy": name, "evidence": result.manifest["provenance"]["kind"], **result.metrics}
        for name, result in sorted(results.items())
    )
    _csv(path.with_suffix(".csv"), rows)
    with path.with_suffix(".json").open("x", encoding="utf-8") as output:
        output.write(encode(rows) + "\n")
    with path.open("x", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
