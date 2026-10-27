"""Offline documented Alpaca bars parser. Never infer original publication or eligibility."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from ..alpaca.contracts import page_cursor, query_from_source
from .archive import Archive
from .models import Bar, ExchangeCalendar, History, Source
from .providers import check_source, number, stamp


def decode_page(raw: bytes, source: Source) -> tuple[dict[str, tuple[Bar, ...]], str | None]:
    """Validate checksums before decoding; sanitized parser failures contain no source text."""
    failed = False
    result: dict[str, tuple[Bar, ...]] = {}
    token: str | None = None
    try:
        check_source(raw, source)
        query = query_from_source(source)
        payload: Any = json.loads(raw, parse_float=Decimal)
        if (
            not isinstance(payload, dict)
            or "bars" not in payload
            or "next_page_token" not in payload
        ):
            raise ValueError()
        if payload.get("currency", "USD") != "USD" or payload.get("feed", "iex") != "iex":
            raise ValueError()
        token = payload["next_page_token"]
        if token is not None and (
            not isinstance(token, str)
            or not token
            or len(token) > 4096
            or not token.isascii()
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
        ):
            raise ValueError()
        rows = payload["bars"]
        if not isinstance(rows, dict) or set(rows) - set(query.symbols):
            raise ValueError()
        basis = "raw" if query.adjustment == "raw" else "split_adjusted"
        count = 0
        for symbol, items in rows.items():
            if not isinstance(items, list):
                raise ValueError()
            bars = []
            previous = None
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError()
                start = stamp(item["t"])
                end = start + timedelta(hours=1)
                if not query.start <= start <= query.end or end > source.retrieved_at:
                    raise ValueError()
                if previous is not None and start <= previous:
                    raise ValueError()
                values = [number(str(item[k])) for k in ("o", "h", "l", "c")]
                volume = number(str(item["v"]), zero=True)
                if (
                    not values[2]
                    <= min(values[0], values[3])
                    <= max(values[0], values[3])
                    <= values[1]
                ):
                    raise ValueError()
                bars.append(
                    Bar(
                        start,
                        end,
                        values[0],
                        values[1],
                        values[2],
                        values[3],
                        volume,
                        source.retrieved_at,
                        basis,
                    )
                )
                previous = start
                count += 1
            result[symbol] = tuple(bars)
        if count > 10000:
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        failed = True
    if failed:
        raise ValueError("Invalid Alpaca page schema, chronology or provenance.")
    return result, token


class AlpacaBars:
    """HistoricalProvider implementation for one raw page, with caller-reviewed exchange mapping."""

    def __init__(self, symbol: str, *, exchange: str) -> None:
        self.symbol, self.exchange = symbol, exchange

    def parse(self, raw: bytes, source: Source) -> History:
        rows, _ = decode_page(raw, source)
        query = query_from_source(source)
        if self.symbol not in query.symbols:
            raise ValueError("Symbol not requested in Alpaca source.")
        return History(
            self.symbol,
            self.exchange,
            "USD",
            "1h",
            "raw" if query.adjustment == "raw" else "split_adjusted",
            rows.get(self.symbol, ()),
            source,
        )


def load_download(archive: Archive, manifest_id: str, symbol: str, *, exchange: str) -> History:
    """Revalidate the immutable complete-page chain before exposing any combined history."""
    raw, manifest_source = archive.get(manifest_id)
    failed = False
    histories: list[History] = []
    try:
        if manifest_source.provider != "alpaca-iex-download":
            raise ValueError()
        manifest: Any = json.loads(raw)
        if manifest.get("schema") != "alpaca-iex-download-v1" or manifest.get("feed") != "iex":
            raise ValueError()
        ids = manifest["pages"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids):
            raise ValueError()
        expected_token = None
        query = None
        previous: dict[str, datetime] = {}
        visited: set[str | None] = set()
        for index, identity in enumerate(ids):
            page, source = archive.get(identity)
            if expected_token in visited or source.classification != manifest_source.classification:
                raise ValueError()
            visited.add(expected_token)
            current = query_from_source(source)
            if query is not None and current != query:
                raise ValueError()
            if page_cursor(source) != expected_token:
                raise ValueError()
            query = current
            rows, token = decode_page(page, source)
            for name, bars in rows.items():
                if bars and name in previous and bars[0].start <= previous[name]:
                    raise ValueError()
                if bars:
                    previous[name] = bars[-1].start
            histories.append(AlpacaBars(symbol, exchange=exchange).parse(page, source))
            if token is None and index != len(ids) - 1:
                raise ValueError()
            expected_token = token
        if (
            expected_token is not None
            or query is None
            or manifest["query"] != query.params()
            or source.url != manifest_source.url
            or source.retrieved_at != manifest_source.retrieved_at
        ):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        failed = True
    if failed or not histories:
        raise ValueError("Invalid or incomplete Alpaca download manifest.")
    bars = tuple(bar for h in histories for bar in h.bars)
    return History(symbol, exchange, "USD", "1h", histories[0].basis, bars, manifest_source)


def session_counts(history: History, calendar: ExchangeCalendar) -> dict[str, int]:
    """Report native boundary/extended-hours bars without trimming, shifting or fabricating them."""
    from zoneinfo import ZoneInfo

    if not history.bars:
        return {"full_regular": 0, "boundary": 0, "outside_regular": 0}
    zone = ZoneInfo("America/New_York")
    dates = [b.start.astimezone(zone).date() for b in history.bars]
    sessions = calendar.sessions(min(dates), max(dates))
    counts = {"full_regular": 0, "boundary": 0, "outside_regular": 0}
    for bar in history.bars:
        if any(s.opens <= bar.start < bar.end <= s.closes for s in sessions):
            counts["full_regular"] += 1
        elif any(bar.start < s.closes and bar.end > s.opens for s in sessions):
            counts["boundary"] += 1
        else:
            counts["outside_regular"] += 1
    return counts
