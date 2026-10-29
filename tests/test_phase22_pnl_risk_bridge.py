"""Offline integration of documented Demo P&L cash into existing risk adapter."""

from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from etoro_demo_bot.broker_evidence_gate import (
    BrokerEvidence,
    prepare_pnl_risk_observation,
)
from etoro_demo_bot.demo_cash import IncompleteDemoSnapshot
from etoro_demo_bot.risk.models import Exposure


def _evidence() -> BrokerEvidence:
    return BrokerEvidence(**{item.name: True for item in fields(BrokerEvidence)})


def _pnl() -> dict[str, object]:
    return {
        "credit": "1000",
        "ordersForOpen": [{"mirrorID": 0, "amount": "100"}],
        "orders": [{"amount": "50"}],
    }


def test_pnl_cash_feeds_existing_risk_shape_without_trust() -> None:
    observed = prepare_pnl_risk_observation(
        _evidence(),
        pnl_response=_pnl(),
        account_id="synthetic-demo",
        equity=Decimal("1500"),
        exposures=(Exposure(1, Decimal("600"), 1),),
        observed_at=datetime.now(UTC),
    )
    assert observed.available_balance == Decimal("850")
    assert observed.demo
    assert not observed.complete
    assert not observed.cash_flows_reconciled


@pytest.mark.parametrize(
    "bad",
    [
        {"credit": "1000", "ordersForOpen": []},
        {"credit": "1000", "ordersForOpen": [], "orders": [{"amount": "1001"}]},
        {"credit": "NaN", "ordersForOpen": [], "orders": []},
    ],
)
def test_partial_or_unsafe_pnl_blocks(bad: dict[str, object]) -> None:
    with pytest.raises(IncompleteDemoSnapshot):
        prepare_pnl_risk_observation(
            _evidence(),
            pnl_response=bad,
            account_id="synthetic-demo",
            equity=Decimal("1500"),
            exposures=(),
            observed_at=datetime.now(UTC),
        )


def test_missing_broker_attestation_blocks() -> None:
    with pytest.raises(ValueError, match="Unverified"):
        prepare_pnl_risk_observation(
            BrokerEvidence(),
            pnl_response=_pnl(),
            account_id="synthetic-demo",
            equity=Decimal("1500"),
            exposures=(),
            observed_at=datetime.now(UTC),
        )


def test_documented_envelope_and_precision() -> None:
    from decimal import localcontext

    from etoro_demo_bot.demo_cash import normalize_demo_pnl_response

    payload = {
        "clientPortfolio": {
            "credit": "1000.123456",
            "ordersForOpen": [{"mirrorId": 0, "amount": "100.000001"}],
            "orders": [{"amount": "50.000002"}],
        }
    }
    with localcontext() as context:
        context.prec = 4
        result = normalize_demo_pnl_response(payload)
    assert result.available_cash == Decimal("850.123453")
    assert not result.trusted_for_risk


def test_duplicate_exposures_rejected() -> None:
    with pytest.raises(ValueError, match="exposure"):
        prepare_pnl_risk_observation(
            _evidence(),
            pnl_response=_pnl(),
            account_id="synthetic-demo",
            equity=Decimal("1500"),
            exposures=(Exposure(1, Decimal(10), 1),) * 2,
            observed_at=datetime.now(UTC),
        )


def test_normalized_observation_cannot_pass_real_risk(tmp_path: Path) -> None:
    from etoro_demo_bot.risk import Proposal, RiskEngine, RiskStore

    now = datetime.now(UTC)
    snapshot = prepare_pnl_risk_observation(
        _evidence(),
        pnl_response=_pnl(),
        account_id="synthetic-demo",
        equity=Decimal("1500"),
        exposures=(),
        observed_at=now,
    )
    store = RiskStore.initialize(tmp_path / "risk.sqlite", "synthetic-demo")
    store.establish_day(now.date(), snapshot.equity)
    decision = RiskEngine(store).evaluate(
        Proposal("synthetic", 1, Decimal(1), Decimal(10), Decimal(9), now, Decimal(0)),
        snapshot,
        now=now,
    )
    assert not decision.passed
    assert not decision.execution_authorized
