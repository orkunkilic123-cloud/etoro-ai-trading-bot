"""Synthetic hourly engineering fixtures only; no historical profitability evidence."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.history.calendar import NYSE2026
from etoro_demo_bot.history.hourly import (
    CoveragePolicy,
    StudyWindow,
    audit_hourly,
    cached_hourly,
    readiness_manifest,
    run_hourly_study,
)
from etoro_demo_bot.history.models import Bar, History, Source

NOW = datetime(2026, 10, 27, 22, tzinfo=UTC)
CAL = NYSE2026(verified_at=NOW)
POLICY = CoveragePolicy()
WINDOW = StudyWindow(
    date(2026, 1, 2),
    date(2026, 7, 31),
    datetime(2026, 1, 12, tzinfo=UTC),
    datetime(2026, 5, 1, tzinfo=UTC),
    datetime(2026, 6, 15, tzinfo=UTC),
    datetime(2026, 7, 31, 21, tzinfo=UTC),
)


def source(raw: bytes = b"") -> Source:
    return Source(
        "invented-hourly",
        "synthetic://hourly",
        "synthetic://license",
        NOW,
        hashlib.sha256(raw).hexdigest(),
        "synthetic",
        "Invented fixture.",
        symbol="TEST",
    )


def history() -> History:
    bars = []
    for session in CAL.sessions(WINDOW.start, WINDOW.end):
        point = session.opens
        while point + timedelta(hours=1) <= session.closes:
            end = point + timedelta(hours=1)
            bars.append(Bar(point, end, D(100), D(101), D(99), D(100), D(1000), end, "raw"))
            point = end
    return History("TEST", "XNYS", "USD", "1h", "raw", tuple(bars), source())


def test_six_month_coverage_does_not_promote_synthetic_evidence() -> None:
    result = audit_hourly(history(), CAL, WINDOW, POLICY, audit_at=NOW)
    assert result.coverage_ok
    assert result.expected_bars == result.observed_bars
    assert result.complete_sessions >= 120
    assert result.omitted_partial_minutes == result.complete_sessions * 30
    assert min(result.warmup_counts) >= 35
    assert {"SYNTHETIC_SOURCE", "ORIGINAL_AVAILABILITY_UNVERIFIED"} <= set(result.replay_blockers)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "partial",
        "off_grid",
        "daily",
        "adjusted",
        "late_availability",
        "short",
        "future_retrieval",
    ],
)
def test_unusable_history_rejected(mutation: str) -> None:
    data = history()
    if mutation == "missing":
        data = replace(data, bars=data.bars[1:])
    elif mutation == "duplicate":
        data = replace(data, bars=data.bars + data.bars[-1:])
    elif mutation == "partial":
        data = replace(
            data,
            bars=(replace(data.bars[0], end=data.bars[0].start + timedelta(minutes=30)),)
            + data.bars[1:],
        )
    elif mutation == "off_grid":
        extra = replace(
            data.bars[0],
            start=data.bars[0].start + timedelta(minutes=5),
            end=data.bars[0].end + timedelta(minutes=5),
        )
        data = replace(data, bars=(extra,) + data.bars[1:])
    elif mutation == "daily":
        data = replace(data, resolution="1d")
    elif mutation == "adjusted":
        data = replace(data, basis="split_adjusted")
    elif mutation == "late_availability":
        data = replace(data, bars=tuple(replace(b, known_at=NOW) for b in data.bars))
    elif mutation == "short":
        data = replace(data, bars=data.bars[:50])
    elif mutation == "future_retrieval":
        data = replace(data, source=replace(data.source, retrieved_at=NOW + timedelta(days=1)))
    result = audit_hourly(data, CAL, WINDOW, POLICY, audit_at=NOW)
    assert not result.coverage_ok


def test_complete_grid_plus_extra_offset_bar_is_rejected() -> None:
    data = history()
    first = data.bars[0]
    extra = replace(
        first,
        start=first.start + timedelta(minutes=15),
        end=first.end + timedelta(minutes=15),
        known_at=first.end + timedelta(minutes=15),
    )
    data = replace(data, bars=tuple(sorted((*data.bars, extra), key=lambda b: b.start)))
    assert (
        "OFF_GRID_OR_PARTIAL_CANDLE"
        in audit_hourly(data, CAL, WINDOW, POLICY, audit_at=NOW).coverage_errors
    )


def test_coverage_thresholds_and_chronological_boundaries() -> None:
    assert (
        "INSUFFICIENT_CALENDAR_SPAN"
        in audit_hourly(
            history(), CAL, WINDOW, replace(POLICY, minimum_days=365), audit_at=NOW
        ).coverage_errors
    )
    assert (
        "INSUFFICIENT_PARTITION_SESSIONS"
        in audit_hourly(
            history(), CAL, WINDOW, replace(POLICY, minimum_partition_sessions=100), audit_at=NOW
        ).coverage_errors
    )
    with pytest.raises(ValueError):
        replace(POLICY, warmup_bars=34)
    with pytest.raises(ValueError):
        replace(POLICY, minimum_days=True)
    with pytest.raises(ValueError):
        replace(WINDOW, test_at=WINDOW.train_at)
    with pytest.raises(ValueError):
        replace(WINDOW, train_at=WINDOW.train_at.replace(tzinfo=None))


def test_future_prices_cannot_supply_warmup() -> None:
    data = history()
    late = replace(data, bars=tuple(replace(b, known_at=WINDOW.validation_at) for b in data.bars))
    result = audit_hourly(late, CAL, WINDOW, POLICY, audit_at=NOW)
    assert result.warmup_counts[0] == 0
    assert "INSUFFICIENT_POINT_IN_TIME_WARMUP" in result.coverage_errors


def test_dst_and_half_day_grid() -> None:
    sessions = CAL.sessions(date(2026, 3, 6), date(2026, 3, 9))
    assert [s.opens.hour for s in sessions] == [14, 13]
    day = CAL.sessions(date(2026, 11, 27), date(2026, 11, 27))[0]
    assert day.closes - day.opens == timedelta(hours=3, minutes=30)
    assert len(CAL.sessions(date(2026, 11, 26), date(2026, 11, 27))) == 1


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_cached_hourly_exact_bytes_and_explicit_basis(
    tmp_path: Path, newline: bytes, bom: bytes
) -> None:
    raw = bom + newline.join(
        [
            b"start,end,open,high,low,close,volume,known_at",
            b"2026-03-09T09:30:00-04:00,2026-03-09T10:30:00-04:00,100,101,99,100,1000,",
            b"",
        ]
    )
    archive = Archive(tmp_path / "history.sqlite")
    identity = archive.put(raw, source(raw))
    parsed = cached_hourly(
        Archive(archive.path), identity, exchange="XNYS", currency="USD", basis="raw"
    )
    assert parsed.bars[0].start == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    assert parsed.bars[0].known_at == NOW
    assert not parsed.point_in_time_verified
    assert archive.get(identity)[0] == raw
    assert (
        cached_hourly(archive, identity, exchange="XNYS", currency="USD", basis="unknown").basis
        == "unknown"
    )


def test_report_deterministic_and_metrics_absent() -> None:
    report = readiness_manifest(history(), CAL, WINDOW, POLICY, audit_at=NOW, snapshot="synthetic")
    assert json.dumps(report, default=str, sort_keys=True) == json.dumps(
        readiness_manifest(history(), CAL, WINDOW, POLICY, audit_at=NOW, snapshot="synthetic"),
        default=str,
        sort_keys=True,
    )
    assert report["timezone"] == "America/New_York"
    rows = report["comparisons"]
    assert isinstance(rows, list) and len(rows) == 10
    assert all(
        row["status"] == "not_run"
        and row["total_return"] is None
        and row["number_of_trades"] is None
        for row in rows
    )


def test_replay_rejects_before_creating_state(tmp_path: Path) -> None:
    from etoro_demo_bot.backtest.fixtures import synthetic_dataset
    from etoro_demo_bot.backtest.models import Plan, Simulation
    from etoro_demo_bot.strategy.models import Rules

    with pytest.raises(ValueError, match="insufficient"):
        run_hourly_study(
            history(),
            CAL,
            synthetic_dataset(1),
            Plan(Rules(), Simulation()),
            tmp_path / "run",
            window=WINDOW,
            policy=POLICY,
            audit_at=NOW,
            review_reference="synthetic test",
        )
    assert not (tmp_path / "run").exists()


def test_hourly_cli_cache_reproduction_and_checksum_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    from dataclasses import asdict

    from etoro_demo_bot.history.hourly_cli import main

    raw = (
        b"start,end,open,high,low,close,volume,known_at\r\n"
        b"2026-03-09T13:30:00Z,2026-03-09T14:30:00Z,100,101,99,100,1000,\r\n"
    )
    csv_path, source_path, study_path = (
        tmp_path / n for n in ("bars.csv", "source.json", "study.json")
    )
    csv_path.write_bytes(raw)
    source_path.write_text(json.dumps(asdict(source(raw)), default=str), encoding="utf-8")
    request = asdict(WINDOW) | {
        "audit_at": NOW,
        "calendar_verified_at": NOW,
        "exchange": "XNYS",
        "currency": "USD",
        "basis": "raw",
    }
    study_path.write_text(json.dumps(request, default=str), encoding="utf-8")
    common = ["hourly_cli", "--study", str(study_path), "--cache", str(tmp_path / "cache.sqlite")]
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    monkeypatch.setattr(
        sys,
        "argv",
        common + ["--csv", str(csv_path), "--source", str(source_path), "--output", str(first)],
    )
    assert main() == 0
    report = json.loads(first.read_text(encoding="utf-8"))
    assert "INSUFFICIENT_CALENDAR_SPAN" in report["audit"]["coverage_errors"]
    monkeypatch.setattr(
        sys, "argv", common + ["--snapshot", report["snapshot"], "--output", str(second)]
    )
    assert main() == 0
    assert first.read_bytes() == second.read_bytes()
    csv_path.write_bytes(raw.replace(b"\r\n", b"\n"))
    monkeypatch.setattr(
        sys,
        "argv",
        common
        + [
            "--csv",
            str(csv_path),
            "--source",
            str(source_path),
            "--output",
            str(tmp_path / "bad.json"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert not (tmp_path / "bad.json").exists()


def test_reviewed_contract_delegates_to_existing_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fabricated attestations exercise the call boundary, not real historical verification.
    from unittest.mock import MagicMock

    from etoro_demo_bot.backtest.fixtures import synthetic_dataset
    from etoro_demo_bot.backtest.models import Plan, Simulation
    from etoro_demo_bot.history import hourly
    from etoro_demo_bot.strategy.models import Rules

    data = history()
    reviewed = replace(
        data,
        source=replace(data.source, classification="historical_observation"),
        actions_complete=True,
        point_in_time_verified=True,
    )
    engine_data = replace(synthetic_dataset(1), start=WINDOW.train_at, end=WINDOW.test_at)
    plan = Plan(Rules(), Simulation())
    delegate = MagicMock()
    monkeypatch.setattr(hourly, "run_verified", delegate)
    run_hourly_study(
        reviewed,
        CAL,
        engine_data,
        plan,
        tmp_path / "run",
        window=WINDOW,
        policy=POLICY,
        audit_at=NOW,
        review_reference="INVENTED_TEST_ATTESTATION",
    )
    delegate.assert_called_once_with(
        reviewed,
        CAL,
        engine_data,
        plan,
        tmp_path / "run",
        review_reference="INVENTED_TEST_ATTESTATION",
        coverage_start=WINDOW.start,
        coverage_end=WINDOW.end,
        audit_at=NOW,
    )
