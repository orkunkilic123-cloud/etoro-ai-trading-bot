"""Offline broker evidence gate for first Demo order integration.

This deliberately cannot normalize unknown broker shapes into trusted risk inputs.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .risk.models import AccountSnapshot, Exposure


@dataclass(frozen=True)
class BrokerEvidence:
    demo_key_scope_verified: bool = False
    account_identity_attested: bool = False
    balance_complete_fresh: bool = False
    positions_complete_fresh: bool = False
    cash_reservations_reconciled: bool = False
    eligibility_fresh: bool = False
    minimum_order_verified: bool = False
    quote_fresh: bool = False
    official_order_contract_verified: bool = False
    manual_approval_bound: bool = False
    existing_risk_pass: bool = False
    no_unknown_prior_order: bool = False


@dataclass(frozen=True)
class IntegrationGate:
    missing: tuple[str, ...]
    valid_evidence: bool
    may_submit: bool = False


def verify_evidence(evidence: BrokerEvidence) -> IntegrationGate:
    """Return missing evidence only. Never grant permission to submit."""
    if not isinstance(evidence, BrokerEvidence):
        raise TypeError("BrokerEvidence required")
    missing: list[str] = []
    for name in BrokerEvidence.__dataclass_fields__:
        flag = getattr(evidence, name)
        if type(flag) is not bool:
            raise TypeError("Evidence flags must be booleans")
        if not flag:
            missing.append(name)
    return IntegrationGate(tuple(missing), not missing)


def prepare_risk_snapshot(
    evidence: BrokerEvidence,
    *,
    account_id: str,
    equity: Decimal,
    available_balance: Decimal,
    exposures: tuple[Exposure, ...],
    observed_at: datetime,
) -> AccountSnapshot:
    """Build an explicitly untrusted risk observation, never admission.

    The upstream evidence flags cannot prove broker source authenticity.
    Completeness and cash-flow reconciliation remain false until a separately
    reviewed authoritative attestation integration exists.
    """
    from datetime import UTC, timedelta

    from .risk.models import identifier, money

    gate = verify_evidence(evidence)
    if (
        not gate.valid_evidence
        or not identifier(account_id)
        or not money(equity, positive=True)
        or not money(available_balance)
        or available_balance > equity
        or not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or not isinstance(exposures, tuple)
    ):
        raise ValueError("Unverified broker observations")
    now = datetime.now(UTC)
    age = now - observed_at.astimezone(UTC)
    if age < timedelta(0) or age > timedelta(seconds=60):
        raise ValueError("Stale broker observations")
    for exposure in exposures:
        if (
            not isinstance(exposure, Exposure)
            or type(exposure.instrument_id) is not int
            or exposure.instrument_id <= 0
            or not money(exposure.notional, positive=True)
            or type(exposure.positions) is not int
            or exposure.positions <= 0
        ):
            raise ValueError("Invalid broker exposure")
    return AccountSnapshot(
        account_id=account_id,
        equity=equity,
        available_balance=available_balance,
        exposures=exposures,
        observed_at=observed_at,
        demo=True,
        complete=False,
        cash_flows_reconciled=False,
    )
