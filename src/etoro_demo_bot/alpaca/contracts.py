"""Verified market-data query contract; URL parsing only, no network operations."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from ..history.models import Source
from ..history.providers import stamp
from ..scanner.models import aware

ORIGIN = "https://data.alpaca.markets"
BARS = "/v2/stocks/bars"
TERMS = "https://alpaca.markets/disclosures"


@dataclass(frozen=True)
class BarsQuery:
    symbols: tuple[str, ...]
    start: datetime
    end: datetime  # Inclusive bar-start bound, as documented by Alpaca.
    adjustment: str = "raw"

    def __post_init__(self) -> None:
        if (
            type(self.symbols) is not tuple
            or not 1 <= len(self.symbols) <= 20
            or len(set(self.symbols)) != len(self.symbols)
            or any(
                not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s)
                for s in self.symbols
            )
            or not aware(self.start)
            or not aware(self.end)
            or self.start >= self.end
            or self.adjustment not in ("raw", "split")
        ):
            raise ValueError("Invalid Alpaca hourly query.")

    def params(self) -> dict[str, str]:
        return {
            "symbols": ",".join(self.symbols),
            "timeframe": "1Hour",
            "start": self.start.astimezone(UTC).isoformat(),
            "end": self.end.astimezone(UTC).isoformat(),
            "feed": "iex",
            "currency": "USD",
            "adjustment": self.adjustment,
            "asof": "-",
            "sort": "asc",
            "limit": "10000",
        }


def query_from_source(source: Source) -> BarsQuery:
    url = urlsplit(source.url)
    values = parse_qs(url.query, keep_blank_values=True)
    required = {
        "currency",
        "symbols",
        "timeframe",
        "start",
        "end",
        "feed",
        "adjustment",
        "asof",
        "sort",
        "limit",
    }
    if (
        url.scheme != "https"
        or url.netloc != "data.alpaca.markets"
        or url.path != BARS
        or url.fragment
        or not required <= set(values)
        or set(values) - required - {"page_token"}
        or any(len(v) != 1 for v in values.values())
        or any(
            values[k] != [v]
            for k, v in {
                "timeframe": "1Hour",
                "feed": "iex",
                "currency": "USD",
                "asof": "-",
                "sort": "asc",
                "limit": "10000",
            }.items()
        )
        or source.provider != "alpaca-iex-hourly"
    ):
        raise ValueError("Invalid Alpaca page provenance.")
    return BarsQuery(
        tuple(values["symbols"][0].split(",")),
        stamp(values["start"][0]),
        stamp(values["end"][0]),
        values["adjustment"][0],
    )


def page_cursor(source: Source) -> str | None:
    return parse_qs(urlsplit(source.url).query).get("page_token", [None])[0]
