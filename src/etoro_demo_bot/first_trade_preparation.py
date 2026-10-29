"""Offline first-Demo-trade preparation. No credentials, network, or submission."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TradeEvidence:
    """Externally validated safety attestations, all false until verified."""

    demo_identity: bool = False
    account_fresh_complete: bool = False
    cash_reconciled: bool = False
    positions_reconciled: bool = False
    quote_fresh: bool = False
    eligibility_confirmed: bool = False
    order_minimum_verified: bool = False
    v3_contract_verified: bool = False
    owner_approval_interface_verified: bool = False
    risk_engine_passed: bool = False
    kill_switch_clear: bool = False
    daily_loss_not_halted: bool = False
    duplicate_and_unknown_orders_reconciled: bool = False


@dataclass(frozen=True)
class Preparation:
    blockers: tuple[str, ...]
    ready_to_request_owner_approval: bool
    execution_authorized: bool = False


def prepare_first_demo_trade(evidence: TradeEvidence) -> Preparation:
    """Conservative offline gate; approval and execution are always unavailable."""
    if not isinstance(evidence, TradeEvidence):
        raise TypeError("Expected TradeEvidence")
    blockers: list[str] = []
    for name in TradeEvidence.__dataclass_fields__:
        value = getattr(evidence, name)
        if type(value) is not bool:
            raise TypeError("Evidence must be explicit booleans")
        if not value:
            blockers.append(name)
    return Preparation(tuple(blockers), not blockers)
