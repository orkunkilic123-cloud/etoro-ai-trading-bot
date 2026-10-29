"""Explicit read-only Demo connection and verified cash checks."""

import argparse

from .client import ApiError, DemoClient
from .config import ConfigurationError, Credentials
from .demo_balance import display_demo_balance
from .demo_cash import IncompleteDemoSnapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only eToro Demo checks")
    parser.add_argument("command", choices=["check-demo", "show-demo-balance"])
    args = parser.parse_args()
    try:
        with DemoClient(Credentials.from_environment()) as client:
            result = client.portfolio()
            if args.command == "show-demo-balance":
                if result.partial:
                    raise IncompleteDemoSnapshot("Partial Demo portfolio response")
                output = display_demo_balance(result.data)
            else:
                output = (
                    "Demo portfolio GET succeeded. No orders submitted; "
                    "key scope relies on eToro enforcement."
                )
    except (ApiError, ConfigurationError, IncompleteDemoSnapshot):
        # Never include upstream exceptions or response bodies in CLI output.
        print("Demo balance/check unavailable: credentials, API read or verified schema incomplete.")
        return 1
    print(output)
    return 0
