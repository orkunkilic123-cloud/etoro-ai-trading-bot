"""Strict documented daily CSV and explicit provider-neutral file imports; no key loading."""

import csv
import hashlib
import io
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from .models import Bar, ExchangeCalendar, HistoricalProvider, History, Source


def number(value: str, *, zero: bool = False) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid historical numeric value.") from None
    if not result.is_finite() or result < 0 or not zero and result == 0:
        raise ValueError("Invalid historical numeric value.")
    return result


def stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Historical timestamps must have explicit timezone offsets.")
    return result.astimezone(UTC)


def check_source(raw: bytes, source: Source) -> None:
    if (
        source.classification not in ("historical_observation", "synthetic")
        or not source.provider
        or not source.url
        or not source.terms_url
        or not source.license_note
        or source.retrieved_at.tzinfo is None
        or source.retrieved_at.utcoffset() is None
        or hashlib.sha256(raw).hexdigest() != source.raw_sha256
    ):
        raise ValueError("Invalid historical source provenance or checksum.")


class AlphaVantageDaily:
    """Raw TIME_SERIES_DAILY CSV, never adjusted-close substitution."""

    def __init__(self, symbol: str, calendar: ExchangeCalendar) -> None:
        if not symbol or not symbol.isascii() or not all(c.isalnum() or c in ".-" for c in symbol):
            raise ValueError("Invalid symbol.")
        self.symbol, self.calendar = symbol, calendar

    def parse(self, raw: bytes, source: Source) -> History:
        check_source(raw, source)
        if source.symbol != self.symbol:
            raise ValueError("Source symbol does not match requested history.")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != ["timestamp", "open", "high", "low", "close", "volume"]:
            raise ValueError(
                "Unexpected daily schema; error bodies and adjusted series are rejected."
            )
        bars = []
        for row in reader:
            day = date.fromisoformat(row["timestamp"])
            sessions = self.calendar.sessions(day, day)
            if len(sessions) != 1:
                raise ValueError("Daily candle falls outside the reviewed exchange calendar.")
            session = sessions[0]
            bars.append(
                Bar(
                    session.opens,
                    session.closes,
                    number(row["open"]),
                    number(row["high"]),
                    number(row["low"]),
                    number(row["close"]),
                    number(row["volume"], zero=True),
                    source.retrieved_at,
                    "raw",
                )
            )
        if not bars:
            raise ValueError("Empty daily response.")
        return History(
            self.symbol,
            "XNYS",
            "USD",
            "1d",
            "raw",
            tuple(sorted(bars, key=lambda b: b.start)),
            source,
        )


class CSVHistory:
    """User-supplied licensed export contract; not an undocumented vendor API."""

    def __init__(
        self, *, symbol: str, exchange: str, currency: str, resolution: str, basis: str
    ) -> None:
        if resolution not in ("1d", "1h") or basis not in (
            "raw",
            "split_adjusted",
            "total_return_adjusted",
            "unknown",
        ):
            raise ValueError("Unsupported resolution or price basis.")
        self.symbol, self.exchange, self.currency, self.resolution, self.basis = (
            symbol,
            exchange,
            currency,
            resolution,
            basis,
        )

    def parse(self, raw: bytes, source: Source) -> History:
        check_source(raw, source)
        if source.symbol != self.symbol:
            raise ValueError("Source symbol does not match requested history.")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if reader.fieldnames != [
            "start",
            "end",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "known_at",
        ]:
            raise ValueError("Unexpected normalized historical CSV schema.")
        bars = []
        for row in reader:
            values = [number(row[k]) for k in ("open", "high", "low", "close")]
            known = stamp(row["known_at"]) if row["known_at"] else source.retrieved_at
            bars.append(
                Bar(
                    stamp(row["start"]),
                    stamp(row["end"]),
                    values[0],
                    values[1],
                    values[2],
                    values[3],
                    number(row["volume"], zero=True) if row["volume"] else None,
                    known,
                    self.basis,
                )
            )
        return History(
            self.symbol,
            self.exchange,
            self.currency,
            self.resolution,
            self.basis,
            tuple(bars),
            source,
        )


class Providers:
    def __init__(self) -> None:
        self._providers: dict[str, HistoricalProvider] = {}

    def register(self, name: str, provider: HistoricalProvider) -> None:
        if name in self._providers:
            raise ValueError("Provider already registered.")
        self._providers[name] = provider

    def parse(self, name: str, raw: bytes, source: Source) -> History:
        return self._providers[name].parse(raw, source)


def ecb_usd_reference(raw: bytes, source: Source) -> tuple[tuple[date, Decimal], ...]:
    """Reference FX observations, not executable rates or historical availability evidence."""
    check_source(raw, source)
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("XML declarations are forbidden.")
    root = ElementTree.fromstring(raw)
    result: dict[date, Decimal] = {}
    for element in root.iter():
        if "time" not in element.attrib:
            continue
        day = date.fromisoformat(element.attrib["time"])
        for child in element:
            if child.attrib.get("currency") == "USD":
                if day in result:
                    raise ValueError("Duplicate FX date.")
                result[day] = number(child.attrib["rate"])
    if not result:
        raise ValueError("No USD reference data.")
    return tuple(sorted(result.items()))
