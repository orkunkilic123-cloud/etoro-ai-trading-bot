"""Offline-only paper orchestration safety primitives. No broker transport or order submission."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class Decision(str, Enum):
    HALT = "halt"
    RECONCILE = "reconcile"
    OBSERVE = "observe"


@dataclass(frozen=True)
class PaperSnapshot:
    account_mode: str
    broker_reconciled: bool
    kill_switch: bool
    daily_loss_fraction: float
    pending_order_uncertain: bool
    last_heartbeat: datetime


def assess(snapshot: PaperSnapshot, now: datetime) -> Decision:
    """Fail closed; never grants trade authorization."""
    if now.tzinfo is None or snapshot.last_heartbeat.tzinfo is None:
        return Decision.HALT
    if snapshot.account_mode != "paper" or snapshot.kill_switch:
        return Decision.HALT
    if not (0 <= snapshot.daily_loss_fraction < 0.03):
        return Decision.HALT
    if snapshot.last_heartbeat > now or (now - snapshot.last_heartbeat).total_seconds() > 120:
        return Decision.HALT
    if snapshot.pending_order_uncertain or not snapshot.broker_reconciled:
        return Decision.RECONCILE
    return Decision.OBSERVE
