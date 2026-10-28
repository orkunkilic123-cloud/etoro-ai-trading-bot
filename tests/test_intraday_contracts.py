"""Deterministic SYNTHETIC research fixtures only; never keys or real-data requests."""

import hashlib
import json
import socket
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import pytest

from etoro_demo_bot.alpaca import __main__ as alpaca_cli
from etoro_demo_bot.alpaca.client import MarketDataClient
from etoro_demo_bot.alpaca.config import Credentials, DataError
from etoro_demo_bot.alpaca.contracts import BARS, ORIGIN, BarsQuery, query_from_source
from etoro_demo_bot.backtest.fixtures import synthetic_dataset
from etoro_demo_bot.history.alpaca import archive_research_pages, decode_page
from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.history.calendar import NYSE2026
from etoro_demo_bot.history.intraday import qualify_download, research_report
from etoro_demo_bot.history.intraday_cli import main as audit_main
from etoro_demo_bot.scanner.indicators import calculate
from etoro_demo_bot.strategy.engine import point_in_time
from etoro_demo_bot.timeframes import (
    FIVE_MINUTE_RESEARCH,
    HOURLY_BASELINE,
    BarContract,
    Timeframe,
    require_hourly_baseline,
)


@pytest.fixture(autouse=True)
def no_keys_or_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Intraday contract tests must not access credentials or sockets")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(Credentials, "from_environment", blocked)


def calendar(day: date) -> NYSE2026:
    return NYSE2026(verified_at=datetime.combine(day, datetime.min.time(), UTC))


def rows_for(day: date) -> list[dict[str, Any]]:
    sessions = calendar(day).sessions(day, day)
    if not sessions:
        return []
    s = sessions[0]
    point = s.opens
    rows = []
    while point < s.closes:
        rows.append({"t": point.isoformat(), "o": 100, "h": 101, "l": 99, "c": 100, "v": 10})
        point += timedelta(minutes=5)
    return rows


def put_page(
    archive: Archive,
    day: date,
    rows: list[dict[str, Any]],
    *,
    token: str | None = None,
    cursor: str | None = None,
    timeframe: Timeframe = Timeframe.FIVE_MINUTES,
    adjustment: str = "raw",
    retrieved_at: datetime | None = None,
) -> str:
    from etoro_demo_bot.history.models import Source

    query = BarsQuery(
        ("IBM",),
        datetime.combine(day, datetime.min.time(), UTC),
        datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC),
        adjustment,
        timeframe,
    )
    params = query.params()
    if cursor:
        params["page_token"] = cursor
    raw = json.dumps({"bars": {"IBM": rows}, "next_page_token": token}).encode()
    when = retrieved_at or datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=22)
    return archive.put(
        raw,
        Source(
            "alpaca-iex-5min-v1" if timeframe is Timeframe.FIVE_MINUTES else "alpaca-iex-hourly",
            ORIGIN + BARS + "?" + urlencode(params),
            "https://alpaca.markets/disclosures",
            when,
            hashlib.sha256(raw).hexdigest(),
            "synthetic",
            "SYNTHETIC test data; no market observations",
        ),
    )


def fixture_download(
    tmp_path: Path,
    day: date,
    *,
    rows: list[dict[str, Any]] | None = None,
    adjustment: str = "raw",
    retrieved_at: datetime | None = None,
) -> tuple[Archive, str]:
    archive = Archive(tmp_path / "research.sqlite")
    page = put_page(
        archive,
        day,
        rows_for(day) if rows is None else rows,
        adjustment=adjustment,
        retrieved_at=retrieved_at,
    )
    return archive, archive_research_pages(archive, (page,), "IBM")


def qualify(archive: Archive, identity: str, day: date, **kwargs: Any) -> Any:
    return qualify_download(
        archive,
        identity,
        "IBM",
        start=day,
        end=day,
        calendar=calendar(day),
        audit_at=datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=22),
        **kwargs,
    )


@pytest.mark.parametrize(
    "day,open_hour,count",
    [
        (date(2026, 3, 6), 14, 78),
        (date(2026, 3, 9), 13, 78),
        (date(2026, 10, 30), 13, 78),
        (date(2026, 11, 2), 14, 78),
        (date(2026, 11, 27), 14, 42),
        (date(2026, 12, 24), 14, 42),
    ],
)
def test_session_grid_dst_early_close_and_metadata(
    tmp_path: Path, day: date, open_hour: int, count: int
) -> None:
    archive, identity = fixture_download(tmp_path, day)
    series = qualify(archive, identity, day)
    assert len(series.bars) == count
    assert series.bars[0].observation.start.hour == open_hour
    assert series.bars[0].observation.start.minute == 30
    assert series.sessions[0].timezone == "America/New_York"
    assert series.sessions[0].version == "XNYS-regular-2026-v1"
    assert series.bars[-1].completed_at == series.sessions[0].closes
    assert series.bars[0].first_known_at == series.source.retrieved_at
    assert series.bars[0].source_snapshot == identity
    assert not series.execution_authorized
    assert "ORIGINAL_AVAILABILITY_UNVERIFIED" in series.replay_blockers
    assert "STRATEGY_REQUIRES_HOURLY_HISTORY" in series.replay_blockers
    assert research_report(series)["structural_qualification"] is True


@pytest.mark.parametrize(
    "day", [date(2026, 1, 1), date(2026, 7, 3), date(2026, 11, 26), date(2026, 3, 7)]
)
def test_closed_days_cannot_qualify(tmp_path: Path, day: date) -> None:
    archive, identity = fixture_download(tmp_path, day)
    with pytest.raises(ValueError):
        qualify(archive, identity, day)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "empty",
        "premarket",
        "after_close",
        "offgrid",
        "seconds",
        "duplicate",
        "overlap",
        "reverse",
        "badprice",
    ],
)
def test_invalid_bars_rejected_without_fabrication(tmp_path: Path, change: str) -> None:
    day = date(2026, 3, 9)
    rows = rows_for(day)
    if change == "missing":
        rows.pop(2)
    if change == "empty":
        rows = []
    if change == "premarket":
        rows[0]["t"] = "2026-03-09T13:25:00Z"
    if change == "after_close":
        rows[-1]["t"] = "2026-03-09T20:00:00Z"
    if change == "offgrid":
        rows[0]["t"] = "2026-03-09T13:31:00Z"
    if change == "seconds":
        rows[0]["t"] = "2026-03-09T13:30:01Z"
    if change == "duplicate":
        rows.insert(1, dict(rows[0]))
    if change == "overlap":
        rows[1]["t"] = "2026-03-09T13:32:00Z"
    if change == "reverse":
        rows.reverse()
    if change == "badprice":
        rows[0]["o"] = "NaN"
    with pytest.raises(ValueError):
        archive, identity = fixture_download(tmp_path, day, rows=rows)
        qualify(archive, identity, day)


def test_native_offset_and_original_bytes_preserved(tmp_path: Path) -> None:
    day = date(2026, 3, 9)
    archive = Archive(tmp_path / "cache.sqlite")
    rows = rows_for(day)
    rows[0]["t"] = "2026-03-09T09:30:00-04:00"
    page = put_page(archive, day, rows)
    identity = archive_research_pages(archive, (page,), "IBM")
    series = qualify(archive, identity, day)
    assert series.bars[0].observation.start.isoformat() == "2026-03-09T13:30:00+00:00"
    assert b"09:30:00-04:00" in archive.get(page)[0]


@pytest.mark.parametrize(
    "change", ["incomplete", "wrong_cursor", "mixed_timeframe", "duplicate_page"]
)
def test_page_chain_rejects_mixed_or_incomplete_inputs(tmp_path: Path, change: str) -> None:
    day = date(2026, 3, 9)
    archive = Archive(tmp_path / "cache.sqlite")
    rows = rows_for(day)
    first = put_page(archive, day, rows[:39], token="next")
    second = put_page(
        archive,
        day,
        rows[39:],
        cursor="wrong" if change == "wrong_cursor" else "next",
        timeframe=Timeframe.HOUR if change == "mixed_timeframe" else Timeframe.FIVE_MINUTES,
    )
    ids = (
        (first,)
        if change == "incomplete"
        else (first, first)
        if change == "duplicate_page"
        else (first, second)
    )
    with pytest.raises(ValueError):
        archive_research_pages(archive, ids, "IBM")


def test_valid_multi_page_chain_and_tamper_detection(tmp_path: Path) -> None:
    import sqlite3

    day = date(2026, 3, 9)
    archive = Archive(tmp_path / "cache.sqlite")
    rows = rows_for(day)
    a = put_page(archive, day, rows[:39], token="next")
    b = put_page(archive, day, rows[39:], cursor="next")
    identity = archive_research_pages(archive, (a, b), "IBM")
    assert len(qualify(archive, identity, day).bars) == 78
    with sqlite3.connect(archive.path) as db:
        db.execute("UPDATE snapshots SET raw=? WHERE id=?", (b"corrupt", a))
    with pytest.raises(ValueError):
        qualify(archive, identity, day)


@pytest.mark.parametrize("change", ["stale", "future", "split", "wrong_window", "calendar_future"])
def test_qualification_rejects_bad_source_or_window(tmp_path: Path, change: str) -> None:
    day = date(2026, 3, 9)
    when = datetime(2026, 3, 9, 22, tzinfo=UTC)
    retrieved = when + timedelta(days=1) if change == "future" else when
    archive, identity = fixture_download(
        tmp_path, day, retrieved_at=retrieved, adjustment="split" if change == "split" else "raw"
    )
    with pytest.raises(ValueError):
        qualify_download(
            archive,
            identity,
            "IBM",
            start=day,
            end=day + timedelta(days=1) if change == "wrong_window" else day,
            audit_at=when + timedelta(days=2) if change == "stale" else when,
            calendar=NYSE2026(
                verified_at=when + timedelta(seconds=1) if change == "calendar_future" else when
            ),
        )


def test_completion_and_first_known_prevent_lookahead(tmp_path: Path) -> None:
    day = date(2026, 3, 9)
    close = calendar(day).sessions(day, day)[0].closes
    archive, identity = fixture_download(tmp_path, day, retrieved_at=close)
    series = qualify(archive, identity, day)
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        series.visible_at(close - timedelta(seconds=1))
    assert len(series.visible_at(close)) == 78
    assert len(series.visible_at(close + timedelta(seconds=300))) == 78
    with pytest.raises(ValueError, match="STALE"):
        series.visible_at(close + timedelta(seconds=301))
    with pytest.raises(ValueError):
        series.visible_at(close.replace(tzinfo=None))


def test_incomplete_page_end_rejected(tmp_path: Path) -> None:
    day = date(2026, 3, 9)
    archive = Archive(tmp_path / "cache.sqlite")
    page = put_page(
        archive, day, rows_for(day)[:1], retrieved_at=datetime(2026, 3, 9, 13, 32, tzinfo=UTC)
    )
    raw, source = archive.get(page)
    with pytest.raises(ValueError):
        decode_page(raw, source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "v2"),
        ("timezone", "UTC"),
        ("exchange", "XNAS"),
        ("timeframe", "5Min"),
        ("alignment", "guess"),
        ("research_only", True),
    ],
)
def test_baseline_consumer_contract_denials(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        require_hourly_baseline(replace(HOURLY_BASELINE, **{field: value}))


def test_hourly_query_and_existing_consumers_remain_baseline(tmp_path: Path) -> None:
    at = datetime(2026, 3, 9, tzinfo=UTC)
    query = BarsQuery(("IBM",), at, at + timedelta(days=1))
    assert query.params()["timeframe"] == "1Hour"
    assert query.version == "alpaca-bars-v1"
    assert Timeframe.HOUR.duration == timedelta(hours=1)
    assert Timeframe.FIVE_MINUTES.duration == timedelta(minutes=5)
    require_hourly_baseline(HOURLY_BASELINE)
    data = synthetic_dataset(1)
    data.validate()
    replace(data, contract=HOURLY_BASELINE).validate()
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        replace(data, contract=FIVE_MINUTE_RESEARCH).validate()
    bar = replace(data.history[0].candle, contract=FIVE_MINUTE_RESEARCH)
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        replace(data, history=(replace(data.history[0], candle=bar),)).validate()
    # Indicator inputs cannot silently acquire a new timeframe via the old interval argument.
    candles = tuple(replace(x.candle, contract=FIVE_MINUTE_RESEARCH) for x in data.history)
    with pytest.raises(ValueError):
        calculate(candles, interval_seconds=300)


def test_strategy_interface_rejects_five_minute_context() -> None:
    from etoro_demo_bot.monte_carlo.fixtures import synthetic_inputs

    context, _ = synthetic_inputs(500)
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        point_in_time(replace(context, contract=FIVE_MINUTE_RESEARCH), context.account.observed_at)
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        point_in_time(
            replace(
                context, opportunity=replace(context.opportunity, contract=FIVE_MINUTE_RESEARCH)
            ),
            context.account.observed_at,
        )


def test_five_minute_network_and_cli_disabled_before_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = date(2026, 3, 9)
    query = BarsQuery(
        ("IBM",),
        datetime(2026, 3, 9, tzinfo=UTC),
        datetime(2026, 3, 10, tzinfo=UTC),
        timeframe=Timeframe.FIVE_MINUTES,
    )
    with (
        MarketDataClient(
            Credentials("SYNTHETIC_KEY", "SYNTHETIC_SECRET"),
            Archive(tmp_path / "cache.sqlite"),
            enabled=True,
            transport=httpx.MockTransport(lambda r: pytest.fail("Transport reached")),
        ) as api,
        pytest.raises(DataError),
    ):
        api.fetch(query)
    args = [
        "alpaca",
        "--symbols",
        "IBM",
        "--start",
        str(day) + "T00:00:00Z",
        "--end",
        "2026-03-10T00:00:00Z",
        "--timeframe",
        "5Min",
    ]
    monkeypatch.setattr(sys, "argv", args + ["--dry-run"])
    assert alpaca_cli.main() == 0
    monkeypatch.setattr(sys, "argv", args + ["--enable-network"])
    with pytest.raises(SystemExit) as error:
        alpaca_cli.main()
    assert error.value.code == 1


def test_offline_cli_exclusive_report_and_readonly_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = date(2026, 3, 9)
    archive, identity = fixture_download(tmp_path, day)
    before = archive.path.read_bytes()
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "intraday_cli",
            "--cache",
            str(archive.path),
            "--manifest",
            identity,
            "--symbol",
            "IBM",
            "--start",
            str(day),
            "--end",
            str(day),
            "--audit-at",
            "2026-03-09T22:00:00Z",
            "--calendar-verified-at",
            "2026-03-09T00:00:00Z",
            "--output",
            str(output),
        ],
    )
    assert audit_main() == 0
    report = json.loads(output.read_text())
    assert report["bars"] == 78 and not report["execution_authorized"]
    with pytest.raises(SystemExit):
        audit_main()
    assert archive.path.read_bytes() == before


def test_scanner_contract_rejected_before_source_access() -> None:
    from unittest.mock import MagicMock

    from etoro_demo_bot.monte_carlo.fixtures import synthetic_inputs
    from etoro_demo_bot.scanner.engine import Scanner

    context, _ = synthetic_inputs(500)
    source = MagicMock()
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        Scanner(source, MagicMock(), context.evidence.budget, contract=FIVE_MINUTE_RESEARCH)
    assert not source.mock_calls


@pytest.mark.parametrize("field", ["context", "opportunity", "candle"])
def test_strategy_proposal_rejects_mixed_contracts(tmp_path: Path, field: str) -> None:
    from etoro_demo_bot.monte_carlo.fixtures import synthetic_inputs
    from etoro_demo_bot.strategy.engine import StrategyEngine
    from etoro_demo_bot.strategy.journal import Journal

    context, _ = synthetic_inputs(500)
    if field == "context":
        context = replace(context, contract=FIVE_MINUTE_RESEARCH)
    elif field == "opportunity":
        context = replace(
            context, opportunity=replace(context.opportunity, contract=FIVE_MINUTE_RESEARCH)
        )
    else:
        changed = replace(
            context.bars[0], candle=replace(context.bars[0].candle, contract=FIVE_MINUTE_RESEARCH)
        )
        context = replace(context, bars=(changed,) + context.bars[1:])
    engine = StrategyEngine(Journal.initialize(tmp_path / "strategy.sqlite"))
    result = engine.propose(context, now=context.account.observed_at)
    assert result.candidate is None and result.status == "rejected"


@pytest.mark.parametrize("mode", ["before_close", "unknown_year", "naive_audit", "wrong_contract"])
def test_session_and_contract_qualification_denials(tmp_path: Path, mode: str) -> None:
    day = date(2026, 3, 9)
    archive, identity = fixture_download(tmp_path, day)
    when = datetime(2026, 3, 9, 22, tzinfo=UTC)
    if mode == "before_close":
        when = datetime(2026, 3, 9, 19, tzinfo=UTC)
    elif mode == "naive_audit":
        when = when.replace(tzinfo=None)
    with pytest.raises(ValueError):
        qualify_download(
            archive,
            identity,
            "IBM",
            start=date(2027, 3, 9) if mode == "unknown_year" else day,
            end=date(2027, 3, 9) if mode == "unknown_year" else day,
            audit_at=when,
            calendar=calendar(day),
            contract=HOURLY_BASELINE if mode == "wrong_contract" else FIVE_MINUTE_RESEARCH,
        )


@pytest.mark.parametrize("mode", ["provider", "feed", "timeframe", "duplicate_parameter"])
def test_five_minute_provenance_denials(tmp_path: Path, mode: str) -> None:
    day = date(2026, 3, 9)
    archive = Archive(tmp_path / "cache.sqlite")
    identity = put_page(archive, day, rows_for(day))
    _, source = archive.get(identity)
    if mode == "provider":
        source = replace(source, provider="alpaca-iex-hourly")
    elif mode == "feed":
        source = replace(source, url=source.url.replace("feed=iex", "feed=sip"))
    elif mode == "timeframe":
        source = replace(source, url=source.url.replace("timeframe=5Min", "timeframe=1Min"))
    else:
        source = replace(source, url=source.url + "&timeframe=5Min")
    with pytest.raises(ValueError):
        query_from_source(source)


def test_hourly_query_version_and_research_flag_are_not_switches() -> None:
    with pytest.raises(ValueError):
        BarContract(Timeframe.FIVE_MINUTES, research_only=False)
    with pytest.raises(ValueError):
        BarsQuery(
            ("IBM",),
            datetime(2026, 3, 9, tzinfo=UTC),
            datetime(2026, 3, 10, tzinfo=UTC),
            version="unknown",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("timezone", "UTC"),
        ("exchange", "XNAS"),
        ("version", "v0"),
        ("opens", datetime(2026, 3, 9, 14, 30, tzinfo=UTC)),
        ("closes", datetime(2026, 3, 9, 21, tzinfo=UTC)),
    ],
)
def test_session_contract_cannot_override_calendar(tmp_path: Path, field: str, value: Any) -> None:
    day = date(2026, 3, 9)
    archive, identity = fixture_download(tmp_path, day)
    session = qualify(archive, identity, day).sessions[0]
    with pytest.raises(ValueError):
        replace(session, **{field: value})


def test_observation_completion_and_known_at_are_not_interchangeable(tmp_path: Path) -> None:
    day = date(2026, 3, 9)
    archive, identity = fixture_download(tmp_path, day)
    observation = qualify(archive, identity, day).bars[0]
    with pytest.raises(ValueError):
        replace(observation, first_known_at=observation.completed_at)
    with pytest.raises(ValueError):
        replace(observation, completed_at=observation.completed_at - timedelta(seconds=1))


def test_hourly_indicator_cannot_be_relabelled_by_interval_argument() -> None:
    data = synthetic_dataset(1)
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        calculate(tuple(b.candle for b in data.history), interval_seconds=300)
