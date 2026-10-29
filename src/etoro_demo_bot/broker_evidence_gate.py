"""Offline broker evidence gate for first Demo order integration.

This deliberately cannot normalize unknown broker shapes into trusted risk inputs.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .demo_cash import DemoCashObservation, normalize_demo_cash, normalize_demo_pnl_response
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
    seen: set[int] = set()
    for exposure in exposures:
        if (
            not isinstance(exposure, Exposure)
            or type(exposure.instrument_id) is not int
            or exposure.instrument_id <= 0
            or exposure.instrument_id in seen
            or not money(exposure.notional, positive=True)
            or type(exposure.positions) is not int
            or exposure.positions <= 0
        ):
            raise ValueError("Invalid broker exposure")
        seen.add(exposure.instrument_id)
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


def prepare_pnl_risk_observation(
    evidence: BrokerEvidence,
    *,
    pnl_response: dict[str, object],
    account_id: str,
    equity: Decimal,
    exposures: tuple[Exposure, ...],
    observed_at: datetime,
) -> AccountSnapshot:
    """Connect documented Demo P&L cash parsing to the existing risk bridge.

    This does not authenticate a payload or certify its account or position
    identity. Therefore the risk snapshot stays incomplete and non-admissible.
    """
    cash: DemoCashObservation = (
        normalize_demo_pnl_response(pnl_response)
        if "clientPortfolio" in pnl_response
        else normalize_demo_cash(pnl_response)
    )
    if cash.trusted_for_risk:
        raise ValueError("Unexpected trusted broker cash")
    return prepare_risk_snapshot(
        evidence,
        account_id=account_id,
        equity=equity,
        available_balance=cash.available_cash,
        exposures=exposures,
        observed_at=observed_at,
    )
