"""Versioned temporal interfaces. Five-minute inputs can never enable trading."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class Timeframe(StrEnum):
    HOUR = "1Hour"
    FIVE_MINUTES = "5Min"

    @property
    def duration(self) -> timedelta:
        return timedelta(hours=1) if self is Timeframe.HOUR else timedelta(minutes=5)

    @property
    def resolution(self) -> str:
        return "1h" if self is Timeframe.HOUR else "5m"


@dataclass(frozen=True)
class BarContract:
    timeframe: Timeframe = Timeframe.HOUR
    version: str = "bar-contract-v1"
    exchange: str = "XNYS"
    timezone: str = "America/New_York"
    alignment: str = "provider-native"
    research_only: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.timeframe) is not Timeframe
            or self.version != "bar-contract-v1"
            or self.exchange != "XNYS"
            or self.timezone != "America/New_York"
            or self.alignment not in ("provider-native", "regular-session-full-bars-v1")
            or type(self.research_only) is not bool
            or self.timeframe is Timeframe.FIVE_MINUTES
            and not self.research_only
        ):
            raise ValueError("INVALID_TEMPORAL_CONTRACT")


HOURLY_BASELINE = BarContract()
FIVE_MINUTE_RESEARCH = BarContract(
    Timeframe.FIVE_MINUTES, alignment="regular-session-full-bars-v1", research_only=True
)


def require_hourly_baseline(contract: BarContract) -> None:
    """Existing consumers reject new semantics until separately implemented and reviewed."""
    if type(contract) is not BarContract:
        raise ValueError("TIMEFRAME_OR_SESSION_INCOMPATIBLE")
    contract.__post_init__()
    if contract != HOURLY_BASELINE:
        raise ValueError("TIMEFRAME_OR_SESSION_INCOMPATIBLE")
