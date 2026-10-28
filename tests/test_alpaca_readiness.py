"""Synthetic HTTP data only; no sockets, real credentials or performance claims."""

import json
import socket
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from etoro_demo_bot.alpaca.client import MarketDataClient
from etoro_demo_bot.alpaca.config import Credentials, DataError
from etoro_demo_bot.alpaca.contracts import BarsQuery
from etoro_demo_bot.history import hourly_cli
from etoro_demo_bot.history.archive import Archive

NOW = datetime(2026, 10, 28, tzinfo=UTC)
QUERY = BarsQuery(("IBM",), datetime(2026, 3, 9, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC))


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Readiness tests must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(
        Credentials, "from_environment", lambda: pytest.fail("Credentials accessed")
    )


def download(path: Path, *, status: int = 200, token: str | None = None) -> tuple[str, int]:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "GET"
        assert request.url.host == "data.alpaca.markets"
        assert request.url.path == "/v2/stocks/bars"
        assert request.url.params["feed"] == "iex"
        if status == -1:
            raise httpx.ReadTimeout("SYNTHETIC_SECRET", request=request)
        return httpx.Response(
            status,
            json={
                "bars": {
                    "IBM": [
                        {
                            "t": "2026-03-09T14:00:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100,
                            "v": 20,
                        }
                    ]
                },
                "next_page_token": token,
            },
        )

    with MarketDataClient(
        Credentials("SYNTHETIC_KEY", "SYNTHETIC_SECRET"),
        Archive(path),
        enabled=True,
        request_limit=1,
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW.timestamp(),
        sleep=lambda seconds: None,
    ) as client:
        if status == 200 and token is None:
            identity = client.fetch(QUERY)
            # Budget is for the client lifetime, including later fetch calls.
            with pytest.raises(DataError):
                client.fetch(QUERY)
        else:
            with pytest.raises(DataError):
                client.fetch(QUERY)
            identity = ""
    return identity, calls


@pytest.mark.parametrize(
    "status,token",
    [(200, None), (200, "next"), (429, None), (500, None), (401, None), (302, None), (-1, None)],
)
def test_single_get_budget(tmp_path: Path, status: int, token: str | None) -> None:
    path = tmp_path / "cache.sqlite"
    identity, calls = download(path, status=status, token=token)
    assert calls == 1
    if not identity:
        with sqlite3.connect(path) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM snapshots WHERE metadata LIKE '%alpaca-iex-download%' "
                    "                AND metadata NOT LIKE '%alpaca-iex-hourly%'"
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize("limit", [0, -1, 301, True, 1.5])
def test_bad_budget_before_transport(tmp_path: Path, limit: Any) -> None:
    with pytest.raises(DataError, match="budget"):
        MarketDataClient(
            Credentials("SYNTHETIC_KEY", "SYNTHETIC_SECRET"),
            Archive(tmp_path / "data.sqlite"),
            request_limit=limit,
        )


def test_missing_readonly_archive_does_not_create_anything(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "data.sqlite"
    with pytest.raises(sqlite3.Error):
        Archive.open_readonly(path)
    assert not path.parent.exists()


def test_manifest_audit_preserves_evidence_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cache.sqlite"
    identity, _ = download(path)
    before = path.read_bytes()
    archive = Archive.open_readonly(path)
    raw, source = archive.get(identity)
    with pytest.raises(ValueError, match="read-only"):
        archive.put(raw, source)
    study = tmp_path / "study.json"
    study.write_text(
        json.dumps(
            {
                "start": "2026-03-09",
                "end": "2026-03-13",
                "train_at": "2026-03-09T00:00:00Z",
                "validation_at": "2026-03-10T00:00:00Z",
                "test_at": "2026-03-11T00:00:00Z",
                "finish_at": "2026-03-13T00:00:00Z",
                "audit_at": NOW.isoformat(),
                "calendar_verified_at": NOW.isoformat(),
                "exchange": "XNYS",
                "currency": "USD",
                "basis": "raw",
            }
        )
    )
    output = tmp_path / "audit.json"
    argv = [
        "hourly_cli",
        "--alpaca-manifest",
        identity,
        "--symbol",
        "IBM",
        "--study",
        str(study),
        "--cache",
        str(path),
        "--output",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert hourly_cli.main() == 0
    report = json.loads(output.read_text())
    assert report["execution_authorized"] is False
    assert report["native_session_counts"]["full_regular"] == 1
    assert "OFF_GRID_OR_PARTIAL_CANDLE" in report["audit"]["coverage_errors"]
    assert "ORIGINAL_AVAILABILITY_UNVERIFIED" in report["audit"]["replay_blockers"]
    assert all(
        r["status"] == "not_run" and r["total_return"] is None for r in report["comparisons"]
    )
    assert path.read_bytes() == before
    # Exclusive output creation, unknown symbols and conflicting basis fail closed.
    with pytest.raises(SystemExit):
        hourly_cli.main()
    output.unlink()
    monkeypatch.setattr(sys, "argv", ["UNREQUESTED" if x == "IBM" else x for x in argv])
    with pytest.raises(SystemExit):
        hourly_cli.main()
    assert not output.exists()
    monkeypatch.setattr(sys, "argv", argv)
    request = json.loads(study.read_text())
    request["basis"] = "split_adjusted"
    study.write_text(json.dumps(request))
    with pytest.raises(SystemExit):
        hourly_cli.main()
    assert not output.exists()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "extra",
    [
        ["--symbols", "IBM", "IBM"],
        ["--symbols", "ibm"],
        ["--start", "2026-03-12T00:00:00Z"],
        ["--start", "2026-03-09T00:00:00"],
        ["--adjustment", "all"],
        ["--request-limit", "0"],
    ],
)
def test_invalid_preview_stops_before_any_side_effects(
    monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    from etoro_demo_bot.alpaca import __main__ as cli

    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Preview created a cache or transport")

    monkeypatch.setattr(cli, "Archive", blocked)
    monkeypatch.setattr(cli, "MarketDataClient", blocked)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alpaca",
            "--dry-run",
            "--symbols",
            "IBM",
            "--start",
            "2026-03-09T00:00:00Z",
            "--end",
            "2026-03-10T00:00:00Z",
        ]
        + extra,
    )
    with pytest.raises(SystemExit):
        cli.main()


def test_missing_manifest_cache_fails_without_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    study = tmp_path / "study.json"
    example = Path(__file__).resolve().parents[1] / "docs/examples/alpaca-study.json"
    study.write_bytes(example.read_bytes())
    cache = tmp_path / "missing" / "data.sqlite"
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hourly_cli",
            "--alpaca-manifest",
            "missing",
            "--symbol",
            "IBM",
            "--cache",
            str(cache),
            "--study",
            str(study),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as error:
        hourly_cli.main()
    assert error.value.code == 1
    assert not cache.parent.exists() and not output.exists()
    assert str(cache) not in capsys.readouterr().err
