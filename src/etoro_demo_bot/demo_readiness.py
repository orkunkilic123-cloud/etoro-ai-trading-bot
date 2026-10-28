"""Offline, fail-closed Phase 17 Demo-readiness assessment.

No broker client, environment credentials, filesystem writes or network access.
An assessment is not an order authorization.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoEvidence:
    """External attestations. Defaults deliberately deny readiness."""

    official_contract_reviewed: bool = False
    demo_read_key_scope_verified: bool = False
    demo_identity_verified: bool = False
    demo_portfolio_complete: bool = False
    demo_cash_reconciled: bool = False
    instrument_eligibility_verified: bool = False
    quotes_fresh: bool = False
    costs_verified: bool = False
    daily_baseline_verified: bool = False
    kill_switch_reviewed: bool = False


@dataclass(frozen=True)
class Readiness:
    read_only_ready: bool
    trade_preparation_ready: bool
    blockers: tuple[str, ...]
    execution_authorized: bool = False


def assess(evidence: DemoEvidence) -> Readiness:
    """Return deterministic blockers; never grant execution authority."""
    if not isinstance(evidence, DemoEvidence):
        raise TypeError("Expected DemoEvidence")
    checks = (
        ("official_contract_unverified", evidence.official_contract_reviewed),
        ("demo_read_scope_unverified", evidence.demo_read_key_scope_verified),
        ("demo_identity_unverified", evidence.demo_identity_verified),
        ("demo_portfolio_incomplete", evidence.demo_portfolio_complete),
        ("demo_cash_unreconciled", evidence.demo_cash_reconciled),
        ("instrument_eligibility_unverified", evidence.instrument_eligibility_verified),
        ("quotes_unverified_or_stale", evidence.quotes_fresh),
        ("costs_unverified", evidence.costs_verified),
        ("daily_baseline_unverified", evidence.daily_baseline_verified),
        ("kill_switch_unreviewed", evidence.kill_switch_reviewed),
    )
    for _, value in checks:
        if type(value) is not bool:
            raise TypeError("Evidence must be explicit booleans")
    blockers = tuple(name for name, passed in checks if not passed)
    # Documentation/contract evidence is necessary even before a private read.
    read_only_ready = all(
        (
            evidence.official_contract_reviewed,
            evidence.demo_read_key_scope_verified,
            evidence.demo_identity_verified,
        )
    )
    return Readiness(
        read_only_ready=read_only_ready,
        trade_preparation_ready=not blockers,
        blockers=blockers,
    )
