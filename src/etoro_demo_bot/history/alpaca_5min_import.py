"""Offline owner-supplied native Alpaca 5Min page import; never contacts a service."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from ..alpaca.contracts import BARS, ORIGIN, TERMS, BarsQuery
from ..timeframes import Timeframe
from .alpaca import archive_research_pages, decode_page
from .archive import Archive
from .models import Source
from .providers import stamp

MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_PAGES = 100


def import_pages(
    archive: Archive,
    page_files: tuple[Path, ...],
    query: BarsQuery,
    *,
    retrieved_at: datetime,
    cursor_tokens: tuple[str | None, ...],
    rights_note: str,
) -> str:
    """Import exact captured JSON entity bytes, preserving page order and raw SHA-256.

    The owner must record the actual retrieval time and original page cursors. This
    cannot establish original bar availability, revisions, feed entitlement or rights.
    """
    if (
        type(query) is not BarsQuery
        or query.timeframe is not Timeframe.FIVE_MINUTES
        or query.adjustment != "raw"
        or len(query.symbols) != 1
        or not 1 <= len(page_files) <= MAX_PAGES
        or len(page_files) != len(cursor_tokens)
        or cursor_tokens[0] is not None
        or retrieved_at.tzinfo is None
        or retrieved_at.utcoffset() is None
        or not rights_note.strip()
    ):
        raise ValueError("INVALID_OFFLINE_IMPORT_CONTRACT")
    query.__post_init__()
    if query.end >= retrieved_at:
        raise ValueError("IMPORT_RETRIEVAL_MUST_FOLLOW_HISTORY")
    ids: list[str] = []
    next_expected: str | None = None
    seen: set[str] = set()
    for path, cursor in zip(page_files, cursor_tokens, strict=True):
        if cursor != next_expected or (cursor is not None and cursor in seen):
            raise ValueError("INVALID_PAGINATION_CHAIN")
        if cursor is not None:
            if not cursor.isascii() or not 1 <= len(cursor) <= 4096 or any(
                ord(c) < 33 or ord(c) > 126 for c in cursor
            ):
                raise ValueError("INVALID_PAGE_CURSOR")
            seen.add(cursor)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PAGE_BYTES:
            raise ValueError("UNSAFE_OR_OVERSIZE_PAGE")
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_PAGE_BYTES:
            raise ValueError("INVALID_PAGE_SIZE")
        params = query.params()
        if cursor is not None:
            params["page_token"] = cursor
        source = Source(
            "alpaca-iex-5min-v1",
            ORIGIN + BARS + "?" + urlencode(params),
            TERMS,
            retrieved_at.astimezone(UTC),
            hashlib.sha256(raw).hexdigest(),
            "historical_observation",
            rights_note,
        )
        _, next_expected = decode_page(raw, source)
        ids.append(archive.put(raw, source))
    if next_expected is not None:
        raise ValueError("INCOMPLETE_PAGINATION")
    return archive_research_pages(archive, tuple(ids), query.symbols[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline private 5Min page import; no network")
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--page", required=True, action="append", type=Path)
    parser.add_argument("--cursor", action="append", default=[])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--rights-note", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", args.symbol):
        parser.error("Invalid symbol")
    try:
        query = BarsQuery(
            (args.symbol,), stamp(args.start), stamp(args.end), timeframe=Timeframe.FIVE_MINUTES
        )
        # The first page's token is always absent; --cursor lists subsequent page tokens.
        tokens = (None, *args.cursor)
        manifest = import_pages(
            Archive(args.cache),
            tuple(args.page),
            query,
            retrieved_at=stamp(args.retrieved_at),
            cursor_tokens=tokens,
            rights_note=args.rights_note,
        )
    except (ValueError, OSError):
        parser.error("Import blocked: invalid pages, source metadata or pagination")
    print(json.dumps({"status": "imported_not_qualified", "manifest": manifest,
                      "execution_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
