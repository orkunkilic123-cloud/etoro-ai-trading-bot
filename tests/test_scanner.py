"""Offline scanner contracts and independently checkable numerical examples."""

import asyncio
import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from etoro_demo_bot.config import Credentials
from etoro_demo_bot.scanner import (
    Budget,
    CachedEarnings,
    MarketClient,
    ScanError,
    Scanner,
    ScanPolicy,
    ScanStore,
    ScoringRules,
)
from etoro_demo_bot.scanner.client import ELIGIBILITY, RATES, parse_eligibility
from etoro_demo_bot.scanner.indicators import calculate, ema_series, sma
from etoro_demo_bot.scanner.models import (
    Candle,
    Eligibility,
    Features,
    FundamentalAnalysis,
    Instrument,
    ProductEvidence,
    Quote,
    SessionEvidence,
)

NOW = datetime(2026, 10, 27, 15, 30, tzinfo=UTC)
KEYS = Credentials("synthetic-api-key", "synthetic-user-key", "demo", True)


def bars(values: tuple[float, ...] | None = None) -> tuple[Candle, ...]:
    values = values or tuple(100 + i * i * 0.01 for i in range(60))
    return tuple(
        Candle(
            NOW - timedelta(hours=len(values) - i + 1),
            v,
            v + 0.2,
            v - 0.2,
            v,
            300 if i == len(values) - 1 else 100,
        )
        for i, v in enumerate(values)
    )


def budget(eur: str = "500") -> Budget:
    return Budget(D(eur), D("1.10"), NOW, "synthetic-fx", D(".005"), D("0.1"), D(".001"), D(".001"))


def eligible(iid: int = 1) -> Eligibility:
    return Eligibility(iid, D("10"), D("10000"), True, NOW, True)


def quote(iid: int = 1) -> Quote:
    return Quote(iid, D("134.80"), D("134.81"), NOW, "realtime")


def eligibility_json(ids: list[int]) -> dict[str, Any]:
    return {
        "currency": "USD",
        "eligibilities": [
            {
                "instrumentId": iid,
                "minPositionExposure": 10,
                "maxUnitsPerOrder": 1000,
                "allowOpenPosition": True,
                "tradeUnitType": "units",
                "unitsQuantityType": "fractional",
                "allowedOrderQuantityType": "all",
                "additionalBufferPercent": None,
                "leverageConfigs": [
                    {
                        "settlementType": "real",
                        "direction": "long",
                        "leverageValues": [1],
                        "isPotential": False,
                        "minPositionAmount": 10,
                    }
                ],
            }
            for iid in ids
        ],
    }


class Clock:
    def __init__(self) -> None:
        self.value = NOW.timestamp()
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.value

    async def sleep(self, delay: float) -> None:
        self.waits.append(delay)
        self.value += delay


class Evidence:
    def __init__(self) -> None:
        self.product_value = ProductEvidence(
            1, "USD", True, True, "synthetic-review", NOW + timedelta(days=1)
        )
        self.session_value = SessionEvidence(
            1, True, NOW, NOW + timedelta(hours=1), "synthetic-calendar"
        )
        self.complete = True

    async def product(self, instrument: Instrument, now: datetime) -> ProductEvidence:
        return replace(self.product_value, instrument_id=instrument.instrument_id)

    async def session(self, instrument: Instrument, now: datetime) -> SessionEvidence:
        return replace(self.session_value, instrument_id=instrument.instrument_id)

    async def history_complete(
        self, instrument: Instrument, candles: tuple[Candle, ...], now: datetime
    ) -> bool:
        return self.complete


class Source:
    def __init__(self) -> None:
        self.instruments: tuple[Instrument, ...] = (Instrument(1, "SYNTH", "Stocks", 1),)
        self.q = {1: quote()}
        self.e = {1: eligible()}
        self.h = bars()
        self.calls = 0

    async def discover(self) -> tuple[Instrument, ...]:
        self.calls += 1
        return self.instruments

    async def quotes(self, ids: tuple[int, ...]) -> dict[int, Quote]:
        return self.q

    async def eligibility(self, ids: tuple[int, ...]) -> dict[int, Eligibility]:
        return self.e

    async def history(self, instrument_id: int) -> tuple[Candle, ...]:
        return self.h


def scan(source: Source | None = None, evidence: Evidence | None = None) -> Any:
    scanner = Scanner(source or Source(), evidence or Evidence(), budget(), clock=lambda: NOW)
    return asyncio.run(scanner.run_due())


def test_indicators_flat_and_linear() -> None:
    flat = calculate(bars((100.0,) * 60))
    assert flat.sma == flat.ema == 100
    assert flat.rsi == 50
    assert flat.macd == flat.macd_signal == flat.momentum == flat.volatility == 0
    assert flat.atr == pytest.approx(0.4)
    assert flat.relative_volume == 3
    values = tuple(float(x) for x in range(1, 61))
    linear = calculate(bars(values))
    assert linear.sma == 50.5
    assert linear.ema == pytest.approx(50.5)
    assert linear.rsi == 100
    assert linear.macd == pytest.approx(7)
    assert linear.macd_signal == pytest.approx(7)
    assert linear.atr == pytest.approx(1.2)
    assert linear.momentum == pytest.approx(0.2)
    assert calculate(bars(tuple(reversed(values)))).rsi == 0
    assert ema_series((1.0, 2.0, 3.0, 4.0, 5.0), 3) == (2.0, 3.0, 4.0)
    assert sma((1.0, 2.0, 3.0, 4.0), 3) == 3


def test_rsi_wilder_reference() -> None:
    # Wilder's first 14 changes: gains 3.34/14, losses 1.40/14 -> RSI 70.464135.
    values = (
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
    )
    padded = values + (46.28,) * 25
    assert calculate(bars(padded)).rsi == pytest.approx(70.4641350211)


@pytest.mark.parametrize(
    "change", ["nan", "negative", "high", "order", "naive", "overlap", "volume"]
)
def test_bad_history_rejected(change: str) -> None:
    data = list(bars())
    if change == "nan":
        data[1] = replace(data[1], close=math.nan)
    if change == "negative":
        data[1] = replace(data[1], low=-1)
    if change == "high":
        data[1] = replace(data[1], high=1)
    if change == "order":
        data.reverse()
    if change == "naive":
        data[1] = replace(data[1], start=data[1].start.replace(tzinfo=None))
    if change == "overlap":
        data[1] = replace(data[1], start=data[0].start)
    if change == "volume":
        data[1] = replace(data[1], volume=-1)
    with pytest.raises(ScanError):
        calculate(tuple(data))


def test_volume_missing_zero_and_warmup() -> None:
    for volume in (None, 0):
        assert calculate(tuple(replace(b, volume=volume) for b in bars())).relative_volume is None
    with pytest.raises(ScanError, match="INSUFFICIENT_HISTORY"):
        calculate(bars()[:34])


@pytest.mark.parametrize("eur", ["500", "1000"])
def test_small_eur_budget_costs_and_fractional(eur: str) -> None:
    cash, total = budget(eur).minimum_cash(eligible(), quote(), NOW)
    assert total == D(eur) * D("1.1") * D(".995")
    assert D("10") < cash < D("10.2")
    if eur == "500":
        with pytest.raises(ScanError, match="UNAFFORDABLE"):
            budget(eur).minimum_cash(replace(eligible(), fractional=False), quote(), NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("usd_per_eur", D("NaN")),
        ("equity_eur", D("-1")),
        ("conversion_cost_fraction", D("1")),
        ("fx_source", ""),
        ("fx_observed_at", NOW - timedelta(seconds=61)),
        ("round_trip_fixed_usd", D("-1")),
    ],
)
def test_invalid_budget(field: str, value: Any) -> None:
    with pytest.raises(ScanError):
        replace(budget(), **{field: value}).minimum_cash(eligible(), quote(), NOW)


def test_cost_and_size_rejections() -> None:
    with pytest.raises(ScanError, match="COSTS_TOO_HIGH"):
        replace(budget(), round_trip_fixed_usd=D("5")).minimum_cash(eligible(), quote(), NOW)
    with pytest.raises(ScanError, match="MAX_UNITS"):
        budget().minimum_cash(replace(eligible(), max_units=D(".001")), quote(), NOW)


def test_scoring_rules_are_explainable() -> None:
    f = Features(100, 101, 60, 2, 1, 1, 3, 0.01, 0.03, 104, 105)
    parts = ScoringRules().rank(f)
    assert parts == (("momentum_breakout", 35), ("trend_continuation", 30), ("unusual_volume", 20))
    assert sum(x[1] for x in parts) == 85
    assert ScoringRules().rank(
        replace(f, close=90, rsi=20, momentum=-0.1, relative_volume=None)
    ) == (("potential_mean_reversion", 15),)
    assert ScoringRules(breakout_weight=10).rank(f)[0][1] == 10
    with pytest.raises(ScanError):
        ScoringRules(volume_threshold=1)
    with pytest.raises(ScanError):
        ScoringRules(breakout_weight=200)
    with pytest.raises(ScanError):
        ScoringRules().rank(replace(f, volatility=0.2))


def test_scan_success_expiry_no_execution() -> None:
    result = scan()
    assert len(result.opportunities) == 1 and result.rejected == ()
    opportunity = result.opportunities[0]
    assert opportunity.score >= 55
    assert not opportunity.execution_authorized
    assert opportunity.valid_at(NOW)
    assert not opportunity.valid_at(NOW + timedelta(seconds=60))
    assert not opportunity.valid_at(NOW - timedelta(seconds=1))


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "delayed",
        "stale",
        "future",
        "inverted",
        "nan",
        "eligibility",
        "eligibility_stale",
    ],
)
def test_scan_missing_stale_or_invalid_data(case: str) -> None:
    source = Source()
    if case == "missing":
        source.q = {}
    if case == "delayed":
        source.q[1] = replace(quote(), quote_type="delayed")
    if case == "stale":
        source.q[1] = replace(quote(), observed_at=NOW - timedelta(seconds=61))
    if case == "future":
        source.q[1] = replace(quote(), observed_at=NOW + timedelta(seconds=1))
    if case == "inverted":
        source.q[1] = replace(quote(), bid=D("500"))
    if case == "nan":
        source.q[1] = replace(quote(), ask=D("NaN"))
    if case == "eligibility":
        source.e = {}
    if case == "eligibility_stale":
        source.e[1] = replace(eligible(), observed_at=NOW - timedelta(seconds=61))
    result = scan(source)
    assert not result.opportunities and len(result.rejected) == 1


@pytest.mark.parametrize(
    "case", ["closed", "unknown", "expired", "leveraged", "currency", "underlying", "history_gaps"]
)
def test_scan_safety_evidence(case: str) -> None:
    e = Evidence()
    if case == "closed":
        e.session_value = replace(e.session_value, is_open=False)
    if case == "unknown":
        e.session_value = replace(e.session_value, source="")
    if case == "expired":
        e.session_value = replace(e.session_value, valid_until=NOW)
    if case == "leveraged":
        e.product_value = replace(e.product_value, unleveraged=False)
    if case == "currency":
        e.product_value = replace(e.product_value, currency="EUR")
    if case == "underlying":
        e.product_value = replace(e.product_value, underlying=False)
    if case == "history_gaps":
        e.complete = False
    assert not scan(evidence=e).opportunities


def test_timezone_and_forming_candle() -> None:
    source = Source()
    source.q[1] = replace(quote(), observed_at=NOW.astimezone(timezone(timedelta(hours=-4))))
    source.h += (Candle(NOW, 1, 1, 1, 1, 999999),)
    assert scan(source).opportunities[0].features == calculate(bars())


def test_schedule_serializes_without_trade_quota() -> None:
    async def scenario() -> None:
        source = Source()
        scanner = Scanner(source, Evidence(), budget(), clock=lambda: NOW)
        results = await asyncio.gather(scanner.run_due(), scanner.run_due())
        assert results[0] is not None and results[1] is None and source.calls == 1
        scanner.clock = lambda: NOW - timedelta(seconds=1)
        with pytest.raises(ScanError, match="CLOCK"):
            await scanner.run_due()

    asyncio.run(scenario())
    with pytest.raises(ScanError):
        ScanPolicy(schedule_seconds=0)


def test_store_restart_expiry_and_quota(tmp_path: Path) -> None:
    path = tmp_path / "scan.sqlite"
    store = ScanStore(path)
    store.put("history", {"data": 1}, 100, 30)
    assert ScanStore(path).get("history", 129) == {"data": 1}
    assert store.get("history", 130) is None and store.get("history", 99) is None
    assert store.claim("market", 100, 1.1) == 0
    assert ScanStore(path).claim("market", 100, 1.1) == pytest.approx(1.1)
    store.cooldown("market", 100, 60, 1.1)
    assert ScanStore(path).claim("market", 101, 1.1) == 59
    with pytest.raises(ScanError, match="ROLLBACK"):
        store.claim("market", 99, 1.1)


def make_client(
    tmp_path: Path, handler: Any, clock: Clock, *, enabled: bool = True
) -> MarketClient:
    return MarketClient(
        KEYS,
        ScanStore(tmp_path / "data.sqlite"),
        network_enabled=enabled,
        free_access_confirmed=enabled,
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )


def test_batched_quotes_partial_and_headers(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "public-api.etoro.com"
        assert request.url.path == RATES and request.headers["x-api-key"] == KEYS.api_key
        assert UUID(request.headers["x-request-id"]).version == 4
        ids = [int(x) for x in request.url.params["instrumentIds"].split(",")]
        calls.append(len(ids))
        return httpx.Response(
            206,
            json={
                "results": [
                    {
                        "instrumentId": ids[0],
                        "bid": 100,
                        "ask": 101,
                        "date": NOW.isoformat(),
                        "quoteType": "realtime",
                    }
                ]
            },
        )

    async def scenario() -> None:
        clock = Clock()
        client = make_client(tmp_path, handler, clock)
        result = await client.quotes(tuple(range(1, 1002)))
        assert set(result) == {1, 1001} and calls == [1000, 1]
        assert sum(clock.waits) == pytest.approx(1.1)
        await client.close()

    asyncio.run(scenario())


def test_discovery_pagination_and_cache(tmp_path: Path) -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        iid = 3 if params["type"] == "ETF" else 2 if "pageToken" in params else 1
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "instrumentId": iid,
                        "symbol": f"SYN{iid}",
                        "type": params["type"],
                        "exchangeId": 1,
                    }
                ],
                "pagination": {
                    "hasNext": iid == 1,
                    "nextPageToken": "cursor" if iid == 1 else None,
                },
            },
        )

    async def scenario() -> None:
        clock = Clock()
        client = make_client(tmp_path, handler, clock)
        assert [x.instrument_id for x in await client.discover()] == [1, 2, 3]
        await client.discover()
        assert len(calls) == 3 and calls[1]["pageToken"] == "cursor"
        await client.close()
        # Cache works across process/client restart, without caching account eligibility.
        client = make_client(tmp_path, handler, clock)
        await client.discover()
        assert len(calls) == 3
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["cycle", "missing", "limit", "duplicate"])
def test_bad_discovery_pagination(tmp_path: Path, case: str) -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "instrumentId": 1 if case == "duplicate" else count,
                        "symbol": "S",
                        "type": "Stocks",
                        "exchangeId": 1,
                    }
                ],
                "pagination": {
                    "hasNext": True,
                    "nextPageToken": None
                    if case == "missing"
                    else str(count)
                    if case in {"limit", "duplicate"}
                    else "repeated",
                },
            },
        )

    async def scenario() -> None:
        client = make_client(tmp_path, handler, Clock())
        client.max_pages = 3
        with pytest.raises(ScanError):
            await client.discover()
        assert count <= 3
        await client.close()

    asyncio.run(scenario())


def test_history_official_schema_and_cache(tmp_path: Path) -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        assert request.url.path.endswith("/1/history/candles/asc/OneHour/100")
        return httpx.Response(
            200,
            json={
                "interval": "OneHour",
                "candles": [
                    {
                        "instrumentId": 1,
                        "candles": [
                            {
                                "instrumentID": 1,
                                "fromDate": b.start.isoformat(),
                                "open": b.open,
                                "high": b.high,
                                "low": b.low,
                                "close": b.close,
                                "volume": b.volume,
                            }
                            for b in bars()
                        ],
                    }
                ],
            },
        )

    async def scenario() -> None:
        clock = Clock()
        client = make_client(tmp_path, handler, clock)
        assert await client.history(1) == bars()
        assert await client.history(1) == bars() and count == 1
        clock.value += 60
        await client.history(1)
        assert count == 2
        await client.close()

    asyncio.run(scenario())


def test_eligibility_batching_and_quota(tmp_path: Path) -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == ELIGIBILITY
        body = json.loads(request.content)
        assert body["currency"] == "USD" and set(body) == {"instrumentIds", "currency"}
        sizes.append(len(body["instrumentIds"]))
        return httpx.Response(200, json=eligibility_json(body["instrumentIds"]))

    async def scenario() -> None:
        clock = Clock()
        client = make_client(tmp_path, handler, clock)
        assert len(await client.eligibility(tuple(range(1, 102)))) == 101
        assert sizes == [100, 1] and sum(clock.waits) == pytest.approx(3.1)
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowOpenPosition", False),
        ("tradeUnitType", "contracts"),
        ("unitsQuantityType", "unknown"),
        ("allowedOrderQuantityType", "amountOnly"),
        ("additionalBufferPercent", 1),
    ],
)
def test_eligibility_fail_closed(field: str, value: Any) -> None:
    data = eligibility_json([1])
    data["eligibilities"][0][field] = value
    assert parse_eligibility(data, NOW) == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("settlementType", "cfd"),
        ("direction", "short"),
        ("isPotential", True),
        ("leverageValues", [2]),
        ("leverageValues", [True]),
    ],
)
def test_underlying_config_required(field: str, value: Any) -> None:
    data = eligibility_json([1])
    data["eligibilities"][0]["leverageConfigs"][0][field] = value
    assert parse_eligibility(data, NOW) == {}


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v3/trading/execution/demo/orders"),
        ("POST", "/api/v3/trading/execution/real/orders"),
        ("GET", "/api/v1/trading/info/real/portfolio"),
        ("GET", RATES + "/"),
        ("GET", RATES + "?instrumentIds=1"),
        ("GET", "https://evil.test" + RATES),
        ("GET", "/api/v1/market-data/instruments/../history/candles/asc/OneHour/100"),
        ("DELETE", ELIGIBILITY),
        ("GET", "/api/v2/trading/info/real/eligibility"),
    ],
)
def test_exact_allowlist_blocks_orders_and_real(tmp_path: Path, method: str, path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Blocked endpoint reached transport")

    async def scenario() -> None:
        client = make_client(tmp_path, handler, Clock())
        with pytest.raises(ScanError, match="ENDPOINT_BLOCKED"):
            await client._request(method, path)
        await client.close()

    asyncio.run(scenario())


def test_disabled_network_default(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = make_client(
            tmp_path, lambda r: pytest.fail("network enabled"), Clock(), enabled=False
        )
        with pytest.raises(ScanError, match="DISABLED"):
            await client.quotes((1,))
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_api_errors_sanitized_and_no_blind_retries(tmp_path: Path, status: int) -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(status, text="synthetic-user-key", headers={"Retry-After": "120"})

    async def scenario() -> None:
        clock = Clock()
        client = make_client(tmp_path, handler, clock)
        with pytest.raises(ScanError) as error:
            await client.quotes((1,))
        assert "synthetic" not in str(error.value) and count == 1
        assert client.store.claim("market", clock(), 1.1) >= 120
        await client.close()

    asyncio.run(scenario())


def test_timeouts_are_sanitized(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic-user-key", request=request)

    async def scenario() -> None:
        client = make_client(tmp_path, handler, Clock())
        with pytest.raises(ScanError) as error:
            await client.quotes((1,))
        assert str(error.value) == "DATA_SOURCE_UNAVAILABLE" and error.value.__context__ is None
        await client.close()

    asyncio.run(scenario())


def test_shared_market_quota_and_runtime_lower_limit(tmp_path: Path) -> None:
    times: list[float] = []
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        return httpx.Response(200, json={"results": []}, headers={"RateLimit-Limit": "10"})

    async def scenario() -> None:
        first = make_client(tmp_path, handler, clock)
        second = make_client(tmp_path, handler, clock)
        await first.quotes((1,))
        await second.quotes((2,))
        assert times[1] - times[0] == pytest.approx(6.1)
        await first.close()
        await second.close()

    asyncio.run(scenario())


def test_quota_rolling_window(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "quota.sqlite")
    now = 100.0
    sent = []
    for _ in range(120):
        delay = store.claim("market", now, 1.1)
        if delay:
            now += delay
            assert store.claim("market", now, 1.1) == 0
        sent.append(now)
    assert max(sum(t - 60 < x <= t for x in sent) for t in sent) <= 55


def test_fundamental_cache_version_expiry_restart(tmp_path: Path) -> None:
    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        async def analysis(self, instrument_id: int, now: datetime) -> FundamentalAnalysis:
            self.calls += 1
            return FundamentalAnalysis(
                instrument_id,
                "v1",
                "synthetic-filings",
                now,
                now + timedelta(hours=1),
                (("revenue", "100"),),
            )

    async def scenario() -> None:
        provider = Provider()
        path = tmp_path / "facts.sqlite"
        cache = CachedEarnings(provider, ScanStore(path), version="v1")
        first = await cache.analysis(1, NOW)
        assert first == await CachedEarnings(provider, ScanStore(path), version="v1").analysis(
            1, NOW
        )
        assert provider.calls == 1
        await cache.analysis(1, NOW + timedelta(hours=1))
        assert provider.calls == 2
        with pytest.raises(ScanError, match="FUNDAMENTALS"):
            await CachedEarnings(provider, ScanStore(path), version="v2").analysis(1, NOW)

    asyncio.run(scenario())


def test_watchlist_limits_and_missing_ids() -> None:
    async def scenario() -> None:
        source = Source()
        source.instruments += (Instrument(2, "OTHER", "ETF", 1),)
        scanner = Scanner(
            source,
            Evidence(),
            budget(),
            policy=ScanPolicy(watchlist=(1,), max_instruments=1),
            clock=lambda: NOW,
        )
        result = await scanner.run_due()
        assert result is not None and result.discovered == 2 and len(result.opportunities) == 1
        for policy in (ScanPolicy(max_instruments=1), ScanPolicy(watchlist=(999,))):
            with pytest.raises(ScanError):
                await Scanner(
                    source, Evidence(), budget(), policy=policy, clock=lambda: NOW
                ).run_due()

    asyncio.run(scenario())


def test_indicator_analysis_cached_until_history_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from etoro_demo_bot.scanner import engine

    calls = 0

    def tracked(history: tuple[Candle, ...]) -> Features:
        nonlocal calls
        calls += 1
        return calculate(history)

    monkeypatch.setattr(engine, "calculate", tracked)

    async def scenario() -> None:
        source = Source()
        evidence = Evidence()
        clock = [NOW]
        scanner = Scanner(
            source,
            evidence,
            budget(),
            policy=ScanPolicy(schedule_seconds=1),
            clock=lambda: clock[0],
        )
        await scanner.run_due()
        clock[0] += timedelta(seconds=1)
        await scanner.run_due()
        assert calls == 1
        source.h = source.h[:-1] + (replace(source.h[-1], volume=400),)
        clock[0] += timedelta(seconds=1)
        await scanner.run_due()
        assert calls == 2

    asyncio.run(scenario())


def test_earnings_latency_expires_opportunity() -> None:
    clock = [NOW]

    class SlowEarnings:
        async def analysis(self, instrument_id: int, now: datetime) -> FundamentalAnalysis | None:
            clock[0] += timedelta(seconds=61)
            return None

    async def scenario() -> None:
        scanner = Scanner(
            Source(), Evidence(), budget(), earnings=SlowEarnings(), clock=lambda: clock[0]
        )
        result = await scanner.run_due()
        assert result is not None and not result.opportunities
        assert result.rejected == ((1, "OPPORTUNITY_EXPIRED"),)

    asyncio.run(scenario())


def test_async_quota_no_duplicate_slot(tmp_path: Path) -> None:
    clock = Clock()
    times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        return httpx.Response(200, json={"results": []})

    async def scenario() -> None:
        clients = [make_client(tmp_path, handler, clock) for _ in range(3)]
        await asyncio.gather(*(client.quotes((1,)) for client in clients))
        assert len(times) == 3
        assert all(b - a > 1 for a, b in zip(times, times[1:], strict=False))
        for client in clients:
            await client.close()

    asyncio.run(scenario())


def test_corrupt_cache_fails_closed(tmp_path: Path) -> None:
    import sqlite3

    async def scenario() -> None:
        client = make_client(tmp_path, lambda r: pytest.fail("cache failure must block"), Clock())
        with sqlite3.connect(tmp_path / "data.sqlite") as db:
            db.execute("DROP TABLE scan_cache")
        with pytest.raises(ScanError, match="UNAVAILABLE"):
            await client.discover()
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "content,code",
    [
        (b"not json", "DATA_SOURCE_UNAVAILABLE"),
        (b"[]", "INVALID_RESPONSE_SCHEMA"),
        (b'{"results":[{"instrumentId":999}]}', "UNEXPECTED_INSTRUMENT"),
    ],
)
def test_unknown_quote_and_bad_json(tmp_path: Path, content: bytes, code: str) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=content)

        client = make_client(tmp_path, handler, Clock())
        with pytest.raises(ScanError, match=code):
            await client.quotes((1,))
        await client.close()

    asyncio.run(scenario())
