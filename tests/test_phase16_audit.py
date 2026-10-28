"""Phase 16 offline-only evidence audit regression tests."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.history.phase16_audit import audit_symbols, write_bundle

NOW = datetime(2026, 10, 28, 16, tzinfo=UTC)


def test_missing_cache_manifest_blocks_real_performance(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "private.sqlite")
    report = audit_symbols(
        archive,
        {"SPY": "0" * 64, "IBM": "1" * 64},
        start=date(2026, 3, 9),
        end=date(2026, 3, 9),
        audit_at=NOW,
        calendar_verified_at=NOW,
    )
    assert report["genuine_replay_eligible"] is False
    assert report["eur_500_returns"] is None
    assert report["monte_carlo_returns"] is None
    rows = report["datasets"]
    assert isinstance(rows, list)
    assert [row["symbol"] for row in rows] == ["IBM", "SPY"]
    for row in rows:
        assert row["status"] == "blocked"
        assert row["structural_coverage"] == "blocked"
        assert row["expected_regular_bars"] == 78
        assert row["qualified_regular_bars"] == 0
        assert row["original_first_known_at"] is None
        assert "MISSING_HISTORICAL_POINT_IN_TIME_FX" in row["blockers"]


def test_report_output_exclusive_deterministic_utf8(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "archive.sqlite")
    report = audit_symbols(
        archive,
        {"IBM": "a" * 64},
        start=date(2026, 11, 27),
        end=date(2026, 11, 27),
        audit_at=NOW.replace(month=12),
        calendar_verified_at=NOW,
    )
    output = tmp_path / "report"
    first = write_bundle(output, report)
    assert len(first) == 3
    assert b"42" in (output / "evidence.csv").read_bytes()
    assert (output / "evidence.md").read_bytes().endswith(b"\n")
    assert json.loads((output / "evidence.json").read_text("utf-8"))["execution_authorized"] is False
    with pytest.raises(FileExistsError):
        write_bundle(output, report)
    second = write_bundle(tmp_path / "another", report)
    assert first == second


@pytest.mark.parametrize("bad", [{}, {"IBM": "bad"}, {"IBM": "0" * 64, "SPY": ""}])
def test_invalid_inputs_fail_closed(tmp_path: Path, bad: dict[str, str]) -> None:
    archive = Archive(tmp_path / "archive.sqlite")
    with pytest.raises(ValueError):
        audit_symbols(
            archive,
            bad,
            start=date(2026, 3, 9),
            end=date(2026, 3, 9),
            audit_at=NOW,
            calendar_verified_at=NOW,
        )
