"""Deterministic JSON, CSV and Markdown including blocked evidence, never fabricated metrics."""

import csv
import hashlib
from pathlib import Path
from typing import Any

from ...strategy.journal import encode
from ..engine import Result
from .serialization import normalized


def write_bundle(payload: dict[str, Any], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    content = normalized(payload)
    (directory / "report.json").write_bytes((encode(content) + "\n").encode())
    for name in ("metrics", "events", "equity", "trades", "decisions", "scenarios"):
        rows = (
            [{"metric": k, "value": v} for k, v in content.get("metrics", {}).items()]
            if name == "metrics"
            else content.get(name, [])
        )
        keys = sorted({k for row in rows for k in row})
        with (directory / f"{name}.csv").open("x", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=keys, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                cells = {
                    k: encode(v) if isinstance(v, dict | list) else str(v) for k, v in row.items()
                }
                writer.writerow(
                    {
                        k: "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v
                        for k, v in cells.items()
                    }
                )
    manifest = content["manifest"]
    lines = [
        "# Intraday research report",
        "",
        f"Status: **{manifest['status']}**.",
        "Synthetic fixtures and model-based simulations do not establish profitability.",
        "No execution authority, credentials or orders.",
        "",
        "## Metrics",
        "",
    ]
    for k, v in content.get("metrics", {}).items():
        lines.append(f"- {k}: {v}")
    if manifest["status"] == "blocked":
        lines.append("Performance metrics withheld: critical evidence or structure is missing.")
    lines += ["", "## Evidence and limitations", ""]
    for text in (*manifest.get("blockers", []), *manifest.get("limitations", [])):
        lines.append("- " + str(text).replace("\n", " "))
    lines += [
        "",
        "Full provenance, assumptions, risk/cost policy, digests and comparisons "
        "are in report.json.",
        "",
    ]
    (directory / "report.md").write_bytes("\n".join(lines).encode())
    checksums = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir())
    }
    (directory / "checksums.json").write_bytes((encode(checksums) + "\n").encode())


def write_report(result: Result, directory: Path) -> None:
    write_bundle(
        {
            "manifest": result.manifest,
            "metrics": result.metrics,
            "events": result.events,
            "equity": result.equity,
            "trades": result.trades,
            "decisions": result.decisions,
            "benchmarks": result.benchmarks,
        },
        directory,
    )
