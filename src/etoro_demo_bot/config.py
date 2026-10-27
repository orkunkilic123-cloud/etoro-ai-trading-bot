"""Explicit Demo credential declaration; opaque key scope is checked by eToro."""

import os
from dataclasses import dataclass, field


class ConfigurationError(ValueError):
    """Safe configuration error containing no supplied values."""


@dataclass(frozen=True)
class Credentials:
    api_key: str = field(repr=False)
    user_key: str = field(repr=False)
    environment: str
    demo_key_confirmed: bool

    def __post_init__(self) -> None:
        if self.environment != "demo" or self.demo_key_confirmed is not True:
            raise ConfigurationError("A confirmed Demo-bound user key is required.")
        for value in (self.api_key, self.user_key):
            if (
                not value
                or not value.isascii()
                or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            ):
                raise ConfigurationError("API credentials are missing or invalid.")

    @classmethod
    def from_environment(cls) -> "Credentials":
        return cls(
            api_key=os.environ.get("ETORO_API_KEY", ""),
            user_key=os.environ.get("ETORO_USER_KEY", ""),
            environment=os.environ.get("ETORO_ENVIRONMENT", ""),
            demo_key_confirmed=os.environ.get("ETORO_DEMO_KEY_CONFIRMED") == "true",
        )
