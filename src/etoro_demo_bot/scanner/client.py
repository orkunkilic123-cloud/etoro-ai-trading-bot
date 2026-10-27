"""Asynchronous analysis transport: exact metadata/quote/history/eligibility routes only."""

import asyncio
import json
import math
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

import httpx

from ..config import Credentials
from ..rate_limit import retry_delay
from .models import Candle, Eligibility, Instrument, Quote, ScanError
from .storage import ScanStore

ORIGIN = "https://public-api.etoro.com"
INSTRUMENTS = "/api/v2/market-data/instruments"
RATES = "/api/v2/market-data/rates"
ELIGIBILITY = "/api/v2/trading/info/demo/eligibility"
CANDLES = re.compile(r"/api/v1/market-data/instruments/[1-9][0-9]*/history/candles/asc/OneHour/100")


def number(value: object, *, zero: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ScanError("INVALID_NUMBER") from None
    if not result.is_finite() or result < 0 or not zero and result == 0 or result > Decimal("1e15"):
        raise ScanError("INVALID_NUMBER")
    return result


def timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is not None and result.utcoffset() is not None:
            return result.astimezone(UTC)
    except (ValueError, TypeError):
        pass
    raise ScanError("INVALID_TIMESTAMP")


def positive_id(value: Any) -> int:
    if type(value) is not int or not 0 < value <= 2147483647:
        raise ScanError("INVALID_INSTRUMENT_ID")
    return value


def rows(data: dict[str, Any], field: str) -> list[dict[str, Any]]:
    result = data.get(field)
    if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
        raise ScanError("INVALID_RESPONSE_SCHEMA")
    return result


def parse_eligibility(data: dict[str, Any], now: datetime) -> dict[int, Eligibility]:
    if data.get("currency") != "USD":
        raise ScanError("UNKNOWN_ELIGIBILITY_CURRENCY")
    result: dict[int, Eligibility] = {}
    seen: set[int] = set()
    for item in rows(data, "eligibilities"):
        iid = positive_id(item.get("instrumentId"))
        if iid in seen:
            raise ScanError("DUPLICATE_INSTRUMENT")
        seen.add(iid)
        configs = [
            x
            for x in rows(item, "leverageConfigs")
            if x.get("settlementType") == "real"
            and x.get("direction") == "long"
            and x.get("isPotential") is False
            and isinstance(x.get("leverageValues"), list)
            and any(type(v) is int and v == 1 for v in x["leverageValues"])
        ]
        if (
            len(configs) != 1
            or item.get("allowOpenPosition") is not True
            or item.get("tradeUnitType") != "units"
            or item.get("allowedOrderQuantityType") not in ("unitsOnly", "all")
            or item.get("unitsQuantityType") not in ("whole", "fractional")
            or item.get("additionalBufferPercent") not in (None, 0)
            or isinstance(item.get("additionalBufferPercent"), bool)
        ):
            continue
        result[iid] = Eligibility(
            iid,
            max(
                number(item.get("minPositionExposure")), number(configs[0].get("minPositionAmount"))
            ),
            number(item.get("maxUnitsPerOrder")),
            item["unitsQuantityType"] == "fractional",
            now,
            True,
        )
    missing = data.get("notFoundInstrumentIds", [])
    if not isinstance(missing, list) or any(type(i) is not int or i in seen for i in missing):
        raise ScanError("CONTRADICTORY_ELIGIBILITY")
    return result


class MarketClient:
    def __init__(
        self,
        credentials: Credentials,
        store: ScanStore,
        *,
        network_enabled: bool = False,
        free_access_confirmed: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_pages: int = 20,
    ) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 100:
            raise ScanError("INVALID_PAGE_LIMIT")
        self._credentials = credentials
        self._enabled = network_enabled is True and free_access_confirmed is True
        self.store, self.clock, self.sleep = store, clock, sleep
        self.max_pages = max_pages
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            transport=transport, follow_redirects=False, timeout=httpx.Timeout(15, connect=5)
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        cache_ttl: int = 0,
    ) -> dict[str, Any]:
        allowed = method == "GET" and (path in {INSTRUMENTS, RATES} or CANDLES.fullmatch(path))
        if not allowed and not (method == "POST" and path == ELIGIBILITY):
            raise ScanError("ENDPOINT_BLOCKED")
        if (
            not self._enabled
            or self._credentials.environment != "demo"
            or self._credentials.demo_key_confirmed is not True
        ):
            raise ScanError("NETWORK_DISABLED_OR_DEMO_UNCONFIRMED")
        # Query values never control destination, method, or route.
        key = "schema1:" + path + json.dumps(params or {}, sort_keys=True)
        async with self._lock:
            try:
                if cache_ttl and method == "GET":
                    cached = self.store.get(key, self.clock())
                    if cached is not None:
                        return cached
                group, spacing = ("eligibility", 3.1) if path == ELIGIBILITY else ("market", 1.1)
                while delay := self.store.claim(group, self.clock(), spacing):
                    if delay > 300:
                        raise ScanError("QUOTA_COOLDOWN")
                    await self.sleep(delay)
                response = await self._http.request(
                    method,
                    ORIGIN + path,
                    params=params,
                    json=body,
                    headers={
                        "x-api-key": self._credentials.api_key,
                        "x-user-key": self._credentials.user_key,
                        "x-request-id": str(uuid4()),
                        "Accept": "application/json",
                    },
                )
                delay = retry_delay(response.headers.get("Retry-After"))
                reset = retry_delay(response.headers.get("RateLimit-Reset"))
                remaining = response.headers.get("RateLimit-Remaining")
                limit = response.headers.get("RateLimit-Limit")
                if limit and limit.isdecimal() and int(limit) > 0:
                    spacing = max(spacing, 60 / int(limit) + 0.1)
                if remaining and remaining.isdecimal():
                    if int(remaining) == 0:
                        delay = max(delay, reset or 60)
                    elif reset:
                        spacing = max(spacing, reset / int(remaining) + 0.1)
                if response.status_code == 429:
                    delay = max(delay, reset, 60)
                self.store.cooldown(group, self.clock(), max(delay, spacing), spacing)
                if response.status_code != 200 and not (
                    path == RATES and response.status_code == 206
                ):
                    raise ScanError("API_READ_FAILED")
                data = json.loads(response.content)
                await response.aclose()
                if not isinstance(data, dict):
                    raise ScanError("INVALID_RESPONSE_SCHEMA")
                if cache_ttl and method == "GET":
                    self.store.put(key, data, self.clock(), cache_ttl)
                return data
            except ScanError:
                raise
            except (httpx.HTTPError, ValueError, TypeError, sqlite3.Error, OSError):
                pass
        # Raise outside except: upstream requests/credentials never retained as context.
        raise ScanError("DATA_SOURCE_UNAVAILABLE")

    async def discover(self) -> tuple[Instrument, ...]:
        instruments: dict[int, Instrument] = {}
        for kind in ("Stocks", "ETF"):
            token: str | None = None
            seen: set[str] = set()
            for _ in range(self.max_pages):
                params = {"type": kind, "pageSize": "100"}
                if token is not None:
                    params["pageToken"] = token
                data = await self._request("GET", INSTRUMENTS, params=params, cache_ttl=3600)
                for item in rows(data, "results"):
                    iid = positive_id(item.get("instrumentId"))
                    if (
                        item.get("type") != kind
                        or not isinstance(item.get("symbol"), str)
                        or not item["symbol"]
                        or item.get("expirationDateTime") is not None
                        or item.get("multiplier") not in (None, 1)
                    ):
                        continue
                    if iid in instruments:
                        raise ScanError("DUPLICATE_INSTRUMENT")
                    instruments[iid] = Instrument(
                        iid, item["symbol"], kind, positive_id(item.get("exchangeId"))
                    )
                pagination = data.get("pagination")
                if not isinstance(pagination, dict) or type(pagination.get("hasNext")) is not bool:
                    raise ScanError("INVALID_PAGINATION")
                if not pagination["hasNext"]:
                    break
                token = pagination.get("nextPageToken")
                if not isinstance(token, str) or not token or token in seen:
                    raise ScanError("INVALID_PAGINATION")
                seen.add(token)
            else:
                raise ScanError("DISCOVERY_LIMIT_REACHED")
        return tuple(instruments[i] for i in sorted(instruments))

    async def quotes(self, ids: tuple[int, ...]) -> dict[int, Quote]:
        ids = tuple(sorted({positive_id(x) for x in ids}))
        result: dict[int, Quote] = {}
        for start in range(0, len(ids), 1000):
            batch = ids[start : start + 1000]
            data = await self._request(
                "GET", RATES, params={"instrumentIds": ",".join(map(str, batch))}
            )
            for item in rows(data, "results"):
                iid = positive_id(item.get("instrumentId"))
                if iid not in batch or iid in result:
                    raise ScanError("UNEXPECTED_INSTRUMENT")
                try:
                    bid, ask = number(item.get("bid")), number(item.get("ask"))
                    date = timestamp(item.get("date"))
                    if ask < bid or item.get("quoteType") not in ("realtime", "delayed"):
                        continue
                    result[iid] = Quote(iid, bid, ask, date, item["quoteType"])
                except ScanError:
                    continue
        return result

    async def history(self, instrument_id: int) -> tuple[Candle, ...]:
        iid = positive_id(instrument_id)
        path = f"/api/v1/market-data/instruments/{iid}/history/candles/asc/OneHour/100"
        data = await self._request("GET", path, cache_ttl=60)
        groups = rows(data, "candles")
        if (
            data.get("interval") != "OneHour"
            or len(groups) != 1
            or groups[0].get("instrumentId") != iid
        ):
            raise ScanError("INVALID_HISTORY")
        result: list[Candle] = []
        for item in rows(groups[0], "candles"):
            if item.get("instrumentID") != iid:
                raise ScanError("INVALID_HISTORY")
            prices = [float(number(item.get(k))) for k in ("open", "high", "low", "close")]
            volume = (
                None if item.get("volume") is None else float(number(item["volume"], zero=True))
            )
            if not all(math.isfinite(v) for v in prices):
                raise ScanError("INVALID_HISTORY")
            result.append(
                Candle(
                    timestamp(item.get("fromDate")),
                    prices[0],
                    prices[1],
                    prices[2],
                    prices[3],
                    volume,
                )
            )
        return tuple(result)

    async def eligibility(self, ids: tuple[int, ...]) -> dict[int, Eligibility]:
        ids = tuple(sorted({positive_id(x) for x in ids}))
        result: dict[int, Eligibility] = {}
        for start in range(0, len(ids), 100):
            batch = ids[start : start + 100]
            data = await self._request(
                "POST", ELIGIBILITY, body={"instrumentIds": list(batch), "currency": "USD"}
            )
            parsed = parse_eligibility(data, datetime.fromtimestamp(self.clock(), UTC))
            if any(i not in batch or i in result for i in parsed):
                raise ScanError("UNEXPECTED_INSTRUMENT")
            result.update(parsed)
        return result
