"""Offline integration: read-only GET does not constitute trade authorization."""

import httpx
import pytest

from etoro_demo_bot.client import PORTFOLIO, DemoClient, EndpointBlocked
from etoro_demo_bot.config import ConfigurationError, Credentials
from etoro_demo_bot.first_trade_preparation import TradeEvidence, prepare_first_demo_trade


def test_successful_synthetic_demo_read_cannot_authorize_execution() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method + " " + request.url.path)
        return httpx.Response(200, json={"clientPortfolio": {"positions": []}})

    creds = Credentials("fake-app", "fake-demo-user", "demo", True)
    with DemoClient(creds, transport=httpx.MockTransport(handler)) as client:
        assert client.portfolio().data["clientPortfolio"]["positions"] == []
        with pytest.raises(EndpointBlocked):
            client.request("POST", "/api/v2/trading/execution/demo/orders")
        with pytest.raises(EndpointBlocked):
            client.request("POST", "/api/v3/trading/execution/demo/orders")
        with pytest.raises(EndpointBlocked):
            client.request("GET", "/api/v1/trading/info/portfolio")
    assert calls == ["GET " + PORTFOLIO]
    result = prepare_first_demo_trade(TradeEvidence())
    assert not result.ready_to_request_owner_approval
    assert not result.execution_authorized


def test_real_environment_blocked_before_any_network() -> None:
    with pytest.raises(ConfigurationError):
        Credentials("fake-app", "fake-real-user", "real", True)
