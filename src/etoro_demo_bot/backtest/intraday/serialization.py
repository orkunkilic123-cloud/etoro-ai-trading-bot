"""Canonical research serialization, including session dates; no process-local state."""

import json
from datetime import date
from typing import Any

from ...strategy.journal import encode


def normalized(value: Any) -> Any:
    def dates(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: dates(v) for k, v in item.items()}
        if isinstance(item, tuple | list):
            return [dates(v) for v in item]
        if isinstance(item, date) and not hasattr(item, "hour"):
            return item.isoformat()
        return item

    return json.loads(encode(dates(value)))
