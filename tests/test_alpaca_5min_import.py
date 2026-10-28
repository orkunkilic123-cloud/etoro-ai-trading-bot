"""Offline import security regressions; no credentials or network."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from etoro_demo_bot.alpaca.contracts import BarsQuery
from etoro_demo_bot.history.alpaca_5min_import import import_pages
from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.timeframes import Timeframe


def query() -> BarsQuery:
    return BarsQuery(
        ("IBM",), datetime(2026, 3, 9, tzinfo=UTC),
        datetime(2026, 3, 10, tzinfo=UTC), timeframe=Timeframe.FIVE_MINUTES
    )


def test_import_rejects_hourly_and_nonraw(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    q = query()
    with pytest.raises(ValueError, match="INVALID_OFFLINE_IMPORT_CONTRACT"):
        import_pages(cache, (tmp_path / "missing",), BarsQuery(
            q.symbols, q.start, q.end
        ), retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=(None,), rights_note="owner review pending")
    with pytest.raises(ValueError, match="INVALID_OFFLINE_IMPORT_CONTRACT"):
        import_pages(cache, (tmp_path / "missing",), BarsQuery(
            q.symbols, q.start, q.end, adjustment="split", timeframe=Timeframe.FIVE_MINUTES
        ), retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=(None,), rights_note="owner review pending")


def test_import_fails_closed_on_missing_pages(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    with pytest.raises(ValueError, match="INVALID_PAGINATION_CHAIN"):
        import_pages(cache, (tmp_path / "missing",), query(),
            retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=("invented",), rights_note="review pending")
    with pytest.raises(ValueError, match="UNSAFE_OR_OVERSIZE_PAGE"):
        import_pages(cache, (tmp_path / "missing",), query(),
            retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=(None,), rights_note="review pending")


def test_rejects_nonfinal_pagination_and_malformed_bytes(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    page = tmp_path / "capture.json"
    page.write_bytes(b'{"bars":{},"next_page_token":"second"}')
    with pytest.raises(ValueError, match="INCOMPLETE_PAGINATION"):
        import_pages(cache, (page,), query(),
            retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=(None,), rights_note="review pending")
    page.write_bytes(b"not JSON")
    with pytest.raises(ValueError, match="Invalid Alpaca"):
        import_pages(cache, (page,), query(),
            retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=(None,), rights_note="review pending")


def test_rejects_future_retrieval_and_blank_rights(tmp_path: Path) -> None:
    cache = Archive(tmp_path / "history.sqlite")
    with pytest.raises(ValueError, match="IMPORT_RETRIEVAL_MUST_FOLLOW_HISTORY"):
        import_pages(cache, (tmp_path / "missing",), query(),
            retrieved_at=datetime(2026, 3, 9, tzinfo=UTC),
            cursor_tokens=(None,), rights_note="review pending")
    with pytest.raises(ValueError, match="INVALID_OFFLINE_IMPORT_CONTRACT"):
        import_pages(cache, (tmp_path / "missing",), query(),
            retrieved_at=datetime(2026, 3, 11, tzinfo=UTC),
            cursor_tokens=(None,), rights_note=" ")
