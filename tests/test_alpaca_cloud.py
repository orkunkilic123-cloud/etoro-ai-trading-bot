"""Offline proxy construction and security tests; all credentials are synthetic."""

import json
import os
import socket
import ssl
from pathlib import Path
from typing import Any

import httpx
import httpx._client
import pytest

from etoro_demo_bot.alpaca import network
from etoro_demo_bot.alpaca.config import DataError


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Offline security tests must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    policy = tmp_path / "network-policy.json"
    policy.write_text(json.dumps({"version": 1, "http_proxy": "http://proxy:8080"}))
    monkeypatch.setattr(network, "POLICY", policy)
    monkeypatch.setattr(
        os,
        "environ",
        {
            "HTTPS_PROXY": "http://proxy:8080",
            "NO_PROXY": "*",
            "ALL_PROXY": "http://unapproved.invalid:8080",
            "ALPACA_DATA_CODEX_PROXY_REQUIRED": "true",
        },
    )
    return policy


def test_explicit_proxy_and_verified_tls_ignore_bypass(
    cloud: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    requests: list[httpx.Request] = []

    def transport(**kwargs: Any) -> httpx.MockTransport:
        calls.append(kwargs)

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200)

        return httpx.MockTransport(handler)

    monkeypatch.setattr(httpx._client, "HTTPTransport", transport)
    with network.http_client() as client:
        client.get("https://data.alpaca.markets/v2/stocks/bars")
        assert not client.follow_redirects
    assert len(requests) == 1
    assert str(calls[-1]["proxy"].url) == "http://proxy:8080"
    for call in calls:
        assert call["trust_env"] is False
        assert call["verify"].verify_mode == ssl.CERT_REQUIRED
        assert call["verify"].check_hostname is True


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "version",
        "malformed",
        "mismatch",
        "no_proxy",
        "userinfo",
        "path",
        "mode",
    ],
)
def test_bad_cloud_configuration_fails_closed(
    cloud: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    if change == "missing":
        cloud.unlink()
    elif change == "version":
        cloud.write_text('{"version": 2}')
    elif change == "malformed":
        cloud.write_text("not json")
    elif change == "mismatch":
        monkeypatch.setenv("HTTPS_PROXY", "http://unapproved.invalid:8080")
    elif change == "no_proxy":
        monkeypatch.delenv("HTTPS_PROXY")
    elif change in ("userinfo", "path"):
        proxy = (
            "http://SYNTHETIC_SECRET@proxy:8080"
            if change == "userinfo"
            else "http://proxy:8080/wrong"
        )
        cloud.write_text(json.dumps({"version": 1, "http_proxy": proxy}))
        monkeypatch.setenv("HTTPS_PROXY", proxy)
    else:
        monkeypatch.setenv("ALPACA_DATA_CODEX_PROXY_REQUIRED", "yes")
    with pytest.raises(DataError) as error:
        network.http_client()
    assert error.value.__context__ is None
    assert "SYNTHETIC_SECRET" not in str(error.value)


def test_invalid_ca_never_disables_verification(
    cloud: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "ca.pem"
    invalid.write_text("SYNTHETIC_INVALID_CA")
    monkeypatch.setenv("SSL_CERT_FILE", str(invalid))
    with pytest.raises(DataError) as error:
        network.http_client()
    assert error.value.__context__ is None
    assert str(invalid) not in str(error.value)


def test_ca_selectors_are_passed_to_verified_context(
    cloud: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ssl.create_default_context()
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> ssl.SSLContext:
        calls.append(kwargs)
        return context

    monkeypatch.setattr(ssl, "create_default_context", create)
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/ca.pem")
    monkeypatch.setenv("SSL_CERT_DIR", "/synthetic/certs")
    with network.http_client():
        pass
    assert calls == [{"cafile": "/synthetic/ca.pem", "capath": "/synthetic/certs"}]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_local_mode_preserves_direct_verified_transport(
    cloud: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cloud.unlink()
    monkeypatch.setattr(os, "environ", {})
    with network.http_client() as client:
        assert not client.follow_redirects


def test_mock_transport_cannot_escape_via_environment_proxy(cloud: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    with network.http_client(httpx.MockTransport(handler)) as client:
        client.get("https://data.alpaca.markets/v2/stocks/bars")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [200, 301, 302, 307, 308, 403, 407, "timeout"])
def test_placeholder_headers_only_reach_fixed_data_route(
    cloud: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: int | str,
) -> None:
    from datetime import UTC, datetime

    from etoro_demo_bot.alpaca.client import MarketDataClient
    from etoro_demo_bot.alpaca.config import Credentials
    from etoro_demo_bot.alpaca.contracts import BARS, BarsQuery
    from etoro_demo_bot.history.archive import Archive

    key, secret = "SYNTHETIC_PROXY_KEY_PLACEHOLDER", "SYNTHETIC_PROXY_SECRET_PLACEHOLDER"
    requests: list[httpx.Request] = []

    def transport(**kwargs: Any) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            # The direct HTTPX pool exists, but must never receive a request.
            assert kwargs.get("proxy") is not None
            assert str(kwargs["proxy"].url) == "http://proxy:8080"
            assert kwargs["verify"].check_hostname
            requests.append(request)
            assert request.url.host == "data.alpaca.markets"
            assert request.url.path == BARS and request.method == "GET"
            assert request.url.params["feed"] == "iex"
            assert request.headers["APCA-API-KEY-ID"] == key
            assert request.headers["APCA-API-SECRET-KEY"] == secret
            if status == "timeout":
                raise httpx.ConnectError(key + secret, request=request)
            assert isinstance(status, int)
            return httpx.Response(
                status,
                json={"bars": {}, "next_page_token": None},
                headers={"Location": "https://api.alpaca.markets/v2/orders"},
            )

        return httpx.MockTransport(handler)

    monkeypatch.setattr(httpx._client, "HTTPTransport", transport)
    query = BarsQuery(("IBM",), datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC))
    now = [datetime(2026, 10, 27, tzinfo=UTC).timestamp()]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with MarketDataClient(
        Credentials(key, secret),
        Archive(tmp_path / "data.sqlite"),
        enabled=True,
        clock=lambda: now[0],
        sleep=sleep,
    ) as client:
        for method, path in [
            ("POST", BARS),
            ("GET", "/v2/account"),
            ("POST", "/v2/orders"),
            ("GET", "https://api.alpaca.markets/v2/orders"),
            ("GET", "https://paper-api.alpaca.markets/v2/orders"),
            ("GET", "https://evil.invalid/v2/stocks/bars"),
        ]:
            with pytest.raises(DataError):
                client.request(method, path, query)
        assert not requests
        if status == 200:
            client.fetch(query)
        else:
            with pytest.raises(DataError) as error:
                client.fetch(query)
            assert error.value.__context__ is None
            assert key not in str(error.value) and secret not in str(error.value)
    assert len(requests) == (3 if status == "timeout" else 1)
    raw = (tmp_path / "data.sqlite").read_bytes()
    assert key.encode() not in raw and secret.encode() not in raw
