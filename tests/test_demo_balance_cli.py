"""Offline regressions: portfolio GET must never masquerade as verified P&L."""

import sys

import httpx
import pytest

from etoro_demo_bot.client import ApiError, ApiResult, DemoClient
from etoro_demo_bot.config import Credentials
from etoro_demo_bot.demo_balance import display_demo_balance
from etoro_demo_bot.demo_cash import IncompleteDemoSnapshot


def observation() -> dict[str, object]:
    return {
        "clientPortfolio": {
            "accountCurrencyId": 1,
            "credit": 1000,
            "ordersForOpen": [{"mirrorID": 0, "amount": 200}],
            "orders": [{"amount": 150}],
            "positions": [{"positionID": 1}],
            "mirrors": [],
        }
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"clientPortfolio": None},
        {"clientPortfolio": {}},
        observation(),
        {"clientPortfolio": {"credit": "UNTRUSTED_PRIVATE_VALUE"}},
    ],
)
def test_portfolio_cannot_claim_balances(payload: dict[str, object]) -> None:
    with pytest.raises(IncompleteDemoSnapshot):
        display_demo_balance(payload)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_cli_failures_do_not_print_synthetic_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    from etoro_demo_bot.cli import main

    secret = "SYNTHETIC_PRIVATE_VALUE"
    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls(secret, secret, "demo", True)),
    )

    def rejected(self: DemoClient) -> ApiResult:
        raise ApiError(f"HTTP {status}: {secret}")

    monkeypatch.setattr(DemoClient, "portfolio", rejected)
    assert main() == 1
    output = capsys.readouterr().out
    assert secret not in output
    assert "unavailable" in output


def test_malformed_response_redacted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from etoro_demo_bot.cli import main

    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls("fixture-api", "fixture-user", "demo", True)),
    )
    monkeypatch.setattr(
        DemoClient, "portfolio",
        lambda self: ApiResult(data={"clientPortfolio": {"credit": "PRIVATE_RESPONSE"}}),
    )
    assert main() == 1
    assert "PRIVATE_RESPONSE" not in capsys.readouterr().out


def test_get_only_and_original_check_demo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from etoro_demo_bot.cli import main

    credentials = Credentials("fixture-api", "fixture-user", "demo", True)
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method + " " + request.url.path)
        return httpx.Response(200, json=observation())

    with DemoClient(credentials, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IncompleteDemoSnapshot):
            display_demo_balance(client.portfolio().data)
    assert requests == ["GET /api/v1/trading/info/demo/portfolio"]
    monkeypatch.setattr(sys, "argv", ["etoro-demo", "check-demo"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls("fixture-api", "fixture-user", "demo", True)),
    )
    monkeypatch.setattr(DemoClient, "portfolio", lambda self: ApiResult(data=observation()))
    assert main() == 0
    assert (
        capsys.readouterr().out.strip()
        == "Demo portfolio GET succeeded. No orders submitted; key scope relies on eToro enforcement."
    )
