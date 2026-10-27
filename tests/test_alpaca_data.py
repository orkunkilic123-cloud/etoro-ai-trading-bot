"""Synthetic mocked responses only. Never load real credentials or contact Alpaca."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from etoro_demo_bot.alpaca.client import MarketDataClient
from etoro_demo_bot.alpaca.config import Credentials, DataError
from etoro_demo_bot.alpaca.contracts import BARS, ORIGIN, BarsQuery
from etoro_demo_bot.history.alpaca import load_download, session_counts
from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.history.calendar import NYSE2026
from etoro_demo_bot.history.replay import blockers

KEY = "SYNTHETIC_KEY_NOT_A_CREDENTIAL"
SECRET = "SYNTHETIC_SECRET_NOT_A_CREDENTIAL"
NOW = datetime(2026, 10, 27, 18, tzinfo=UTC)
QUERY = BarsQuery(
    ("IBM", "SPY"), datetime(2026, 3, 6, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC)
)


class Clock:
    def __init__(self) -> None:
        self.now = NOW.timestamp()
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def bar(at: str = "2026-03-09T14:00:00Z") -> dict[str, Any]:
    return {"t": at, "o": 100.125, "h": 101, "l": 99, "c": 100.5, "v": 1000, "n": 10, "vw": 100}


def page(
    symbol: str = "IBM", *, token: str | None = None, at: str = "2026-03-09T14:00:00Z"
) -> dict[str, Any]:
    return {"bars": {symbol: [bar(at)]}, "next_page_token": token}


def client(
    tmp_path: Path, handler: Any, *, enabled: bool = True, clock: Clock | None = None
) -> MarketDataClient:
    timer = clock or Clock()
    return MarketDataClient(
        Credentials(KEY, SECRET),
        Archive(tmp_path / "data.sqlite"),
        enabled=enabled,
        transport=httpx.MockTransport(handler),
        clock=timer,
        sleep=timer.sleep,
    )


def test_exact_headers_feed_pagination_cache_and_replay_gate(tmp_path: Path) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url).startswith(ORIGIN + BARS + "?")
        assert request.method == "GET"
        assert request.headers["APCA-API-KEY-ID"] == KEY
        assert request.headers["APCA-API-SECRET-KEY"] == SECRET
        assert request.url.params["feed"] == "iex"
        assert request.url.params["timeframe"] == "1Hour"
        assert request.url.params["asof"] == "-"
        if len(requests) == 1:
            return httpx.Response(200, json=page(token="opaque+/="))
        assert request.url.params["page_token"] == "opaque+/="
        return httpx.Response(200, json=page("SPY"))

    timer = Clock()
    with client(tmp_path, handler, clock=timer) as api:
        identity = api.fetch(QUERY)
    archive = Archive(tmp_path / "data.sqlite")
    for symbol in QUERY.symbols:
        history = load_download(archive, identity, symbol, exchange="XNYS")
        assert len(history.bars) == 1
        assert str(history.bars[0].open) == "100.125"
        assert history.bars[0].known_at >= NOW
        assert history.source.provider == "alpaca-iex-download"
        assert "ORIGINAL_AVAILABILITY_UNVERIFIED" in blockers(history)
        assert "CORPORATE_ACTION_COVERAGE_INCOMPLETE" in blockers(history)
    manifest = json.loads(archive.get(identity)[0])
    assert manifest["feed"] == "iex" and len(manifest["pages"]) == 2
    assert timer.waits == [1]
    raw_file = (tmp_path / "data.sqlite").read_bytes()
    assert KEY.encode() not in raw_file and SECRET.encode() not in raw_file


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", BARS),
        ("DELETE", BARS),
        ("PATCH", BARS),
        ("PUT", BARS),
        ("GET", "/v2/account"),
        ("POST", "/v2/orders"),
        ("GET", "/v2/orders"),
        ("GET", "/v2/assets"),
        ("GET", "https://api.alpaca.markets/v2/account"),
        ("GET", "https://paper-api.alpaca.markets/v2/orders"),
        ("GET", BARS + "?feed=sip"),
        ("GET", BARS + "/"),
        ("GET", "/v2/stocks/../orders"),
        ("GET", "/v2/stocks/%2e%2e/orders"),
        ("GET", "//api.alpaca.markets/v2/account"),
        ("GET", "/v2/crypto/us/bars"),
    ],
)
def test_trading_and_route_variants_never_reach_transport(
    tmp_path: Path, method: str, path: str
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Transport must not be called")

    with client(tmp_path, forbidden) as api, pytest.raises(DataError):
        api.request(method, path, QUERY)


def test_network_opt_in_and_environment_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import os

    monkeypatch.setattr(
        os, "environ", {"ALPACA_DATA_API_KEY": KEY, "ALPACA_DATA_API_SECRET": SECRET}
    )
    with pytest.raises(DataError):
        Credentials.from_environment()
    monkeypatch.setattr(
        os,
        "environ",
        {
            "ALPACA_DATA_API_KEY": KEY,
            "ALPACA_DATA_API_SECRET": SECRET,
            "ALPACA_DATA_FREE_ACCESS_CONFIRMED": "true",
        },
    )
    credentials = Credentials.from_environment()
    assert KEY not in repr(credentials) and SECRET not in repr(credentials)
    with client(tmp_path, lambda request: pytest.fail("Network called"), enabled=False) as api:
        with pytest.raises(DataError, match="disabled"):
            api.fetch(QUERY)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404])
def test_errors_no_redirect_no_auth_retry_and_no_secret_leak(tmp_path: Path, status: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status, text=KEY + SECRET, headers={"Location": "https://api.alpaca.markets/v2/orders"}
        )

    with client(tmp_path, handler) as api, pytest.raises(DataError) as error:
        api.fetch(QUERY)
    assert len(calls) == 1
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert KEY not in str(error.value) and SECRET not in str(error.value)
    assert KEY.encode() not in (tmp_path / "data.sqlite").read_bytes()


def test_transport_exception_sanitized_and_retries_bounded(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout(KEY + SECRET, request=request)

    with client(tmp_path, handler) as api, pytest.raises(DataError) as error:
        api.fetch(QUERY)
    assert len(calls) == 3
    assert error.value.__context__ is None
    assert KEY not in repr(error.value) and SECRET not in repr(error.value)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retry_and_shared_rate_budget(tmp_path: Path, status: int) -> None:
    calls = []
    timer = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, headers={"Retry-After": "2"})
        return httpx.Response(200, json=page())

    with client(tmp_path, handler, clock=timer) as api:
        api.fetch(QUERY)
    assert timer.waits[0] >= (60 if status == 429 else 2)
    # A new client still shares the persisted request slot.
    with client(tmp_path, handler, clock=timer) as api:
        api.fetch(QUERY)
    assert timer.waits[-1] >= 1


def test_server_epoch_reset_and_long_cooldown_fail_closed(tmp_path: Path) -> None:
    timer = Clock()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(timer() + 600)}
        )

    with client(tmp_path, handler, clock=timer) as api, pytest.raises(DataError):
        api.fetch(QUERY)
    with client(tmp_path, handler, clock=timer) as api, pytest.raises(DataError):
        api.fetch(QUERY)
    assert len(calls) == 1 and not timer.waits


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "cycle",
        "malformed",
        "unexpected_symbol",
        "future",
        "bad_price",
        "secret_echo",
        "huge",
    ],
)
def test_invalid_payloads_fail_closed(tmp_path: Path, kind: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        result = page()
        if kind == "duplicate":
            result["bars"]["IBM"] *= 2
        if kind == "cycle":
            result = {"bars": {}, "next_page_token": "repeat"}
        if kind == "malformed":
            return httpx.Response(200, content=b"not JSON")
        if kind == "unexpected_symbol":
            result = page("UNREQUESTED")
        if kind == "future":
            result["bars"]["IBM"][0]["t"] = "2027-01-01T00:00:00Z"
        if kind == "bad_price":
            result["bars"]["IBM"][0]["o"] = "NaN"
        if kind == "secret_echo":
            result["debug"] = SECRET
        if kind == "huge":
            return httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))
        return httpx.Response(200, json=result)

    with client(tmp_path, handler) as api, pytest.raises(DataError):
        api.fetch(QUERY)
    assert len(calls) <= 2


def test_cross_page_duplicate_and_empty_success(tmp_path: Path) -> None:
    calls = []
    timer = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=page(token="next" if len(calls) == 1 else None))

    with client(tmp_path, handler, clock=timer) as api, pytest.raises(DataError):
        api.fetch(QUERY)
    with client(
        tmp_path,
        lambda request: httpx.Response(200, json={"bars": {}, "next_page_token": None}),
        clock=timer,
    ) as api:
        identity = api.fetch(QUERY)
    assert not load_download(
        Archive(tmp_path / "data.sqlite"), identity, "SPY", exchange="XNYS"
    ).bars


def test_split_semantics_and_session_classification(tmp_path: Path) -> None:
    query = BarsQuery(QUERY.symbols, QUERY.start, QUERY.end, "split")
    result = page()
    result["bars"]["IBM"] = [
        bar("2026-03-09T13:00:00Z"),
        bar("2026-03-09T14:00:00Z"),
        bar("2026-03-09T20:00:00Z"),
    ]
    with client(tmp_path, lambda request: httpx.Response(200, json=result)) as api:
        identity = api.fetch(query)
    data = load_download(Archive(tmp_path / "data.sqlite"), identity, "IBM", exchange="XNYS")
    assert data.basis == "split_adjusted" and not data.actions_complete
    assert "REPLAY_REQUIRES_RAW_PRICES" in blockers(data)
    assert session_counts(data, NYSE2026(verified_at=NOW)) == {
        "full_regular": 1,
        "boundary": 1,
        "outside_regular": 1,
    }


@pytest.mark.parametrize("adjustment", ["all", "dividend", "spin-off", "sip"])
def test_unsupported_adjustments_rejected(adjustment: str) -> None:
    with pytest.raises(ValueError):
        BarsQuery(QUERY.symbols, QUERY.start, QUERY.end, adjustment)


def test_incomplete_hours_block_before_network(tmp_path: Path) -> None:
    with client(tmp_path, lambda request: pytest.fail("Network called")) as api:
        with pytest.raises(DataError):
            api.fetch(BarsQuery(("IBM",), QUERY.start, NOW))


def test_json_escaped_secret_is_not_cached(tmp_path: Path) -> None:
    encoded = "".join(f"\\u{ord(c):04x}" for c in SECRET)
    raw = ('{"bars":{},"next_page_token":"' + encoded + '"}').encode()
    with client(tmp_path, lambda request: httpx.Response(200, content=raw)) as api:
        with pytest.raises(DataError):
            api.fetch(QUERY)
    assert encoded.encode() not in (tmp_path / "data.sqlite").read_bytes()


def test_saved_pages_and_manifest_are_revalidated(tmp_path: Path) -> None:
    import sqlite3

    with client(tmp_path, lambda request: httpx.Response(200, json=page())) as api:
        identity = api.fetch(QUERY)
    archive = Archive(tmp_path / "data.sqlite")
    manifest = json.loads(archive.get(identity)[0])
    with sqlite3.connect(archive.path) as db:
        db.execute("UPDATE snapshots SET raw=? WHERE id=?", (b"changed", manifest["pages"][0]))
    with pytest.raises(ValueError):
        load_download(archive, identity, "IBM", exchange="XNYS")


def test_offline_cli_does_not_load_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from etoro_demo_bot.alpaca.__main__ import main

    monkeypatch.setattr(
        Credentials, "from_environment", lambda: pytest.fail("Credentials accessed")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alpaca",
            "--symbols",
            "IBM",
            "--start",
            "2026-03-01T00:00:00Z",
            "--end",
            "2026-04-01T00:00:00Z",
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


@pytest.mark.parametrize("currency", ["EUR", "BTC"])
def test_response_currency_mismatch_blocked(tmp_path: Path, currency: str) -> None:
    result = page() | {"currency": currency}
    with client(tmp_path, lambda request: httpx.Response(200, json=result)) as api:
        with pytest.raises(DataError):
            api.fetch(QUERY)


def test_native_bars_are_not_shifted_to_make_backtest_pass(tmp_path: Path) -> None:
    from datetime import date

    from etoro_demo_bot.history.hourly import CoveragePolicy, StudyWindow, audit_hourly

    with client(tmp_path, lambda request: httpx.Response(200, json=page())) as api:
        identity = api.fetch(QUERY)
    data = load_download(Archive(tmp_path / "data.sqlite"), identity, "IBM", exchange="XNYS")
    at = data.bars[0].start
    assert at.hour == 14 and at.minute == 0
    window = StudyWindow(
        date(2026, 3, 6),
        date(2026, 3, 10),
        QUERY.start,
        datetime(2026, 3, 7, tzinfo=UTC),
        datetime(2026, 3, 9, tzinfo=UTC),
        QUERY.end,
    )
    result = audit_hourly(data, NYSE2026(verified_at=NOW), window, CoveragePolicy(), audit_at=NOW)
    assert {
        "OFF_GRID_OR_PARTIAL_CANDLE",
        "MISSING_HOURLY_CANDLES",
        "INSUFFICIENT_POINT_IN_TIME_WARMUP",
    } <= set(result.coverage_errors)


@pytest.mark.parametrize("eur", ["500", "1000"])
def test_both_portfolio_scenarios_require_verified_evidence(tmp_path: Path, eur: str) -> None:
    from datetime import date
    from decimal import Decimal

    from etoro_demo_bot.backtest.fixtures import synthetic_dataset
    from etoro_demo_bot.backtest.models import Plan, Simulation
    from etoro_demo_bot.history.hourly import CoveragePolicy, StudyWindow, run_hourly_study
    from etoro_demo_bot.strategy.models import Rules

    with client(tmp_path, lambda request: httpx.Response(200, json=page())) as api:
        identity = api.fetch(QUERY)
    data = load_download(Archive(tmp_path / "data.sqlite"), identity, "IBM", exchange="XNYS")
    window = StudyWindow(
        date(2026, 3, 6),
        date(2026, 3, 10),
        QUERY.start,
        datetime(2026, 3, 7, tzinfo=UTC),
        datetime(2026, 3, 9, tzinfo=UTC),
        QUERY.end,
    )
    with pytest.raises(ValueError, match="insufficient"):
        run_hourly_study(
            data,
            NYSE2026(verified_at=NOW),
            synthetic_dataset(1),
            Plan(Rules(), Simulation(initial_eur=Decimal(eur))),
            tmp_path / "run",
            window=window,
            policy=CoveragePolicy(),
            audit_at=NOW,
            review_reference="SYNTHETIC-MOCK-NOT-VERIFIED",
        )
    assert not (tmp_path / "run").exists()
