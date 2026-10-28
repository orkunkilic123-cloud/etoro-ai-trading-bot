"""Bounded current NYSE schedule, explicitly not an archived historical publication."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Session


class NYSE2026:
    source_url = "https://www.nyse.com/markets/hours-calendars"

    def __init__(self, *, verified_at: datetime) -> None:
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            raise ValueError("Calendar verification time must be timezone-aware.")
        self.verified_at = verified_at
        self.zone = ZoneInfo("America/New_York")

    def sessions(self, start: date, end: date) -> tuple[Session, ...]:
        if start.year != 2026 or end.year != 2026 or end < start:
            raise ValueError("Only the reviewed 2026 NYSE schedule is supported.")
        holidays = {
            date(2026, m, d)
            for m, d in (
                (1, 1),
                (1, 19),
                (2, 16),
                (4, 3),
                (5, 25),
                (6, 19),
                (7, 3),
                (9, 7),
                (11, 26),
                (12, 25),
            )
        }
        early = {date(2026, 11, 27), date(2026, 12, 24)}
        days = []
        day = start
        while day <= end:
            if day.weekday() < 5 and day not in holidays:
                days.append(
                    Session(
                        day,
                        datetime.combine(day, time(9, 30), self.zone).astimezone(UTC),
                        datetime.combine(
                            day, time(13 if day in early else 16), self.zone
                        ).astimezone(UTC),
                    )
                )
            day += timedelta(days=1)
        return tuple(days)
