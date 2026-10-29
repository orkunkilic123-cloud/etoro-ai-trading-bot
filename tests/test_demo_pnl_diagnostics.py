"""Offline diagnostic categories for the read-only Demo P&L endpoint."""

import sys

import httpx
import pytest

from etoro_demo_bot.client import PNL, DemoClient, ReadDiagnostic
from etoro_demo_bot.config import Credentials


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "authorization"),
        (403, "authorization"),
        (404, "unsupported-endpoint"),
        (429, "rate-limit"),
        (500, "server"),
        (502, "server"),
        (503, "server"),
        (504, "server"),
        (418, "unexpected-http"),
    ],
)
def test_http_categories(status: int, category: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == PNL
        return httpx.Response(status, text="PRIVATE_SYNTHETIC_RESPONSE")

    with DemoClient(
        Credentials("synthetic-api", "synthetic-user", "demo", True),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(ReadDiagnostic) as exc:
            client.pnl()
    assert exc.value.category == category
    assert "PRIVATE_SYNTHETIC_RESPONSE" not in str(exc.value)


@pytest.mark.parametrize(
    ("exception", "category"),
    [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network")],
)
def test_transport_categories(
    exception: type[httpx.TransportError], category: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception("PRIVATE_SYNTHETIC_RESPONSE", request=request)

    with DemoClient(
        Credentials("synthetic-api", "synthetic-user", "demo", True),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(ReadDiagnostic) as exc:
            client.pnl()
    assert exc.value.category == category
    assert "PRIVATE_SYNTHETIC_RESPONSE" not in str(exc.value)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null"])
def test_invalid_json_category(body: bytes) -> None:
    with DemoClient(
        Credentials("synthetic-api", "synthetic-user", "demo", True),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
    ) as client:
        with pytest.raises(ReadDiagnostic, match="invalid-response"):
            client.pnl()


def test_cli_response_schema_category(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from etoro_demo_bot.cli import main
    from etoro_demo_bot.client import ApiResult

    monkeypatch.setattr(sys, "argv", ["etoro-demo", "show-demo-balance"])
    monkeypatch.setattr(
        Credentials,
        "from_environment",
        classmethod(lambda cls: cls("synthetic-api", "synthetic-user", "demo", True)),
    )
    monkeypatch.setattr(
        DemoClient,
        "pnl",
        lambda self: ApiResult(data={"credit": "PRIVATE_SYNTHETIC_RESPONSE"}),
    )
    assert main() == 1
    output = capsys.readouterr().out
    assert "incomplete-or-incompatible-data" in output
    assert "PRIVATE_SYNTHETIC_RESPONSE" not in output
