"""Explicit opt-in local configuration; importing this module reads no environment values."""

import os
from dataclasses import dataclass, field


class DataError(ValueError):
    """Sanitized error: never attach a request, response or upstream exception."""


@dataclass(frozen=True)
class Credentials:
    key: str = field(repr=False)
    secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if any(
            not value
            or not value.isascii()
            or len(value) > 256
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            for value in (self.key, self.secret)
        ):
            raise DataError("Alpaca data credentials are missing or invalid.")

    @classmethod
    def from_environment(cls) -> "Credentials":
        if os.environ.get("ALPACA_DATA_FREE_ACCESS_CONFIRMED") != "true":
            raise DataError(
                "Confirm Basic free IEX access and applicable data terms locally first."
            )
        return cls(
            os.environ.get("ALPACA_DATA_API_KEY", ""), os.environ.get("ALPACA_DATA_API_SECRET", "")
        )
