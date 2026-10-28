"""Verified TLS and explicit Codex proxy routing; never reads API credentials."""

import json
import os
import ssl
from pathlib import Path

import httpx

from .config import DataError

POLICY = Path("/etc/codex/network-policy.json")


def http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Injected transports are for offline tests; production uses the managed proxy."""
    if transport is not None:
        return httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(20, connect=5),
            follow_redirects=False,
            trust_env=False,
            verify=True,
        )
    result = None
    try:
        proxy = None
        mode = os.environ.get("ALPACA_DATA_CODEX_PROXY_REQUIRED", "false")
        if mode not in ("true", "false"):
            raise ValueError("Invalid proxy mode")
        if POLICY.exists() or mode == "true":
            policy = json.loads(POLICY.read_text(encoding="utf-8"))
            if not isinstance(policy, dict) or policy.get("version") != 1:
                raise ValueError("Unsupported policy")
            proxy = policy.get("http_proxy")
            if not isinstance(proxy, str):
                raise ValueError("Missing proxy")
            url = httpx.URL(proxy)
            if (
                url.scheme not in ("http", "https")
                or not url.host
                or url.userinfo
                or url.query
                or url.fragment
                or url.path != "/"
                or os.environ.get("HTTPS_PROXY") != proxy
            ):
                raise ValueError("Invalid or mismatched proxy")
        # Explicit context retains hostname verification and CERT_REQUIRED.
        # An invalid configured CA fails rather than falling back to another trust store.
        context = ssl.create_default_context(
            cafile=os.environ.get("SSL_CERT_FILE"), capath=os.environ.get("SSL_CERT_DIR")
        )
        result = httpx.Client(
            proxy=proxy,
            verify=context,
            trust_env=False,
            timeout=httpx.Timeout(20, connect=5),
            follow_redirects=False,
        )
    except (OSError, ValueError, TypeError, httpx.InvalidURL):
        pass
    if result is None:
        # Raise outside the handler: no context containing environment values or paths.
        raise DataError("Market-data proxy or TLS configuration is invalid.")
    return result
