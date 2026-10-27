import traceback
from uuid import UUID

import httpx
import pytest

from etoro_demo_bot.client import PORTFOLIO, RATES, ApiError, DemoClient, EndpointBlocked
from etoro_demo_bot.config import ConfigurationError, Credentials
from etoro_demo_bot.rate_limit import RateLimiter, retry_delay

API_SENTINEL = "synthetic-api-secret"
USER_SENTINEL = "synthetic-user-secret"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def read(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def credentials() -> Credentials:
    return Credentials(API_SENTINEL, USER_SENTINEL, "demo", True)


def test_environment_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "ETORO_API_KEY",
        "ETORO_USER_KEY",
        "ETORO_ENVIRONMENT",
        "ETORO_DEMO_KEY_CONFIRMED",
    ]:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError):
        Credentials.from_environment()
    monkeypatch.setenv("ETORO_API_KEY", API_SENTINEL)
    monkeypatch.setenv("ETORO_USER_KEY", USER_SENTINEL)
    monkeypatch.setenv("ETORO_ENVIRONMENT", "demo")
    with pytest.raises(ConfigurationError):
        Credentials.from_environment()
    monkeypatch.setenv("ETORO_DEMO_KEY_CONFIRMED", "true")
    assert Credentials.from_environment().environment == "demo"
    monkeypatch.setenv("ETORO_ENVIRONMENT", "real")
    with pytest.raises(ConfigurationError):
        Credentials.from_environment()


@pytest.mark.parametrize("key", ["", "secret\r\nx-header: yes", "secret value", "é"])
def test_invalid_credentials(key: str) -> None:
    with pytest.raises(ConfigurationError):
        Credentials(key, USER_SENTINEL, "demo", True)


def test_credentials_repr() -> None:
    assert API_SENTINEL not in repr(credentials())
    assert USER_SENTINEL not in repr(credentials())


def test_headers_routes_and_partial_data() -> None:
    requests: list[httpx.Request] = []
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "public-api.etoro.com"
        assert request.url.scheme == "https"
        assert request.method == "GET"
        assert request.headers["x-api-key"] == API_SENTINEL
        assert request.headers["x-user-key"] == USER_SENTINEL
        UUID(request.headers["x-request-id"])
        if request.url.path == PORTFOLIO:
            return httpx.Response(200, json={"clientPortfolio": {"positions": []}})
        assert request.url.path == RATES
        assert request.url.params["instrumentIds"] == "1,2"
        return httpx.Response(206, json={"rates": {"1": {"quoteType": "delayed"}}})

    with DemoClient(
        credentials(),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(clock.read, clock.sleep),
    ) as client:
        assert client.portfolio().data["clientPortfolio"]["positions"] == []
        result = client.rates([1, 2])
        assert result.partial
        assert result.data["rates"]["1"]["quoteType"] == "delayed"
    assert requests[0].headers["x-request-id"] != requests[1].headers["x-request-id"]
    assert clock.sleeps == [1.0]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/trading/info/portfolio"),
        ("GET", "/api/v1/trading/info/real/portfolio"),
        ("POST", "/api/v3/trading/execution/demo/orders"),
        ("POST", "/api/v3/trading/execution/orders"),
        ("DELETE", "/api/v2/trading/execution/demo/orders/1"),
        ("POST", PORTFOLIO),
        ("PATCH", PORTFOLIO),
        ("GET", PORTFOLIO + "/"),
        ("GET", PORTFOLIO + "?mode=real"),
        ("GET", "https://public-api.etoro.com" + PORTFOLIO),
        ("GET", "/api/v1/trading/info/demo/../portfolio"),
        ("GET", "/api/v1/trading/info/demo/%2e%2e/portfolio"),
        ("GET", "//evil.invalid" + PORTFOLIO),
    ],
)
def test_blocked_before_transport(method: str, path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Blocked request reached transport")

    with DemoClient(credentials(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(EndpointBlocked):
            client.request(method, path)


@pytest.mark.parametrize(
    "params",
    [{"environment": "real"}, {"instrumentIds": "1&mode=real"}, {"instrumentIds": "0"}, {}],
)
def test_blocked_query(params: dict[str, str]) -> None:
    with (
        DemoClient(
            credentials(),
            transport=httpx.MockTransport(
                lambda r: pytest.fail("Unexpected dispatch"),
            ),
        ) as client,
        pytest.raises(EndpointBlocked),
    ):
        client.request("GET", RATES, params=params)


@pytest.mark.parametrize("ids", [[], [0], [-1], [True], list(range(1, 1002))])
def test_invalid_ids(ids: list[int]) -> None:
    with DemoClient(credentials()) as client, pytest.raises(ApiError):
        client.rates(ids)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404, 500])
def test_errors_sanitized_and_no_redirect_or_auth_retry(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status, text=API_SENTINEL + USER_SENTINEL, headers={"Location": "https://evil.invalid/"}
        )

    with DemoClient(credentials(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ApiError) as error:
            client.portfolio()
    rendered = "".join(traceback.format_exception(error.value))
    assert API_SENTINEL not in rendered and USER_SENTINEL not in rendered
    assert calls == 1


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retry_then_success(status: int) -> None:
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"clientPortfolio": {}})

    with DemoClient(
        credentials(),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(clock.read, clock.sleep),
    ) as client:
        client.portfolio()
    assert calls == 2
    assert clock.sleeps == [7.0]


def test_timeout_bounded_and_no_secret_exception_context() -> None:
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout(USER_SENTINEL, request=request)

    with DemoClient(
        credentials(),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(clock.read, clock.sleep),
    ) as client:
        with pytest.raises(ApiError) as error:
            client.portfolio()
    assert calls == 3
    assert error.value.__context__ is None
    assert USER_SENTINEL not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null"])
def test_invalid_response(body: bytes) -> None:
    with (
        DemoClient(
            credentials(),
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=body),
            ),
        ) as client,
        pytest.raises(ApiError, match="invalid JSON"),
    ):
        client.portfolio()


def test_exhausted_quota_cooldown() -> None:
    clock = Clock()
    with DemoClient(
        credentials(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={},
                headers={
                    "RateLimit-Remaining": "0",
                    "RateLimit-Reset": "45",
                },
            ),
        ),
        limiter=RateLimiter(clock.read, clock.sleep),
    ) as client:
        client.portfolio()
        client.portfolio()
    assert clock.sleeps == [45.0]


def test_long_cooldown_stops_instead_of_retrying_early() -> None:
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "900"})

    with DemoClient(
        credentials(),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(clock.read, clock.sleep),
    ) as client:
        with pytest.raises(ApiError):
            client.portfolio()
    assert calls == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "invalid"])
def test_invalid_delay(value: str) -> None:
    assert retry_delay(value) == 0


def test_http_retry_budget() -> None:
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text=USER_SENTINEL)

    with DemoClient(
        credentials(),
        transport=httpx.MockTransport(handler),
        limiter=RateLimiter(clock.read, clock.sleep),
    ) as client:
        with pytest.raises(ApiError, match="HTTP 503"):
            client.portfolio()
    assert calls == 3


def test_cli_missing_config_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from etoro_demo_bot.cli import main

    monkeypatch.setattr("sys.argv", ["etoro-demo", "check-demo"])
    monkeypatch.setenv("ETORO_ENVIRONMENT", "real")
    monkeypatch.setenv("ETORO_API_KEY", API_SENTINEL)
    assert main() == 1
    output = capsys.readouterr().out
    assert "Demo" in output and API_SENTINEL not in output


def test_portfolio_query_override_blocked() -> None:
    with DemoClient(credentials()) as client, pytest.raises(EndpointBlocked):
        client.request("GET", PORTFOLIO, params={"mode": "real"})


def test_http_date_retry_header() -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    value = format_datetime(datetime.now(UTC) + timedelta(seconds=30))
    assert 28 <= retry_delay(value) <= 30
