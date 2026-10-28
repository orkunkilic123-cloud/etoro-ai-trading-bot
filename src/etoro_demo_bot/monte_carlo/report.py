"""Deterministic research reports; exclusive directory creation, no telemetry."""

import csv
import hashlib
from dataclasses import asdict
from pathlib import Path

from ..strategy.journal import encode
from .engine import Result


def write_report(result: Result, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    payload = asdict(result)
    payload["execution_authorized"] = False
    (destination / "report.json").write_text(encode(payload) + "\n", encoding="utf-8", newline="\n")
    with (destination / "trials.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(
            (
                "trial",
                "block",
                "outcome",
                "exit_step",
                "exit_price_usd",
                "pnl_usd",
                "costs_usd",
                "portfolio_pnl_eur",
            )
        )
        for t in result.trials:
            writer.writerow(
                (
                    t.index,
                    t.sampled_block,
                    t.outcome,
                    t.exit_step,
                    t.exit_price,
                    t.pnl_usd,
                    t.costs_usd,
                    t.portfolio_pnl_eur,
                )
            )
    text = (
        "# Monte Carlo: SYNTHETIC research only\n\n"
        "Not historical evidence or a probability of future profit. Execution disabled.\n\n"
        f"Status: {result.status}; trials: {len(result.trials)}\n\n"
        f"Input digest: {result.inputs_digest}\n\n"
        f"Reasons: {', '.join(result.reasons)}\n\n"
        "## Conditional metrics\n\n"
        + "\n".join(f"- {key}: {encode(value)}" for key, value in result.metrics.items())
        + "\n\n## Limitations\n\n"
        + "\n".join(f"- {line}" for line in result.manifest["limitations"])
        + "\n"
    )
    (destination / "report.md").write_text(text, encoding="utf-8", newline="\n")
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())
    }
    (destination / "checksums.json").write_text(
        encode(hashes) + "\n", encoding="utf-8", newline="\n"
    )
