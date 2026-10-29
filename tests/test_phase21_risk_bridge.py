"""Offline observation-to-risk integration tests without broker access."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from etoro_demo_bot.broker_evidence_gate import (
    BrokerEvidence,
    prepare_risk_snapshot,
)
from etoro_demo_bot.risk.models import Exposure


def evidence() -> BrokerEvidence:
    return BrokerEvidence(**{field.name: True for field in fields(BrokerEvidence)})


def sample(now: datetime) -> dict[str, object]:
    return {
        "account_id": "synthetic-demo",
        "equity": Decimal("10000"),
        "available_balance": Decimal("9000"),
        "exposures": (Exposure(1, Decimal("1000"), 1),),
        "observed_at": now,
    }


def test_verified_observation_produces_risk_snapshot_not_authorization() -> None:
    now = datetime.now(UTC)
    result = prepare_risk_snapshot(evidence(), **sample(now))  # type: ignore[arg-type]
    assert result.demo is True
    assert result.complete is False
    assert result.cash_flows_reconciled is False
    assert result.available_balance == Decimal("9000")


def test_unverified_evidence_cannot_enter_risk() -> None:
    with pytest.raises(ValueError, match="Unverified"):
        prepare_risk_snapshot(BrokerEvidence(), **sample(datetime.now(UTC)))  # type: ignore[arg-type]


@pytest.mark.parametrize("replacement", [
    {"account_id": ""},
    {"equity": Decimal("NaN")},
    {"available_balance": Decimal("20000")},
    {"exposures": (Exposure(0, Decimal("10"), 1),)},
    {"exposures": (Exposure(1, Decimal("10"), 0),)},
])
def test_invalid_broker_observations_rejected(replacement: dict[str, object]) -> None:
    kwargs = sample(datetime.now(UTC)) | replacement
    with pytest.raises(ValueError):
        prepare_risk_snapshot(evidence(), **kwargs)  # type: ignore[arg-type]


def test_stale_broker_observation_rejected() -> None:
    with pytest.raises(ValueError, match="Stale"):
        prepare_risk_snapshot(
            evidence(),
            **sample(datetime.now(UTC) - timedelta(seconds=61)),  # type: ignore[arg-type]
        )


def test_future_broker_observation_rejected() -> None:
    with pytest.raises(ValueError, match="Stale"):
        prepare_risk_snapshot(
            evidence(),
            **sample(datetime.now(UTC) + timedelta(minutes=2)),  # type: ignore[arg-type]
        )
