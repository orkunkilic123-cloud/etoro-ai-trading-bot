"""The only broker boundary: three exact GET routes, no redirects or mutations."""

import random
import threading
from dataclasses import dataclass
from types import TracebackType
from typing import Any
from uuid import uuid4

import httpx

from .config import Credentials
from .rate_limit import RateLimiter, retry_delay

ORIGIN = "https://public-api.etoro.com"
PORTFOLIO = "/api/v1/trading/info/demo/portfolio"
PNL = "/api/v1/trading/info/demo/pnl"
RATES = "/api/v2/market-data/rates"
ALLOWED = frozenset({("GET", PORTFOLIO), ("GET", PNL), ("GET", RATES)})


class ApiError(Exception):
    """Sanitized errors: never retain requests, responses, or upstream exceptions."""


class ReadDiagnostic(ApiError):
    """A fixed safe error category; never captures upstream response content."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class EndpointBlocked(ApiError):
    """Operation not permitted by the immutable read-only policy."""


@dataclass(frozen=True)
class ApiResult:
    data: dict[str, Any]
    partial: bool = False


class DemoClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._credentials = credentials
        self._limiter = limiter or RateLimiter()
        self._lock = threading.Lock()
        self._http = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=False,
        )

    def __enter__(self) -> "DemoClient":
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

    def portfolio(self) -> ApiResult:
        return self.request("GET", PORTFOLIO)

    def pnl(self) -> ApiResult:
        return self.request("GET", PNL)

    def rates(self, instrument_ids: list[int]) -> ApiResult:
        if not 1 <= len(instrument_ids) <= 1000 or any(
            type(i) is not int or i <= 0 for i in instrument_ids
        ):
            raise ApiError("Supply between 1 and 1000 positive integer instrument IDs.")
        return self.request(
            "GET",
            RATES,
            params={
                "instrumentIds": ",".join(map(str, instrument_ids)),
            },
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> ApiResult:
        if (method, path) not in ALLOWED:
            raise EndpointBlocked(
                "Only explicitly allowed read-only Demo/data operations are allowed."
            )
        if path in {PORTFOLIO, PNL} and params:
            raise EndpointBlocked("Portfolio query overrides are blocked.")
        if path == RATES:
            ids = (params or {}).get("instrumentIds", "").split(",")
            if (
                set(params or {}) != {"instrumentIds"}
                or not 1 <= len(ids) <= 1000
                or any(not i.isascii() or not i.isdecimal() or int(i) <= 0 for i in ids)
            ):
                raise EndpointBlocked("Invalid market-data query.")
        with self._lock:
            return self._get(path, params)

    def _get(self, path: str, params: dict[str, str] | None) -> ApiResult:
        for attempt in range(3):
            timed_out = False
            failure = ""
            response: httpx.Response | None = None
            try:
                self._limiter.wait()
                response = self._http.get(
                    ORIGIN + path,
                    params=params,
                    headers={
                        "x-api-key": self._credentials.api_key,
                        "x-user-key": self._credentials.user_key,
                        "x-request-id": str(uuid4()),
                        "Accept": "application/json",
                    },
                )
            except httpx.TimeoutException:
                failure = "Read request timed out."
                timed_out = True
            except httpx.TransportError:
                failure = "Read request failed after bounded retries."
            except (ValueError, httpx.HTTPError):
                failure = "Request could not be completed safely."
                # Raised outside the except block to avoid secret-bearing exception context.
                attempt = 2
            if failure:
                if attempt == 2:
                    if path == PNL:
                        raise ReadDiagnostic("timeout" if timed_out else "network") from None
                    raise ApiError(failure)
                self._limiter.defer(2**attempt + random.random())
                continue
            assert response is not None
            status = response.status_code
            delay = retry_delay(response.headers.get("Retry-After"))
            if response.headers.get("RateLimit-Remaining") == "0":
                delay = max(delay, retry_delay(response.headers.get("RateLimit-Reset")) or 60)
            self._limiter.defer(delay)
            if status in {429, 502, 503, 504} and attempt < 2:
                response.close()
                self._limiter.defer(max(delay, 2**attempt + random.random()))
                continue
            if status != 200 and not (path == RATES and status == 206):
                response.close()
                if path == PNL:
                    category = (
                        "authorization" if status in {401, 403} else
                        "unsupported-endpoint" if status == 404 else
                        "rate-limit" if status == 429 else
                        "server" if 500 <= status <= 599 else
                        "unexpected-http"
                    )
                    raise ReadDiagnostic(category)
                raise ApiError(f"API read rejected (HTTP {status}); no response body retained.")
            data: Any = None
            try:
                data = response.json()
            except ValueError:
                pass
            finally:
                response.close()
            if not isinstance(data, dict):
                if path == PNL:
                    raise ReadDiagnostic("invalid-response")
                raise ApiError("API returned an invalid JSON object.")
            return ApiResult(data=data, partial=status == 206)
        raise ApiError("Read retry budget exhausted.")
