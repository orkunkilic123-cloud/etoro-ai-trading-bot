"""Exact one-route GET client. IEX only; explicit opt-in; no accounts or trading APIs."""

import hashlib
import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import TracebackType

import httpx

from ..history.alpaca import archive_research_pages, decode_page, load_download
from ..history.archive import Archive
from ..history.models import Source
from ..rate_limit import retry_delay
from ..scanner.models import ScanError
from ..scanner.storage import ScanStore
from ..timeframes import Timeframe
from .config import Credentials, DataError
from .contracts import BARS, ORIGIN, TERMS, BarsQuery
from .network import http_client


class MarketDataClient:
    def __init__(
        self,
        credentials: Credentials,
        archive: Archive,
        *,
        enabled: bool = False,
        request_limit: int = 300,
        allow_five_minute: bool = False,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if type(request_limit) is not int or not 1 <= request_limit <= 300:
            raise DataError("Market-data request budget must be between 1 and 300.")
        self._allow_five_minute = allow_five_minute is True
        self._remaining_requests = request_limit
        self._credentials, self._archive, self._enabled = credentials, archive, enabled is True
        self._clock, self._sleep = clock, sleep
        self._quota = ScanStore(archive.path)
        self._lock = threading.Lock()
        self._http = http_client(transport)

    def __enter__(self) -> "MarketDataClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _wait(self) -> None:
        # Shared across all clients/processes using this archive, including retries.
        for _ in range(100):
            delay = self._quota.claim("alpaca-iex-bars", self._clock(), 1.0)
            if delay == 0:
                return
            if not math.isfinite(delay) or delay > 60:
                raise DataError("Market-data cooldown exceeds automatic wait budget.")
            self._sleep(delay)
        raise DataError("Market-data quota contention; try later.")

    def _cooldown(self, delay: float) -> None:
        self._quota.cooldown("alpaca-iex-bars", self._clock(), delay, 1.0)

    def _page(self, query: BarsQuery, token: str | None) -> tuple[bytes, Source]:
        params = query.params()
        if token is not None:
            params["page_token"] = token
        for attempt in range(3):
            failed = False
            raw = b""
            status = 0
            headers = httpx.Headers()
            url = ""
            try:
                if self._remaining_requests == 0:
                    raise DataError("Market-data request budget exhausted; no further GET allowed.")
                self._wait()
                self._remaining_requests -= 1
                with self._http.stream(
                    "GET",
                    ORIGIN + BARS,
                    params=params,
                    headers={
                        "APCA-API-KEY-ID": self._credentials.key,
                        "APCA-API-SECRET-KEY": self._credentials.secret,
                        "Accept": "application/json",
                    },
                ) as response:
                    status, headers, url = response.status_code, response.headers, str(response.url)
                    if status == 200:
                        chunks = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > 4 * 1024 * 1024:
                                raise DataError("Market-data page exceeds byte limit.")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
            except httpx.HTTPError:
                failed = True
            if failed:
                if attempt == 2:
                    raise DataError("Market-data transport failed after bounded GET retries.")
                self._cooldown(2**attempt)
                continue
            delay = retry_delay(headers.get("Retry-After"))
            if headers.get("X-RateLimit-Remaining") == "0":
                reset_delay = 60.0
                try:
                    value = float(headers.get("X-RateLimit-Reset", "")) - self._clock()
                    if math.isfinite(value):
                        reset_delay = max(0, value)
                except ValueError:
                    pass
                delay = max(delay, reset_delay)
            if status == 429:
                delay = max(delay, 60)
            if delay:
                self._cooldown(delay)
            if status in (429, 500, 502, 503, 504) and attempt < 2:
                self._cooldown(max(delay, 2**attempt))
                continue
            if status != 200:
                raise DataError(
                    f"Market-data GET rejected (HTTP {status}); response body discarded."
                )
            decoded_text = json.dumps(json.loads(raw), ensure_ascii=False)
            if any(
                value in decoded_text or value.encode() in raw
                for value in (self._credentials.key, self._credentials.secret)
            ):
                raise DataError("Market-data response failed secret-exposure guard.")
            source = Source(
                "alpaca-iex-5min-v1"
                if query.timeframe is Timeframe.FIVE_MINUTES
                else "alpaca-iex-hourly",
                url,
                TERMS,
                datetime.fromtimestamp(self._clock(), UTC),
                hashlib.sha256(raw).hexdigest(),
                "historical_observation",
                "Alpaca Basic IEX; account and exchange terms apply; redistribution unverified.",
            )
            return raw, source
        raise DataError("Market-data GET retry budget exhausted.")

    def fetch(self, query: BarsQuery) -> str:
        return self.request("GET", BARS, query)

    def request(self, method: str, path: str, query: BarsQuery) -> str:
        """Return a complete download manifest ID, never an authenticated response/request."""
        if (method, path) != ("GET", BARS):
            raise DataError("Only the exact historical stock bars GET route is allowed.")
        if not self._enabled:
            raise DataError("Market-data networking is disabled; explicit opt-in required.")
        if type(query) is not BarsQuery:
            raise DataError("Invalid market-data query type.")
        # Guard against malformed manually constructed/mutated query objects, too.
        query.__post_init__()
        if query.timeframe is Timeframe.FIVE_MINUTES and not self._allow_five_minute:
            raise DataError("Five-minute download requires separate owner opt-in.")
        now = datetime.fromtimestamp(self._clock(), UTC)
        if query.end + query.timeframe.duration + timedelta(minutes=15) > now:
            raise DataError("Request only completed historical hours at least 15 minutes old.")
        result: str | None = None
        failed = False
        try:
            with self._lock:
                result = self._download(query)
        except (ValueError, sqlite3.Error, OSError, ScanError):
            failed = True
        if failed or result is None:
            # Outside except: no nested exception containing response content or credentials.
            raise DataError(
                "Market-data download incomplete; check access, quota, schema and storage."
            )
        return result

    def _download(self, query: BarsQuery) -> str:
        ids = []
        token = None
        seen: set[str] = set()
        last: dict[str, datetime] = {}
        for _ in range(100):
            raw, source = self._page(query, token)
            rows, next_token = decode_page(raw, source)
            for symbol, bars in rows.items():
                if bars and symbol in last and bars[0].start <= last[symbol]:
                    raise DataError("Duplicate or unordered cross-page bars.")
                if bars:
                    last[symbol] = bars[-1].start
            ids.append(self._archive.put(raw, source))
            if next_token is None:
                if query.timeframe is Timeframe.FIVE_MINUTES:
                    return archive_research_pages(
                        self._archive, tuple(ids), query.symbols[0]
                    )
                manifest = json.dumps(
                    {
                        "schema": "alpaca-iex-download-v1",
                        "query": query.params(),
                        "pages": ids,
                        "feed": "iex",
                        "alignment": "provider-native; never shifted",
                        "timezone": "timestamps normalized to UTC; raw offsets preserved",
                    },
                    sort_keys=True,
                ).encode()
                meta = Source(
                    "alpaca-iex-download",
                    source.url,
                    TERMS,
                    source.retrieved_at,
                    hashlib.sha256(manifest).hexdigest(),
                    "historical_observation",
                    source.license_note,
                )
                identity = self._archive.put(manifest, meta)
                # Revalidate saved pages, not only the in-memory response stream.
                load_download(self._archive, identity, query.symbols[0], exchange="UNVERIFIED")
                return identity
            if next_token in seen:
                raise DataError("Repeated pagination cursor.")
            seen.add(next_token)
            token = next_token
        raise DataError("Pagination budget exhausted; no complete download manifest created.")
