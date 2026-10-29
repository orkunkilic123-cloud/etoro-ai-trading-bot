"""Explicit read-only Demo connection check and fail-closed balance command."""

import argparse

from .client import ApiError, DemoClient, ReadDiagnostic
from .config import ConfigurationError, Credentials
from .demo_balance import display_demo_balance
from .demo_cash import IncompleteDemoSnapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only eToro Demo checks")
    parser.add_argument("command", choices=["check-demo", "show-demo-balance"])
    args = parser.parse_args()
    try:
        with DemoClient(Credentials.from_environment()) as client:
            result = client.pnl() if args.command == "show-demo-balance" else client.portfolio()
            if args.command == "show-demo-balance":
                if result.partial:
                    raise IncompleteDemoSnapshot("Partial Demo P&L response")
                output = display_demo_balance(result.data)
            else:
                output = (
                    "Demo portfolio GET succeeded. No orders submitted; "
                    "key scope relies on eToro enforcement."
                )
    except ReadDiagnostic as exc:
        if args.command == "show-demo-balance":
            print(f"Demo P&L diagnostic: {exc.category}. No account data shown.")
        else:
            print("Demo check unavailable.")
        return 1
    except ConfigurationError:
        print("Demo configuration invalid or incomplete. No credential values shown.")
        return 1
    except IncompleteDemoSnapshot as exc:
        print(f"Demo P&L validation: {exc.field}: {exc.category}. No account data shown.")
        return 1
    except ApiError:
        if args.command == "show-demo-balance":
            print(
                "Demo P&L diagnostic: read-error. No account data shown."
            )
        else:
            print("Demo check unavailable: credentials or API read failed.")
        return 1
    print(output)
    return 0
