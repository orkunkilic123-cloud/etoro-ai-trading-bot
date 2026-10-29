"""Bounded SEC Atom parsing with separate reported, updated and observation clocks."""

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

ATOM = "{http://www.w3.org/2005/Atom}"
MAX_BYTES = 2 * 1024 * 1024


class NewsError(ValueError):
    """Fixed diagnostic codes, never feed bodies or external exception content."""


def timestamp(value: str) -> datetime:
    result = None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            result = parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        pass
    if result is None:
        # Outside the handler: no source timestamp or upstream exception context leaks.
        raise NewsError("INVALID_EVENT_TIME")
    return result


def sec_url(value: str, *, feed: bool = False) -> str:
    try:
        url = urlsplit(value)
        valid = (
            url.scheme == "https"
            and url.hostname in ("sec.gov", "www.sec.gov")
            and not url.username
            and not url.password
            and url.port in (None, 443)
            and not url.fragment
            and (
                url.path == "/cgi-bin/browse-edgar"
                if feed
                else url.path.startswith("/Archives/edgar/data/")
            )
        )
    except ValueError:
        valid = False
    if not valid or len(value) > 2048 or any(ord(c) <= 32 for c in value):
        raise NewsError("INVALID_SEC_SOURCE")
    return value


@dataclass(frozen=True)
class FilingEvent:
    source_id: str
    source_url: str
    title: str
    form: str
    published_at: datetime | None
    updated_at: datetime
    observed_at: datetime
    publication_basis: str
    keyword_tags: tuple[str, ...]


def parse_atom(raw: bytes, *, source: str, observed_at: datetime) -> tuple[FilingEvent, ...]:
    """Parse saved bytes only. Missing event/coverage is never absence of earnings."""
    sec_url(source, feed=True)
    observed = timestamp(observed_at.isoformat())
    if not raw or len(raw) > MAX_BYTES:
        raise NewsError("FEED_SIZE_INVALID")
    root = None
    try:
        text = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise NewsError("XML_DECLARATIONS_FORBIDDEN")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError):
        pass
    if root is None or root.tag != ATOM + "feed":
        raise NewsError("INVALID_ATOM_FEED")
    entries = root.findall(ATOM + "entry")
    if len(entries) > 1000:
        raise NewsError("TOO_MANY_EVENTS")
    events = []
    seen = set()
    for entry in entries:
        identity = (entry.findtext(ATOM + "id") or "").strip()
        title = (entry.findtext(ATOM + "title") or "").strip()
        if not identity or len(identity) > 1024 or not title or len(title) > 4096:
            raise NewsError("EVENT_ID_OR_TITLE_MISSING")
        if identity in seen:
            raise NewsError("DUPLICATE_EVENT_IN_FEED")
        seen.add(identity)
        updated = timestamp(entry.findtext(ATOM + "updated") or "")
        published_text = entry.findtext(ATOM + "published")
        published = timestamp(published_text) if published_text else None
        if updated > observed or (published is not None and published > updated):
            raise NewsError("FUTURE_OR_INCONSISTENT_EVENT")
        links = [
            link.get("href", "")
            for link in entry.findall(ATOM + "link")
            if link.get("rel", "alternate") == "alternate"
        ]
        if len(links) != 1:
            raise NewsError("AMBIGUOUS_EVENT_SOURCE")
        link = sec_url(links[0])
        category = entry.find(ATOM + "category")
        form = category.get("term", "") if category is not None else ""
        if len(form) > 64:
            raise NewsError("INVALID_FORM")
        # Tags describe matching words only. Never sentiment, earnings date or importance.
        tags = tuple(
            word
            for word in ("earnings", "results", "dividend", "merger")
            if re.search(r"\b" + word + r"\b", title, re.IGNORECASE)
        )
        events.append(
            FilingEvent(
                identity,
                link,
                title,
                form,
                published,
                updated,
                observed,
                "published" if published_text else "updated_only",
                tags,
            )
        )
    return tuple(events)


def raw_checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
