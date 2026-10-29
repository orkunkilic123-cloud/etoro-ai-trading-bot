"""Offline read-only Demo balance and redaction tests."""

import sys

import httpx
import pytest

from etoro_demo_bot.client import DemoClient
from etoro_demo_bot.config import Credentials
from etoro_demo_bot.demo_balance import display_demo_balance
from etoro_demo_bot.demo_cash import IncompleteDemoSnapshot


def observation() -> dict[str, object]:
    return {
        "clientPortfolio": {
            "accountCurrencyId": 1,
            "credit": 1000,
            "ordersForOpen": [
                {"mirrorID": 0, "amount": 200},
                {"mirrorID": 7, "amount": 70},
            ],
            "orders": [{"amount": 150}],
            "positions": [{"positionID": 1}],
            "mirrors": [],
        }
    }


def test_verified_cash_components() -> None:
    output = display_demo_balance(observation())
    assert "Portfolio credit (before pending allocations): USD 1000.00" in output
    assert "Available cash (calculated): USD 650.00" in output
    assert "Reserved cash (documented pending orders): USD 350.00" in output
    assert "Direct open positions: 1" in output
    assert "Total account balance: Not available" in output
    assert "Equity: Not available" in output


@pytest.mark.parametrize(
    "change",
    [
        {"clientPortfolio": None},
        {"clientPortfolio": {"credit": 1000}},
        {"clientPortfolio": {"accountCurrencyId": 2, "credit": 1000}},
        {"clientPortfolio": {"accountCurrencyId": True, "credit": 1000}},
        {"clientPortfolio": {"accountCurrencyId": 1, "credit": "NaN"}},
        {"clientPortfolio": {"accountCurrencyId": 1, "credit": -1}},
        {"clientPortfolio": {"accountCurrencyId": 1, "credit": 1000, "orders": []}},
    ],
)
def test_incomplete_schema_fails_closed(change: dict[str, object]) -> None:
    with pytest.raises(IncompleteDemoSnapshot):
        display_demo_balance(change)


def test_malformed_positions_fail_closed() -> None:
    payload = observation()
    portfolio = payload["clientPortfolio"]
    assert isinstance(portfolio, dict)
    portfolio["positions"] = [None]
    with pytest.raises(IncompleteDemoSnapshot):
        display_demo_balance(payload)


def test_copy_positions_not_claimed_complete() -> None:
    payload = observation()
    portfolio = payload["clientPortfolio"]
    assert isinstance(portfolio, dict)
    portfolio["mirrors"] = [{"positions": [{}]}]
    assert "copy-trading coverage unverified" in display_demo_balance(payload)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_cli_auth_failures_redacted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    from etoro_demo_bot.cli import main

    secret = "UNPRINTABLE_SYNTHETIC_SECRET"
    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls(secret, secret, "demo", True)),
    )
    original = DemoClient.portfolio

    def rejected(self: DemoClient) -> object:
        raise __import__("etoro_demo_bot.client", fromlist=["ApiError"]).ApiError(
            f"API read rejected (HTTP {status}); " + secret
        )

    monkeypatch.setattr(DemoClient, "portfolio", rejected)
    assert main() == 1
    output = capsys.readouterr().out
    assert secret not in output
    monkeypatch.setattr(DemoClient, "portfolio", original)


def test_cli_malformed_payload_redacted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from etoro_demo_bot.cli import main
    from etoro_demo_bot.client import ApiResult

    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials, "from_environment",
        classmethod(lambda cls: cls("fixture-api", "fixture-user", "demo", True)),
    )
    monkeypatch.setattr(
        DemoClient, "portfolio",
        lambda self: ApiResult(data={"clientPortfolio": {"secret": "SENSITIVE_FIXTURE"}}),
    )
    assert main() == 1
    output = capsys.readouterr().out
    assert "SENSITIVE_FIXTURE" not in output


def test_client_remains_get_only() -> None:
    credentials = Credentials("fixture-api", "fixture-user", "demo", True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/trading/info/demo/portfolio"
        return httpx.Response(200, json=observation())

    with DemoClient(credentials, transport=httpx.MockTransport(handler)) as client:
        assert "Available cash" in display_demo_balance(client.portfolio().data)
