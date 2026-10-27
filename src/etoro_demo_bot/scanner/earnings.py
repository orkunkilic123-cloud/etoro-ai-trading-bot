"""Versioned persistent analysis cache for a future free, verified Earnings provider."""

from datetime import datetime

from .client import timestamp
from .models import EarningsProvider, FundamentalAnalysis, ScanError, aware
from .storage import ScanStore


class CachedEarnings:
    def __init__(self, provider: EarningsProvider, store: ScanStore, *, version: str) -> None:
        if not version:
            raise ScanError("EARNINGS_VERSION_REQUIRED")
        self.provider, self.store, self.version = provider, store, version

    async def analysis(self, instrument_id: int, now: datetime) -> FundamentalAnalysis | None:
        if not aware(now):
            raise ScanError("INVALID_TIMESTAMP")
        key = f"earnings:{self.version}:{instrument_id}"
        result: FundamentalAnalysis | None
        cached = self.store.get(key, now.timestamp())
        if cached is not None:
            facts = cached.get("facts")
            if not isinstance(facts, list) or any(
                not isinstance(x, list) or len(x) != 2 or any(not isinstance(y, str) for y in x)
                for x in facts
            ):
                raise ScanError("CACHE_INVALID")
            result = FundamentalAnalysis(
                instrument_id,
                self.version,
                str(cached["source"]),
                timestamp(cached["as_of"]),
                timestamp(cached["expires_at"]),
                tuple((x[0], x[1]) for x in facts),
            )
        else:
            result = await self.provider.analysis(instrument_id, now)
        if result is None:
            return None
        if (
            result.instrument_id != instrument_id
            or result.version != self.version
            or not result.source
            or not aware(result.as_of)
            or not aware(result.expires_at)
            or not result.as_of <= now < result.expires_at
        ):
            raise ScanError("INVALID_FUNDAMENTALS")
        if cached is None:
            self.store.put(
                key,
                {
                    "source": result.source,
                    "as_of": result.as_of.isoformat(),
                    "expires_at": result.expires_at.isoformat(),
                    "facts": result.facts,
                },
                now.timestamp(),
                (result.expires_at - now).total_seconds(),
            )
        return result
