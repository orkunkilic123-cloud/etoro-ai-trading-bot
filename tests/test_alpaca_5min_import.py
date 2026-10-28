"""Offline import security regressions; no credentials or network."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from etoro_demo_bot.alpaca.contracts import BarsQuery
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
