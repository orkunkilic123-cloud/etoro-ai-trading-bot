"""Immutable, bounded, point-in-time scenario inputs."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal as D

from ..risk.models import money
from ..scanner.models import aware
from ..strategy.journal import digest


@dataclass(frozen=True)
class Move:
    """OHLC ratios to the previous close, including open/previous-close gaps."""

    open: D
    high: D
    low: D
    close: D


@dataclass(frozen=True)
class Block:
    """One complete horizon; internal ordering/dependence is preserved."""

    start: datetime
    end: datetime
    known_at: datetime
    moves: tuple[Move, ...]


@dataclass(frozen=True)
class Pool:
    instrument_id: int
    classification: str
    source: str
    source_sha256: str
    horizon_seconds: int
    blocks: tuple[Block, ...]

    def validate(self, now: datetime, instrument_id: int) -> None:
        if (
            not aware(now)
            or self.instrument_id != instrument_id
            or self.classification != "synthetic"
            or not self.source.startswith("SYNTHETIC")
            or len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
            or type(self.horizon_seconds) is not int
            or not 1 <= self.horizon_seconds <= 7 * 86400
            or type(self.blocks) is not tuple
            or not 20 <= len(self.blocks) <= 10000
        ):
            raise ValueError("INVALID_OR_UNVERIFIED_SIMULATION_POOL")
        if digest([asdict(b) for b in self.blocks]) != self.source_sha256:
            raise ValueError("POOL_CHECKSUM_MISMATCH")
        previous = None
        for block in self.blocks:
            if (
                not all(aware(t) for t in (block.start, block.end, block.known_at))
                or not block.start < block.end <= block.known_at <= now
                or (block.end - block.start).total_seconds() != self.horizon_seconds
                or (previous is not None and block.start < previous)
                or type(block.moves) is not tuple
                or not 1 <= len(block.moves) <= 128
            ):
                raise ValueError("INVALID_OR_FUTURE_BLOCK")
            previous = block.end
            for m in block.moves:
                if (
                    not all(
                        money(v, positive=True) and D(".01") <= v <= 10
                        for v in (m.open, m.high, m.low, m.close)
                    )
                    or not m.low <= min(m.open, m.close) <= max(m.open, m.close) <= m.high
                ):
                    raise ValueError("INVALID_OHLC_RATIOS")


@dataclass(frozen=True)
class Settings:
    seed: int = 19
    trials: int = 10000

    def __post_init__(self) -> None:
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise ValueError("INVALID_SEED")
        if type(self.trials) is not int or self.trials != 10000:
            raise ValueError("EXACTLY_10000_TRIALS_REQUIRED")


@dataclass(frozen=True)
class Trial:
    index: int
    sampled_block: int
    outcome: str
    exit_step: int
    exit_price: D
    pnl_usd: D
    costs_usd: D
    portfolio_pnl_eur: D
