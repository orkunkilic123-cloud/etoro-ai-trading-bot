"""Synthetic public-schema responses, no broker or credential access."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.broker_diagnostics import DiagnosticError, diagnose, main, parse_pnl
from etoro_demo_bot.execution.journal import install_journal
from etoro_demo_bot.risk import RiskStore

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def samples() -> tuple[dict[str, Any], dict[str, Any]]:
    p = {
        "accountCurrencyId": 1,
        "credit": "1000",
        "bonusCredit": "0",
        "unrealizedPnL": "10",
        "mirrors": [],
        "ordersForClose": [],
        "ordersForCloseMultiple": [],
        "stockOrders": [],
        "entryOrders": [],
        "exitOrders": [],
        "orders": [],
        "ordersForOpen": [
            {
                "orderId": 7,
                "instrumentId": 1,
                "cid": 42,
                "mirrorId": 0,
                "amount": "100",
                "isBuy": True,
                "leverage": 1,
            }
        ],
        "positions": [
            {
                "positionID": 11,
                "instrumentID": 1,
                "CID": 42,
                "mirrorID": 0,
                "settlementTypeID": 1,
                "isBuy": True,
                "leverage": 1,
                "amount": "200",
                "units": "2",
                "unrealizedPnL": {
                    "pnL": "10",
                    "exposureInAccountCurrency": "210",
                    "timestamp": NOW.isoformat(),
                },
            }
        ],
    }
    a = {
        "cid": 42,
        "timestamp": NOW.isoformat(),
        "accountCurrency": "USD",
        "mirrors": [],
        "accountTotals": {
            "accountBalance": "1000",
            "accountAvailableCash": "900",
            "accountFrozenCash": "100",
            "accountTotalUsedMargin": "300",
            "accountCurrentPnl": "10",
            "accountTotalValue": "1210",
        },
        "instrumentAggregates": [{"instrumentId": 1, "netCurrentExposureAccountCurrency": "210"}],
    }
    return {"clientPortfolio": p}, a


def state(path: Path, *, pending: bool = True, broker_id: int | None = 7) -> RiskStore:
    store = RiskStore.initialize(path, "synthetic-local-account")
    store.establish_day(NOW.date(), D(1210))
    install_journal(store)
    if pending:
        with store.transaction() as db:
            db.execute("INSERT INTO reservations VALUES(?,?,?,?)", ("p1", "hash", 1, "120"))
            ticket = json.dumps(
                {
                    "account_id": "synthetic-local-account",
                    "action": "open",
                    "proposal": {"proposal_id": "p1", "instrument_id": 1},
                }
            )
            db.execute(
                "INSERT INTO execution_orders(id,account,digest,ticket,reference,state,broker_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    "o1",
                    "synthetic-local-account",
                    hashlib.sha256(ticket.encode()).hexdigest(),
                    ticket,
                    "reference",
                    "unknown",
                    broker_id,
                ),
            )
    return store


def test_pnl_aggregate_local_holds_and_actual_risk_fail_closed(tmp_path: Path) -> None:
    p, a = samples()
    path = tmp_path / "risk.sqlite"
    state(path)
    before = path.read_bytes()
    result = diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)
    assert result.snapshot.equity == D(1210)
    assert result.snapshot.available_balance == D(780)  # all local holds retained
    assert result.snapshot.exposures[0].notional == D(210)
    assert result.matched_reservations == 1 and result.local.unresolved == 1
    assert not result.snapshot.demo and not result.snapshot.complete
    assert not result.snapshot.cash_flows_reconciled
    assert result.decision.reasons == ("INVALID_ACCOUNT",)
    assert not result.decision.execution_authorized
    assert path.read_bytes() == before
    summary = json.dumps(result.summary())
    assert "synthetic-local-account" not in summary
    assert "1210" not in summary and "780" not in summary and "reference" not in summary
    assert result.summary()["kill_switch_active"] is True


def test_unknown_submission_without_broker_id_keeps_entire_hold(tmp_path: Path) -> None:
    p, a = samples()
    path = tmp_path / "risk.sqlite"
    state(path, broker_id=None)
    result = diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)
    assert result.unmatched_reservations == 1 and result.snapshot.available_balance == D(780)
    assert result.local.unresolved == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "currency",
        "missing",
        "duplicate_position",
        "duplicate_order",
        "mixed_customer",
        "position_pnl",
        "stale",
        "short",
        "leverage",
        "cfd",
        "copy",
        "bonus",
        "stock_order",
        "float",
        "camel_case",
    ],
)
def test_rejects_unsupported_or_inconsistent_pnl(mutation: str) -> None:
    payload, _ = samples()
    p = payload["clientPortfolio"]
    if mutation == "currency":
        p["accountCurrencyId"] = 2
    elif mutation == "missing":
        del p["positions"]
    elif mutation == "duplicate_position":
        p["positions"] *= 2
    elif mutation == "duplicate_order":
        p["orders"] = copy.deepcopy(p["ordersForOpen"])
    elif mutation == "mixed_customer":
        p["positions"][0]["CID"] = 43
    elif mutation == "position_pnl":
        p["unrealizedPnL"] = "11"
    elif mutation == "stale":
        p["positions"][0]["unrealizedPnL"]["timestamp"] = (NOW - timedelta(seconds=61)).isoformat()
    elif mutation == "short":
        p["positions"][0]["isBuy"] = False
    elif mutation == "leverage":
        p["positions"][0]["leverage"] = 2
    elif mutation == "cfd":
        p["positions"][0]["settlementTypeID"] = 0
    elif mutation == "copy":
        p["mirrors"] = [{}]
    elif mutation == "bonus":
        p["bonusCredit"] = "1"
    elif mutation == "stock_order":
        p["stockOrders"] = [{}]
    elif mutation == "float":
        p["credit"] = 1000.0
    else:
        p["positions"][0]["positionId"] = p["positions"][0].pop("positionID")
    with pytest.raises(DiagnosticError) as error:
        parse_pnl(payload, observed_at=NOW, now=NOW)
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "mutation",
    [
        "currency",
        "null_pnl",
        "equity",
        "cash",
        "cid",
        "exposure",
        "missing_instrument",
        "duplicate_instrument",
        "future",
    ],
)
def test_aggregate_consistency_blocks(tmp_path: Path, mutation: str) -> None:
    p, a = samples()
    path = tmp_path / "risk.sqlite"
    state(path)
    if mutation == "currency":
        a["accountCurrency"] = "EUR"
    elif mutation == "null_pnl":
        a["accountTotals"]["accountCurrentPnl"] = None
    elif mutation == "equity":
        a["accountTotals"]["accountTotalValue"] = "1209"
    elif mutation == "cash":
        a["accountTotals"]["accountAvailableCash"] = "1000"
    elif mutation == "cid":
        a["cid"] = 43
    elif mutation == "exposure":
        a["instrumentAggregates"][0]["netCurrentExposureAccountCurrency"] = "209"
    elif mutation == "missing_instrument":
        a["instrumentAggregates"] = []
    elif mutation == "duplicate_instrument":
        a["instrumentAggregates"] *= 2
    else:
        a["timestamp"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(DiagnosticError):
        diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)


def test_missing_state_never_created(tmp_path: Path) -> None:
    p, a = samples()
    path = tmp_path / "missing.sqlite"
    with pytest.raises(DiagnosticError, match="LOCAL_SAFETY"):
        diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)
    assert not path.exists()


def test_snapshot_of_daily_halt_and_restart(tmp_path: Path) -> None:
    p, a = samples()
    path = tmp_path / "risk.sqlite"
    store = state(path)
    with store.transaction() as db:
        db.execute("UPDATE days SET halted=1")
    result = diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)
    assert result.local.daily_halted
    assert result == diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)


def test_command_invalid_input_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "SYNTHETIC_PRIVATE_NAME.json"
    path.write_text('{"secret":"SYNTHETIC_NOT_A_CREDENTIAL", "secret":1}')
    monkeypatch.setattr(
        "sys.argv",
        [
            "broker_diagnostics",
            "--pnl-file",
            str(path),
            "--aggregate-file",
            str(path),
            "--risk-state",
            str(path),
            "--observed-at",
            NOW.isoformat(),
        ],
    )
    assert main() == 1
    output = capsys.readouterr().out
    assert "SYNTHETIC" not in output and "blocked" in output


@pytest.mark.parametrize(
    "mutation", ["ticket_account", "digest", "terminal", "close", "instrument"]
)
def test_local_overlap_contradictions_block(tmp_path: Path, mutation: str) -> None:
    p, a = samples()
    path = tmp_path / "risk.sqlite"
    store = state(path)
    with store.transaction() as db:
        if mutation == "digest":
            db.execute("UPDATE execution_orders SET digest='wrong'")
        elif mutation == "terminal":
            db.execute("UPDATE execution_orders SET state='filled',terminal=1")
        elif mutation == "instrument":
            db.execute("UPDATE reservations SET instrument=2")
        else:
            ticket = json.loads(db.execute("SELECT ticket FROM execution_orders").fetchone()[0])
            if mutation == "ticket_account":
                ticket["account_id"] = "different-account"
            else:
                ticket["action"] = "close"
            raw = json.dumps(ticket)
            db.execute(
                "UPDATE execution_orders SET ticket=?,digest=?",
                (raw, hashlib.sha256(raw.encode()).hexdigest()),
            )
    with pytest.raises(DiagnosticError):
        diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)


def test_flat_account_still_not_trusted(tmp_path: Path) -> None:
    p, a = samples()
    p["clientPortfolio"]["positions"] = []
    p["clientPortfolio"]["unrealizedPnL"] = "0"
    a["accountTotals"].update(
        accountTotalUsedMargin="100", accountCurrentPnl="0", accountTotalValue="1000"
    )
    a["instrumentAggregates"] = []
    path = tmp_path / "risk.sqlite"
    state(path, pending=False)
    result = diagnose(p, path, aggregate=a, observed_at=NOW, now=NOW)
    assert result.snapshot.equity == 1000 and result.snapshot.available_balance == 900
    assert not result.decision.passed


def test_cli_help_needs_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["broker_diagnostics", "--help"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 0
