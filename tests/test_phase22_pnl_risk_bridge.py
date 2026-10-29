"""Offline integration of documented Demo P&L cash into existing risk adapter."""

from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal

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
