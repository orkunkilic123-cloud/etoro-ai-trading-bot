"""The query preview must stop before all credential, transport and storage work."""

import json
import sys
from typing import Any

import pytest

from etoro_demo_bot.alpaca import __main__ as cli
from etoro_demo_bot.alpaca.config import Credentials


@pytest.mark.parametrize("invalid", [False, True])
def test_dry_run_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], invalid: bool
) -> None:
    def blocked(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline preview touched credentials, storage or transport")

    monkeypatch.setattr(Credentials, "from_environment", blocked)
    monkeypatch.setattr(cli, "Archive", blocked)
    monkeypatch.setattr(cli, "MarketDataClient", blocked)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alpaca",
            "--dry-run",
            "--symbols",
            "IBM",
            "--start",
            "invalid" if invalid else "2026-03-01T00:00:00Z",
            "--end",
            "2026-03-02T00:00:00Z",
        ],
    )
    if invalid:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
        assert not capsys.readouterr().out
    else:
        assert cli.main() == 0
        preview = json.loads(capsys.readouterr().out.splitlines()[0])
        assert preview["method"] == "GET"
        assert preview["url"] == "https://data.alpaca.markets/v2/stocks/bars"
        assert preview["params"]["feed"] == "iex"
        assert preview["params"]["symbols"] == "IBM"


def test_preview_and_network_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["alpaca", "--dry-run", "--enable-network"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
