"""Offline import security regressions; no credentials or network."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from etoro_demo_bot.alpaca.client import MarketDataClient
from etoro_demo_bot.alpaca.config import Credentials, DataError
from etoro_demo_bot.alpaca.contracts import BarsQuery
from etoro_demo_bot.history.alpaca import load_download
from etoro_demo_bot.history.alpaca_5min_evidence import (
    MANDATORY,
    evidence_report,
    write_evidence_report,
)
from etoro_demo_bot.history.alpaca_5min_import import import_pages
from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.timeframes import Timeframe

CAPTURED = datetime(2026, 3, 11, tzinfo=UTC)


def query() -> BarsQuery:
    return BarsQuery(
        ("IBM",),
        datetime(2026, 3, 9, tzinfo=UTC),
        datetime(2026, 3, 10, tzinfo=UTC),
        timeframe=Timeframe.FIVE_MINUTES,
    )


def attempt(
    cache: Archive,
    page: Path,
    *,
    q: BarsQuery | None = None,
    cursor: str | None = None,
    retrieved_at: datetime = CAPTURED,
    rights_note: str = "review pending",
) -> str:
    return import_pages(
        cache,
        (page,),
        q or query(),
        retrieved_at=retrieved_at,
        cursor_tokens=(cursor,),
        rights_note=rights_note,
    )


def test_import_rejects_hourly_and_nonraw(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    q = query()
    with pytest.raises(ValueError, match="INVALID_OFFLINE_IMPORT_CONTRACT"):
        attempt(cache, tmp_path / "missing", q=BarsQuery(q.symbols, q.start, q.end))
    with pytest.raises(ValueError, match="INVALID_OFFLINE_IMPORT_CONTRACT"):
        attempt(
            cache,
            tmp_path / "missing",
            q=BarsQuery(
                q.symbols,
                q.start,
                q.end,
                adjustment="split",
                timeframe=Timeframe.FIVE_MINUTES,
            ),
        )


def test_import_fails_closed_on_missing_pages(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    with pytest.raises(ValueError, match="INVALID_PAGINATION_CHAIN"):
        attempt(cache, tmp_path / "missing", cursor="invented")
    with pytest.raises(ValueError, match="UNSAFE_OR_OVERSIZE_PAGE"):
        attempt(cache, tmp_path / "missing")


def test_rejects_nonfinal_pagination_and_malformed_bytes(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    page = tmp_path / "capture.json"
    page.write_bytes(b'{"bars":{},"next_page_token":"second"}')
    with pytest.raises(ValueError, match="INCOMPLETE_PAGINATION"):
        attempt(cache, page)
    page.write_bytes(b"not JSON")
    with pytest.raises(ValueError, match="Invalid Alpaca"):
        attempt(cache, page)


def test_rejects_future_retrieval_and_blank_rights(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    with pytest.raises(ValueError, match="IMPORT_RETRIEVAL_MUST_FOLLOW_HISTORY"):
        attempt(cache, tmp_path / "missing", retrieved_at=datetime(2026, 3, 9, tzinfo=UTC))
    with pytest.raises(ValueError, match="INVALID_OFFLINE_IMPORT_CONTRACT"):
        attempt(cache, tmp_path / "missing", rights_note=" ")


def test_evidence_report_missing_manifest_blocks_without_trades(tmp_path: Path) -> None:
    archive = Archive(tmp_path / "private.sqlite")
    report = evidence_report(
        archive,
        "missing",
        "IBM",
        start="2026-03-09",
        end="2026-03-09",
        audit_at=datetime(2026, 10, 28, tzinfo=UTC),
        calendar_verified_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    assert report["status"] == "blocked"
    assert report["execution_authorized"] is False
    assert report["returns"] is None
    assert report["original_first_known_at"] is None
    assert len(report["blockers"]) == 1 + len(MANDATORY)
    output = tmp_path / "report.json"
    write_evidence_report(output, report)
    first = output.read_bytes()
    assert b"MISSING_ORIGINAL_PUBLICATION_AND_REVISIONS" in first
    with pytest.raises(FileExistsError):
        write_evidence_report(output, report)
    assert output.read_bytes() == first


def test_owner_5min_read_only_opt_in_and_private_manifest(tmp_path: Path) -> None:
    queries: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v2/stocks/bars"
        assert request.url.params["timeframe"] == "5Min"
        assert request.url.params["feed"] == "iex"
        return httpx.Response(
            200,
            json={
                "bars": {
                    "IBM": [
                        {
                            "t": "2026-03-09T14:00:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100,
                            "v": 10,
                        }
                    ]
                },
                "next_page_token": None,
            },
        )

    archive = Archive(tmp_path / "private.sqlite")
    synthetic_keys = Credentials("SYNTHETIC_KEY", "SYNTHETIC_SECRET")
    transport = httpx.MockTransport(handler)
    now = datetime(2026, 10, 28, tzinfo=UTC).timestamp()
    with MarketDataClient(
        synthetic_keys,
        archive,
        enabled=True,
        transport=transport,
        clock=lambda: now,
        request_limit=1,
    ) as client:
        with pytest.raises(DataError, match="owner opt-in"):
            client.fetch(query())
    assert not queries
    with MarketDataClient(
        synthetic_keys,
        archive,
        enabled=True,
        transport=transport,
        clock=lambda: now,
        request_limit=1,
        allow_five_minute=True,
    ) as client:
        manifest = client.fetch(query())
    assert len(queries) == 1
    history = load_download(archive, manifest, "IBM", exchange="XNYS")
    assert history.source.provider == "alpaca-iex-download-5min-v1"
    assert history.bars[0].known_at.year == 2026
    assert b"SYNTHETIC_SECRET" not in archive.path.read_bytes()
