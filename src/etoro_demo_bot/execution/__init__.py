"""Opt-in, manually authorized Demo execution. No autonomous runner or credential loading."""

from .client import DemoExecutionClient, credential_digest
from .engine import ExecutionEngine
from .journal import install_journal
from .models import (
    DemoIdentity,
    ExecutionConfig,
    ExecutionError,
    OrderRecord,
    OrderState,
    PositionEvidence,
    Ticket,
)

__all__ = [
    "DemoExecutionClient",
    "DemoIdentity",
    "ExecutionConfig",
    "ExecutionEngine",
    "ExecutionError",
    "OrderRecord",
    "OrderState",
    "PositionEvidence",
    "Ticket",
    "credential_digest",
    "install_journal",
]
