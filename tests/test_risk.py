from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.risk import (
    AccountSnapshot,
    Exposure,
    Proposal,
    RiskEngine,
    RiskPolicy,
    RiskStore,
    StateError,
)

D = Decimal
NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> RiskStore:
    state = RiskStore.initialize(tmp_path / "risk.sqlite", "demo-account")
    state.establish_day(NOW.date(), D("10000"))
    state.set_kill_switch(False, acknowledged=True)
    return state


@pytest.fixture
def account() -> AccountSnapshot:
    return AccountSnapshot(
        "demo-account",
        D("10000"),
        D("10000"),
        (),
        NOW,
        demo=True,
        complete=True,
        cash_flows_reconciled=True,
    )


@pytest.fixture
def proposal() -> Proposal:
    return Proposal(
        "intent-1", 1, D("10"), D("100"), D("90"), NOW, D("0"), underlying_verified=True
    )


def test_exact_one_percent_pass_and_duplicate_restart(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    result = RiskEngine(store).evaluate(proposal, account, now=NOW)
    assert result.passed and result.risk_amount == D("100")
    assert result.notional == D("1000")
    assert not result.execution_authorized
    again = RiskEngine(RiskStore(store.path)).evaluate(proposal, account, now=NOW)
    assert not again.passed and "DUPLICATE_PROPOSAL" in again.reasons


@pytest.mark.parametrize(
    ("units", "buffer", "passed"),
    [
        ("9.999", "0", True),
        ("10", "0", True),
        ("10.001", "0", False),
        ("10", "0.01", False),
        ("9", "10", True),
    ],
)
def test_one_percent_boundaries(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
    units: str,
    buffer: str,
    passed: bool,
) -> None:
    result = RiskEngine(store).evaluate(
        replace(proposal, units=D(units), cost_buffer=D(buffer)),
        account,
        now=NOW,
    )
    assert result.passed is passed
    if not passed:
        assert "TRADE_RISK_LIMIT" in result.reasons


@pytest.mark.parametrize(
    ("equity", "halted"),
    [
        ("9700.01", False),
        ("9700", True),
        ("9699.99", True),
        ("0", True),
        ("-100", True),
    ],
)
def test_daily_loss_boundaries_and_latch(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
    equity: str,
    halted: bool,
) -> None:
    result = RiskEngine(store).evaluate(
        replace(proposal, units=D("1")),
        replace(account, equity=D(equity)),
        now=NOW,
    )
    assert ("DAILY_LOSS_LIMIT" in result.reasons) is halted
    if halted:
        recovered = RiskEngine(RiskStore(store.path)).evaluate(proposal, account, now=NOW)
        assert recovered.reasons == ("DAILY_LOSS_LIMIT",)
        store.set_kill_switch(True)
        store.set_kill_switch(False, acknowledged=True)
        assert "DAILY_LOSS_LIMIT" in RiskEngine(store).evaluate(proposal, account, now=NOW).reasons


def test_day_rollover_requires_baseline_and_never_clears_kill(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    engine = RiskEngine(store)
    engine.evaluate(proposal, replace(account, equity=D("9600")), now=NOW)
    tomorrow = NOW + timedelta(days=1)
    p = replace(proposal, quoted_at=tomorrow)
    a = replace(account, observed_at=tomorrow)
    assert engine.evaluate(p, a, now=tomorrow).reasons == ("MISSING_DAILY_BASELINE",)
    store.establish_day(tomorrow.date(), D("10000"))
    store.set_kill_switch(True)
    assert engine.evaluate(p, a, now=tomorrow).reasons == ("KILL_SWITCH_ACTIVE",)
    store.set_kill_switch(False, acknowledged=True)
    assert engine.evaluate(p, a, now=tomorrow).passed
    with pytest.raises(StateError):
        store.establish_day(tomorrow.date(), D("8000"))
    with pytest.raises(StateError):
        store.establish_day(NOW.date(), D("8000"))


def test_kill_switch_default_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "risk.sqlite"
    state = RiskStore.initialize(path, "demo-account")
    state.establish_day(NOW.date(), D("10000"))
    with pytest.raises(ValueError):
        state.set_kill_switch(False)
    with pytest.raises(FileExistsError):
        RiskStore.initialize(path, "demo-account")
    with RiskStore(path).transaction() as db:
        assert db.execute("SELECT killed FROM safety").fetchone() == (1,)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("price", None, "INVALID_PRICE"),
        ("price", D("0"), "INVALID_PRICE"),
        ("price", D("NaN"), "INVALID_PRICE"),
        ("price", D("Infinity"), "INVALID_PRICE"),
        ("stop_loss", None, "INVALID_STOP_LOSS"),
        ("stop_loss", D("0"), "INVALID_STOP_LOSS"),
        ("stop_loss", D("100"), "INVALID_STOP_LOSS"),
        ("stop_loss", D("101"), "INVALID_STOP_LOSS"),
        ("stop_loss", D("-1"), "INVALID_STOP_LOSS"),
        ("leverage", D("2"), "LEVERAGE_FORBIDDEN"),
        ("leverage", D("0"), "LEVERAGE_FORBIDDEN"),
        ("side", "sellShort", "INSTRUMENT_FORBIDDEN"),
        ("settlement", "cfd", "INSTRUMENT_FORBIDDEN"),
        ("settlement", "marginTrade", "INSTRUMENT_FORBIDDEN"),
        ("settlement", "realFutures", "INSTRUMENT_FORBIDDEN"),
        ("underlying_verified", False, "INSTRUMENT_FORBIDDEN"),
        ("units", D("-1"), "INVALID_PROPOSAL"),
        ("units", D("0"), "INVALID_PROPOSAL"),
        ("cost_buffer", D("-1"), "INVALID_PROPOSAL"),
        ("quote_type", "delayed", "STALE_MARKET_DATA"),
        ("quoted_at", NOW - timedelta(seconds=61), "STALE_MARKET_DATA"),
        ("quoted_at", NOW + timedelta(seconds=1), "STALE_MARKET_DATA"),
        ("quoted_at", NOW.replace(tzinfo=None), "STALE_MARKET_DATA"),
        ("instrument_id", True, "INVALID_PROPOSAL"),
    ],
)
def test_reject_invalid_proposal(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
    field: str,
    value: Any,
    reason: str,
) -> None:
    result = RiskEngine(store).evaluate(replace(proposal, **{field: value}), account, now=NOW)
    assert not result.passed and reason in result.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("demo", False, "INVALID_ACCOUNT"),
        ("currency", "EUR", "INVALID_ACCOUNT"),
        ("complete", False, "INVALID_ACCOUNT"),
        ("cash_flows_reconciled", False, "INVALID_ACCOUNT"),
        ("equity", D("NaN"), "INVALID_BALANCE"),
        ("available_balance", D("-1"), "INVALID_BALANCE"),
        ("observed_at", NOW - timedelta(seconds=61), "STALE_ACCOUNT"),
        ("account_id", "another-account", "STATE_UNAVAILABLE"),
    ],
)
def test_reject_invalid_account(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
    field: str,
    value: Any,
    reason: str,
) -> None:
    result = RiskEngine(store).evaluate(proposal, replace(account, **{field: value}), now=NOW)
    assert not result.passed and reason in result.reasons


@pytest.mark.parametrize(
    ("policy", "exposures", "balance", "reason"),
    [
        (RiskPolicy(max_position_fraction=D("0.09")), (), "10000", "POSITION_SIZE_LIMIT"),
        (
            RiskPolicy(max_exposure_fraction=D("0.10")),
            (Exposure(2, D("1"), 1),),
            "10000",
            "TOTAL_EXPOSURE_LIMIT",
        ),
        (
            RiskPolicy(max_instrument_fraction=D("0.10")),
            (Exposure(1, D("1"), 1),),
            "10000",
            "INSTRUMENT_EXPOSURE_LIMIT",
        ),
        (
            RiskPolicy(max_concurrent_positions=1),
            (Exposure(2, D("1"), 1),),
            "10000",
            "CONCURRENT_POSITION_LIMIT",
        ),
        (RiskPolicy(), (), "999.99", "INSUFFICIENT_BALANCE"),
    ],
)
def test_capacity_limits(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
    policy: RiskPolicy,
    exposures: tuple[Exposure, ...],
    balance: str,
    reason: str,
) -> None:
    result = RiskEngine(store, policy).evaluate(
        proposal,
        replace(account, exposures=exposures, available_balance=D(balance)),
        now=NOW,
    )
    assert not result.passed and reason in result.reasons


def test_reservations_count_for_balance_exposure_and_slots(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    policy = RiskPolicy(max_exposure_fraction=D("0.15"), max_concurrent_positions=1)
    engine = RiskEngine(store, policy)
    account = replace(account, available_balance=D("1500"))
    assert engine.evaluate(proposal, account, now=NOW).passed
    result = RiskEngine(RiskStore(store.path), policy).evaluate(
        replace(proposal, proposal_id="second", instrument_id=2),
        account,
        now=NOW,
    )
    assert set(result.reasons) == {
        "TOTAL_EXPOSURE_LIMIT",
        "CONCURRENT_POSITION_LIMIT",
        "INSUFFICIENT_BALANCE",
    }


def test_duplicate_economic_intent_with_new_id(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    assert RiskEngine(store).evaluate(proposal, account, now=NOW).passed
    p = replace(proposal, proposal_id="new-id", units=D("10.00"))
    assert "DUPLICATE_PROPOSAL" in RiskEngine(store).evaluate(p, account, now=NOW).reasons
    p = replace(proposal, units=D("9"))
    assert "DUPLICATE_PROPOSAL" in RiskEngine(store).evaluate(p, account, now=NOW).reasons


def test_atomic_concurrent_capacity_reservation(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    def evaluate(index: int) -> bool:
        engine = RiskEngine(RiskStore(store.path), RiskPolicy(max_concurrent_positions=1))
        return engine.evaluate(
            replace(proposal, proposal_id=f"p-{index}", instrument_id=index + 1), account, now=NOW
        ).passed

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(evaluate, range(4))) == 1


def test_missing_corrupt_locked_state(
    tmp_path: Path,
    account: AccountSnapshot,
    proposal: Proposal,
    store: RiskStore,
) -> None:
    path = tmp_path / "missing.sqlite"
    assert RiskEngine(RiskStore(path)).evaluate(proposal, account, now=NOW).reasons == (
        "STATE_UNAVAILABLE",
    )
    assert not path.exists()
    path.write_bytes(b"corrupt")
    assert not RiskEngine(RiskStore(path)).evaluate(proposal, account, now=NOW).passed
    with store.transaction():
        assert RiskEngine(store).evaluate(proposal, account, now=NOW).reasons == (
            "STATE_UNAVAILABLE",
        )


def test_corrupt_reservation_and_schema_fail_closed(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    with store.transaction() as db:
        db.execute("INSERT INTO reservations VALUES ('bad', 'bad', 1, 'NaN')")
    assert not RiskEngine(store).evaluate(proposal, account, now=NOW).passed
    with store.transaction() as db:
        db.execute("PRAGMA user_version=99")
    assert RiskEngine(store).evaluate(proposal, account, now=NOW).reasons == ("STATE_UNAVAILABLE",)


def test_clock_rollback_and_decimal_context_independence(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    with localcontext() as ctx:
        ctx.prec = 2
        result = RiskEngine(store).evaluate(proposal, account, now=NOW)
    assert result.passed and result.risk_amount == D("100")
    earlier = NOW - timedelta(seconds=1)
    result = RiskEngine(store).evaluate(
        replace(proposal, quoted_at=earlier), replace(account, observed_at=earlier), now=earlier
    )
    assert result.reasons == ("CLOCK_ROLLBACK",)


@pytest.mark.parametrize("value", [D("0"), D("1.01"), D("NaN"), D("Infinity")])
def test_invalid_policy(value: Decimal) -> None:
    with pytest.raises(ValueError):
        RiskPolicy(max_position_fraction=value)


def test_rejections_do_not_reserve_and_deterministic_reasons(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    p = replace(proposal, units=D("100"))
    first = RiskEngine(store).evaluate(p, account, now=NOW)
    assert first == RiskEngine(store).evaluate(p, account, now=NOW)
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (0,)
    assert RiskEngine(store).evaluate(proposal, account, now=NOW).passed


def test_unknown_account_metadata_defaults_closed(
    store: RiskStore,
    proposal: Proposal,
) -> None:
    unknown = AccountSnapshot("demo-account", D("10000"), D("10000"), (), NOW)
    assert RiskEngine(store).evaluate(proposal, unknown, now=NOW).reasons == ("INVALID_ACCOUNT",)


def test_stale_boundary_and_equal_capacity_pass(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    policy = RiskPolicy(
        max_position_fraction=D("0.10"),
        max_exposure_fraction=D("0.10"),
        max_instrument_fraction=D("0.10"),
        max_concurrent_positions=1,
    )
    result = RiskEngine(store, policy).evaluate(
        replace(proposal, quoted_at=NOW - timedelta(seconds=60)),
        replace(account, available_balance=D("1000")),
        now=NOW,
    )
    assert result.passed


def test_multiple_positions_in_same_instrument_count_individually(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    a = replace(account, exposures=(Exposure(2, D("100"), 5),))
    assert "CONCURRENT_POSITION_LIMIT" in RiskEngine(store).evaluate(proposal, a, now=NOW).reasons


def test_daily_halt_persists_when_kill_already_active(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    store.set_kill_switch(True)
    result = RiskEngine(store).evaluate(proposal, replace(account, equity=D("9700")), now=NOW)
    assert result.reasons == ("KILL_SWITCH_ACTIVE", "DAILY_LOSS_LIMIT")
    store.set_kill_switch(False, acknowledged=True)
    assert RiskEngine(store).evaluate(proposal, account, now=NOW).reasons == ("DAILY_LOSS_LIMIT",)


@pytest.mark.parametrize(
    "exposures",
    [
        (Exposure(1, D("-1"), 1),),
        (Exposure(1, D("NaN"), 1),),
        (Exposure(1, D("0"), 1),),
        (Exposure(1, D("1"), -1),),
        (Exposure(1, D("1"), 1), Exposure(1, D("2"), 1)),
    ],
)
def test_invalid_exposure_fails_closed(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
    exposures: tuple[Exposure, ...],
) -> None:
    assert RiskEngine(store).evaluate(
        proposal,
        replace(account, exposures=exposures),
        now=NOW,
    ).reasons == ("INVALID_EXPOSURE",)


def test_instrument_reservation_limit(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    engine = RiskEngine(store, RiskPolicy(max_instrument_fraction=D("0.15")))
    assert engine.evaluate(proposal, account, now=NOW).passed
    assert (
        "INSTRUMENT_EXPOSURE_LIMIT"
        in engine.evaluate(
            replace(proposal, proposal_id="second", units=D("9")),
            account,
            now=NOW,
        ).reasons
    )


def test_atomic_concurrent_duplicates(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    def evaluate(index: int) -> bool:
        return (
            RiskEngine(RiskStore(store.path))
            .evaluate(
                replace(proposal, proposal_id=f"same-intent-{index}"),
                account,
                now=NOW,
            )
            .passed
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(evaluate, range(4))) == 1


def test_negative_zero_cannot_bypass_duplicate_guard(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    assert RiskEngine(store).evaluate(proposal, account, now=NOW).passed
    result = RiskEngine(store).evaluate(
        replace(proposal, proposal_id="other", cost_buffer=D("-0.00")),
        account,
        now=NOW,
    )
    assert "DUPLICATE_PROPOSAL" in result.reasons


def test_state_commit_failure_never_returns_pass(
    store: RiskStore,
    account: AccountSnapshot,
    proposal: Proposal,
) -> None:
    # A database trigger simulates a persistent-storage rejection during reservation.
    with store.transaction() as db:
        db.execute("""CREATE TRIGGER fail_reservation BEFORE INSERT ON reservations
                   BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END""")
    result = RiskEngine(store).evaluate(proposal, account, now=NOW)
    assert result.reasons == ("STATE_UNAVAILABLE",)
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (0,)
