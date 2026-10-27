"""Invented fixtures only: not redistributed vendor prices or profitability evidence."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.history.calendar import NYSE2026
from etoro_demo_bot.history.models import Action, History, Source
from etoro_demo_bot.history.providers import (
    AlphaVantageDaily,
    CSVHistory,
    Providers,
    ecb_usd_reference,
)
from etoro_demo_bot.history.quality import inspect, split_adjust_as_of
from etoro_demo_bot.history.replay import blockers
from etoro_demo_bot.history.report import write_readiness

NOW = datetime(2026, 10, 27, 22, tzinfo=UTC)
CAL = NYSE2026(verified_at=NOW)
RAW = b"timestamp,open,high,low,close,volume\n2026-10-26,100,103,99,102,1000\n"


def source(raw: bytes = RAW) -> Source:
    return Source(
        "invented_fixture",
        "synthetic://fixture",
        "synthetic://license",
        NOW,
        hashlib.sha256(raw).hexdigest(),
        "synthetic",
        "Invented test data.",
        symbol="IBM",
    )


def history() -> History:
    return AlphaVantageDaily("IBM", CAL).parse(RAW, source())


def codes(data: History) -> set[str]:
    return {
        f.code
        for f in inspect(
            data, CAL, start=date(2026, 10, 26), end=date(2026, 10, 26), as_of=NOW
        ).findings
    }


def test_raw_daily_preserves_availability() -> None:
    data = history()
    assert data.bars[0].open == D("100")
    assert data.bars[0].known_at == NOW
    assert data.basis == "raw"
    assert codes(data) == {"ACTIONS_INCOMPLETE"}
    assert "SYNTHETIC_SOURCE" in blockers(data)
    assert "STRATEGY_REQUIRES_HOURLY_HISTORY" in blockers(data)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"timestamp,open,high,low,close,volume\n",
        RAW.replace(b"100,103", b"NaN,103"),
        RAW.replace(b"2026-10-26", b"2026-10-25"),
    ],
)
def test_bad_daily_rejected(raw: bytes) -> None:
    with pytest.raises(ValueError):
        AlphaVantageDaily("IBM", CAL).parse(raw, source(raw))


def test_provenance_symbol_and_checksum() -> None:
    for value in (
        replace(source(), symbol="SPY"),
        replace(source(), raw_sha256="wrong"),
        replace(source(), classification="historical_verified"),
    ):
        with pytest.raises(ValueError):
            AlphaVantageDaily("IBM", CAL).parse(RAW, value)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("high", D("90"), "INVALID_OHLC"),
        ("low", D("NaN"), "INVALID_OHLC"),
        ("volume", None, "MISSING_VOLUME"),
        ("volume", D(0), "MISSING_VOLUME"),
        ("basis", "split_adjusted", "MIXED_ADJUSTMENTS"),
        ("known_at", datetime(2026, 10, 26, 12, tzinfo=UTC), "INVALID_AVAILABILITY"),
        ("start", datetime(2026, 10, 26, 13, 30), "NAIVE_TIME"),
    ],
)
def test_quality_failures(field: str, value: Any, code: str) -> None:
    data = history()
    assert code in codes(replace(data, bars=(replace(data.bars[0], **{field: value}),)))


def test_duplicates_missing_stale_and_adjustment_checks() -> None:
    data = history()
    assert "DUPLICATE" in codes(replace(data, bars=data.bars * 2))
    assert "MISSING_CANDLES" in codes(replace(data, bars=()))
    assert "ADJUSTMENT_PROVENANCE_MISSING" in codes(replace(data, basis="split_adjusted"))
    quality = inspect(
        data, CAL, start=date(2026, 10, 26), end=date(2026, 10, 27), as_of=NOW, require_current=True
    )
    assert {"MISSING_CANDLES", "STALE"} <= {f.code for f in quality.findings}


def test_gap_and_point_in_time_split() -> None:
    data = history()
    bar = data.bars[0]
    prior = replace(
        bar,
        start=bar.start - timedelta(days=3),
        end=bar.end - timedelta(days=3),
        open=D(200),
        high=D(206),
        low=D(198),
        close=D(204),
        known_at=bar.end - timedelta(days=3),
    )
    event = Action("IBM", "split", bar.start, bar.start, D(2), "synthetic://action")
    data = replace(data, bars=(prior, bar), actions_complete=True)
    assert "SUSPICIOUS_JUMP" in codes(data)
    assert "SPLIT_JUMP" in codes(replace(data, actions=(event,)))
    before = split_adjust_as_of(data, (event,), as_of=prior.end)
    after = split_adjust_as_of(data, (event,), as_of=NOW)
    assert before[0].close == 204 and after[0].close == 102
    assert after[0].volume == 2000
    assert after[0].known_at == event.effective_at
    late = replace(event, known_at=NOW + timedelta(days=1))
    assert split_adjust_as_of(data, (late,), as_of=NOW)[0].close == 204
    with pytest.raises(ValueError, match="Duplicate"):
        split_adjust_as_of(data, (event, event), as_of=NOW)
    with pytest.raises(ValueError):
        split_adjust_as_of(replace(data, actions_complete=False), (event,), as_of=NOW)


def test_calendar_dst_holidays_early_close_and_bounds() -> None:
    assert not CAL.sessions(date(2026, 7, 3), date(2026, 7, 3))
    assert CAL.sessions(date(2026, 11, 27), date(2026, 11, 27))[0].closes.hour == 18
    assert CAL.sessions(date(2026, 3, 6), date(2026, 3, 6))[0].opens.hour == 14
    assert CAL.sessions(date(2026, 3, 9), date(2026, 3, 9))[0].opens.hour == 13
    with pytest.raises(ValueError):
        CAL.sessions(date(2025, 1, 1), date(2026, 1, 1))


def test_archive_restart_and_tamper(tmp_path: Path) -> None:
    path = tmp_path / "archive.sqlite"
    first = Archive(path).put(RAW, source())
    assert Archive(path).put(RAW, source()) == first
    assert Archive(path).get(first) == (RAW, source())
    with sqlite3.connect(path) as db:
        db.execute("UPDATE snapshots SET raw=?", (b"altered",))
    with pytest.raises(ValueError, match="integrity"):
        Archive(path).get(first)
    with pytest.raises(ValueError):
        Archive(path).get("absent")


def test_provider_neutral_csv_registry() -> None:
    raw = (
        b"start,end,open,high,low,close,volume,known_at\n"
        b"2026-10-26T13:30:00Z,2026-10-26T20:00:00Z,100,103,99,102,1000,\n"
    )
    registry = Providers()
    provider = CSVHistory(
        symbol="IBM", exchange="XNYS", currency="USD", resolution="1d", basis="raw"
    )
    registry.register("licensed-export", provider)
    assert registry.parse("licensed-export", raw, source(raw)).bars[0].known_at == NOW
    with pytest.raises(ValueError):
        registry.register("licensed-export", provider)
    with pytest.raises(ValueError):
        provider.parse(
            raw.replace(b"13:30:00Z", b"13:30:00"), source(raw.replace(b"13:30:00Z", b"13:30:00"))
        )


def test_ecb_reference_not_execution_evidence() -> None:
    raw = b'<root><Cube time="2026-10-26"><Cube currency="USD" rate="1.10"/></Cube></root>'
    assert ecb_usd_reference(raw, source(raw)) == ((date(2026, 10, 26), D("1.10")),)
    malformed = b"<!DOCTYPE root>" + raw
    with pytest.raises(ValueError):
        ecb_usd_reference(malformed, source(malformed))


def test_readiness_reports_deterministic_and_never_performance(tmp_path: Path) -> None:
    data = history()
    quality = inspect(data, CAL, start=date(2026, 10, 26), end=date(2026, 10, 26), as_of=NOW)
    for name in ("one", "two"):
        write_readiness(data, quality, tmp_path / name, "snapshot")
    for name in ("readiness.json", "comparisons.csv", "README.md"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    payload = json.loads((tmp_path / "one" / "readiness.json").read_text())
    assert len(payload["comparisons"]) == 10
    assert all(
        row["status"] == "blocked" and row["total_return"] is None for row in payload["comparisons"]
    )


def test_recorded_public_ecb_sample() -> None:
    root = Path(__file__).parent / "fixtures" / "history"
    metadata = json.loads((root / "ecb-source.json").read_text())
    metadata["retrieved_at"] = datetime.fromisoformat(metadata["retrieved_at"])
    evidence = Source(**metadata)
    values = ecb_usd_reference((root / "ecb-90d.xml").read_bytes(), evidence)
    assert len(values) > 50
    assert all(a[0] < b[0] for a, b in zip(values, values[1:], strict=False))
    assert all(rate > 0 for _, rate in values)
    assert values[-1][0] <= evidence.retrieved_at.date()


def test_replay_gate_rejects_daily_without_creating_state(tmp_path: Path) -> None:
    from etoro_demo_bot.backtest.fixtures import synthetic_dataset
    from etoro_demo_bot.backtest.models import Plan, Simulation
    from etoro_demo_bot.history.replay import run_verified
    from etoro_demo_bot.strategy.models import Rules

    with pytest.raises(ValueError, match="incomplete"):
        run_verified(
            history(),
            CAL,
            synthetic_dataset(1),
            Plan(Rules(), Simulation()),
            tmp_path / "run",
            review_reference="test",
            coverage_start=date(2026, 10, 26),
            coverage_end=date(2026, 10, 26),
            audit_at=NOW,
        )
    assert not (tmp_path / "run").exists()


def test_history_has_no_network_or_execution_imports() -> None:
    import ast

    root = Path(__file__).parents[1] / "src" / "etoro_demo_bot" / "history"
    for file in root.glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not any(
                    s in (node.module or "").split(".")
                    for s in ("execution", "client", "httpx", "requests", "urllib")
                )
            if isinstance(node, ast.Import):
                assert not any(n.name in ("httpx", "requests", "os") for n in node.names)


def test_hourly_adapter_delegates_without_bypassing_backtest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Invented attestation contract test, not historical evidence or a profitability run.
    from unittest.mock import MagicMock

    from etoro_demo_bot.backtest.fixtures import synthetic_dataset
    from etoro_demo_bot.backtest.models import Plan, Simulation
    from etoro_demo_bot.history import replay
    from etoro_demo_bot.strategy.models import Rules

    data = history()
    opening = data.bars[0].start
    hourly = tuple(
        replace(
            data.bars[0],
            start=opening + timedelta(hours=i),
            end=opening + timedelta(hours=i + 1),
            known_at=opening + timedelta(hours=i + 1),
        )
        for i in range(6)
    )
    reviewed = replace(
        data,
        bars=hourly,
        resolution="1h",
        actions_complete=True,
        point_in_time_verified=True,
        source=replace(data.source, classification="historical_observation"),
    )
    template = synthetic_dataset(1)
    at = opening + timedelta(minutes=30)
    tick = template.ticks[0]
    tick = replace(
        tick,
        at=at,
        quote=replace(tick.quote, observed_at=at),
        evidence=replace(tick.evidence, available_at=at, session_close=data.bars[0].end),
    )
    bundle = replace(
        template,
        start=opening.replace(hour=0, minute=0),
        end=at,
        initial_fx_known_at=opening.replace(hour=0, minute=0),
        ticks=(tick,),
        instrument=replace(template.instrument, symbol="IBM"),
        provenance=replace(
            template.provenance,
            kind="historical_verified",
            review_reference="INVENTED_TEST_ATTESTATION",
        ),
    )
    engine = MagicMock()
    monkeypatch.setattr(replay, "Backtest", engine)
    replay.run_verified(
        reviewed,
        CAL,
        bundle,
        Plan(Rules(), Simulation()),
        tmp_path / "run",
        review_reference="INVENTED_TEST_ATTESTATION",
        coverage_start=date(2026, 10, 26),
        coverage_end=date(2026, 10, 26),
        audit_at=NOW,
    )
    engine.assert_called_once()
    forwarded = engine.call_args.args[0]
    assert forwarded.history[0].available_at == hourly[0].end
    assert data.source.raw_sha256 in forwarded.provenance.source
    engine.return_value.run.assert_called_once_with(tmp_path / "run")
