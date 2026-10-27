"""Conservative, per-client pacing and server-directed cooldowns."""

import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


class RateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep
        self.next_request = 0.0

    def defer(self, seconds: float) -> None:
        self.next_request = max(self.next_request, self.clock() + seconds)

    def wait(self) -> None:
        delay = max(0.0, self.next_request - self.clock())
        if delay > 300:
            raise ValueError("Server cooldown exceeds automatic wait budget.")
        if delay:
            self.sleep(delay)
        # One request per second across both endpoints (including retries).
        self.next_request = self.clock() + 1.0


def retry_delay(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            seconds = (date - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0
