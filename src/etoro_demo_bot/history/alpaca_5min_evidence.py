"""Conservative offline five-minute evidence report; never an execution permit."""

import json
from datetime import date, datetime
from pathlib import Path

from .archive import Archive
from .calendar import NYSE2026
from .intraday import qualify_download, research_report

MANDATORY = (
    "original_publication_and_revisions",
    "licensed_use_and_retention",
    "corporate_actions_and_splits",
    "historical_bid_ask_and_liquidity",
    "historical_costs_and_slippage",
    "point_in_time_usd_eur_fx",
    "etoro_instrument_eligibility",
    "point_in_time_earnings",
)


def evidence_report(
    archive: Archive,
    manifest: str,
    symbol: str,
    *,
    start: str,
    end: str,
    audit_at: datetime,
    calendar_verified_at: datetime,
) -> dict[str, object]:
    """Structural success is only conditional; never claim real replay eligibility."""
    issues: list[str] = []
    structural: dict[str, object] | None = None
    try:
        series = qualify_download(
            archive,
            manifest,
            symbol,
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
            audit_at=audit_at,
            calendar=NYSE2026(verified_at=calendar_verified_at),
        )
        structural = research_report(series)
    except (ValueError, OSError):
        issues.append("STRUCTURAL_COVERAGE_OR_PROVENANCE_UNQUALIFIED")
    issues.extend("MISSING_" + field.upper() for field in MANDATORY)
    return {
        "schema": "alpaca-iex-5min-evidence-v1",
        "status": "blocked",
        "symbol": symbol,
        "manifest": manifest,
        "structural": structural,
        "blockers": issues,
        "original_first_known_at": None,
        "original_revision_times": None,
        "historical_replay_eligible": False,
        "execution_authorized": False,
        "returns": None,
        "eur_500": None,
        "eur_1000": None,
    }


def write_evidence_report(path: Path, report: dict[str, object]) -> None:
    """Never overwrite a prior evidence report, even on another OS."""
    payload = (
        json.dumps(report, sort_keys=True, default=str, ensure_ascii=True, indent=2) + "\n"
    ).encode("utf-8")
    with path.open("xb") as f:
        f.write(payload)
