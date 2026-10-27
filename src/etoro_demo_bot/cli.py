"""Explicit read-only connection check; never prints account data or secrets."""

import argparse

from .client import ApiError, DemoClient
from .config import ConfigurationError, Credentials


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Demo connection check")
    parser.add_argument("command", choices=["check-demo"])
    parser.parse_args()
    try:
        with DemoClient(Credentials.from_environment()) as client:
            client.portfolio()
    except (ApiError, ConfigurationError) as exc:
        print(str(exc))
        return 1
    print(
        "Demo portfolio GET succeeded. No orders submitted; key scope relies on eToro enforcement."
    )
    return 0
