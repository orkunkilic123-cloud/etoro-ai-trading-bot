"""Deterministic tests for the documented Demo P&L cash route."""

import sys

import httpx
import pytest

from etoro_demo_bot.client import PNL, PORTFOLIO, ApiError, ApiResult, DemoClient, EndpointBlocked
from etoro_demo_bot.config import Credentials
from etoro_demo_bot.demo_balance import display_demo_balance
from etoro_demo_bot.demo_cash import IncompleteDemoSnapshot


def fixture() -> dict[str, object]:
    return {
        "credit": "1000",
        "ordersForOpen": [
            {"mirrorID": 0, "amount": "200"},
            {"mirrorID": 4, "amount": "100"},
        ],
        "orders": [{"amount": "150"}],
    }


def test_cash_formula_and_precise_labels() -> None:
    result = display_demo_balance(fixture())
    assert "Available cash (calculated): USD 650.00" in result
    assert "Reserved pending orders (calculated): USD 350.00" in result
    assert "Credit (P&L field; not equity): USD 1000.00" in result
    assert "Equity: Unavailable" in result
    assert "Total account balance: Unavailable" in result
    assert "account currency unverified" in result


@pytest.mark.parametrize("field", ["credit", "ordersForOpen", "orders"])
def test_missing_fields_fail_closed(field: str) -> None:
    data = fixture()
    del data[field]
    with pytest.raises(IncompleteDemoSnapshot):
        display_demo_balance(data)


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", "-1", {}, []])
def test_invalid_credit_fails_closed(value: object) -> None:
    data = fixture()
    data["credit"] = value
    with pytest.raises(IncompleteDemoSnapshot):
        display_demo_balance(data)


@pytest.mark.parametrize(
    "change",
    [
        {"ordersForOpen": [{}]},
        {"ordersForOpen": [{"mirrorID": "0", "amount": 3}]},
        {"ordersForOpen": [{"mirrorID": 0, "amount": "NaN"}]},
        {"orders": [{}]},
        {"orders": "not an array"},
        {"orders": [{"amount": 1100}]},
    ],
)
def test_invalid_orders_fail_closed(change: dict[str, object]) -> None:
    data = fixture()
    data.update(change)
    with pytest.raises(IncompleteDemoSnapshot):
        display_demo_balance(data)


def test_pnl_endpoint_exact_allowlist_and_no_mutations() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method + " " + request.url.path)
        return httpx.Response(200, json=fixture())

    credentials = Credentials("fixture-api", "fixture-user", "demo", True)
    with DemoClient(credentials, transport=httpx.MockTransport(handler)) as client:
        assert "Available cash" in display_demo_balance(client.pnl().data)
        with pytest.raises(EndpointBlocked):
            client.request("GET", PNL, params={"mode": "real"})
        with pytest.raises(EndpointBlocked):
            client.request("POST", PNL)
        with pytest.raises(EndpointBlocked):
            client.request("GET", "/api/v1/trading/info/real/pnl")
    assert seen == ["GET " + PNL]


def test_cli_uses_pnl_and_check_demo_uses_portfolio(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etoro_demo_bot.cli import main

    calls: list[str] = []
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls("fixture-api", "fixture-user", "demo", True)),
    )

    def pnl(self: DemoClient) -> ApiResult:
        calls.append(PNL)
        return ApiResult(data=fixture())

    def portfolio(self: DemoClient) -> ApiResult:
        calls.append(PORTFOLIO)
        return ApiResult(data={})

    monkeypatch.setattr(DemoClient, "pnl", pnl)
    monkeypatch.setattr(DemoClient, "portfolio", portfolio)
    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    assert main() == 0
    assert "USD 650.00" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["etoro-demo", "check-demo"])
    assert main() == 0
    assert "Demo portfolio GET succeeded." in capsys.readouterr().out
    assert calls == [PNL, PORTFOLIO]


@pytest.mark.parametrize("status", [401, 403, 500])
def test_redaction_for_rejected_reads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], status: int
) -> None:
    from etoro_demo_bot.cli import main

    secret = "PRIVATE_SYNTHETIC_SENTINEL"
    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls(secret, secret, "demo", True)),
    )

    def denied(self: DemoClient) -> ApiResult:
        raise ApiError(f"HTTP {status}: {secret}")

    monkeypatch.setattr(DemoClient, "pnl", denied)
    assert main() == 1
    assert secret not in capsys.readouterr().out


def test_partial_response_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from etoro_demo_bot.cli import main

    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls("fixture-api", "fixture-user", "demo", True)),
    )
    monkeypatch.setattr(DemoClient, "pnl", lambda self: ApiResult(data=fixture(), partial=True))
    assert main() == 1
    assert "650" not in capsys.readouterr().out
