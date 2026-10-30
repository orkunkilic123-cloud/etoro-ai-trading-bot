from datetime import datetime, timedelta, timezone

from etoro_demo_bot.cloud_paper_safety import Decision, PaperSnapshot, assess


def test_paper_safety_fail_closed():
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    base = dict(account_mode="paper", broker_reconciled=True, kill_switch=False,
                daily_loss_fraction=0.0, pending_order_uncertain=False, last_heartbeat=now)
    assert assess(PaperSnapshot(**base), now) == Decision.OBSERVE
    assert assess(PaperSnapshot(**(base | {"account_mode": "live"})), now) == Decision.HALT
    assert assess(PaperSnapshot(**(base | {"kill_switch": True})), now) == Decision.HALT
    assert assess(PaperSnapshot(**(base | {"daily_loss_fraction": 0.03})), now) == Decision.HALT
    assert assess(PaperSnapshot(**(base | {"last_heartbeat": now - timedelta(minutes=3)})), now) == Decision.HALT
    assert assess(PaperSnapshot(**(base | {"pending_order_uncertain": True})), now) == Decision.RECONCILE
    assert assess(PaperSnapshot(**(base | {"broker_reconciled": False})), now) == Decision.RECONCILE
