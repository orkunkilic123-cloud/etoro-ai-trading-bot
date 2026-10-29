"""Offline broker evidence gate for first Demo order integration.

This deliberately cannot normalize unknown broker shapes into trusted risk inputs.
"""

from dataclasses import dataclass


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
