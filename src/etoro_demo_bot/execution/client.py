"""Private broker boundary. Only the coordinator may dispatch journalled mutations."""

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx

from ..config import Credentials
from .models import DemoIdentity, ExecutionError

ORIGIN = "https://public-api.etoro.com"
OPEN = "/api/v3/trading/execution/demo/orders"
ELIGIBILITY = "/api/v2/trading/info/demo/eligibility"
LOOKUP = "/api/v2/trading/info/demo/orders:lookup"
CLOSE = "/api/v1/trading/execution/demo/market-close-orders/positions/"
CLOSE_LOOKUP = "/api/v1/trading/info/demo/close-orders/"


def credential_digest(credentials: Credentials) -> str:
    return hashlib.sha256((credentials.api_key + "\0" + credentials.user_key).encode()).hexdigest()


def encode_body(body: dict[str, Any]) -> bytes:
    # Decimal numbers go on the wire as JSON numbers without float rounding.
    parts = []
    for key, value in body.items():
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ExecutionError("INVALID_PAYLOAD")
            encoded = format(value, "f")
        else:
            encoded = json.dumps(value, allow_nan=False)
        parts.append(json.dumps(key) + ":" + encoded)
    return ("{" + ",".join(parts) + "}").encode()


class DemoExecutionClient:
    def __init__(
        self,
        credentials: Credentials,
        identity: DemoIdentity,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credentials = credentials
        self.identity = identity
        self._http = httpx.Client(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(15, connect=5),
        )

    def close(self) -> None:
        self._http.close()

    def confirm(self, account_id: str, now: datetime) -> None:
        evidence = self.identity
        if (
            self._credentials.environment != "demo"
            or self._credentials.demo_key_confirmed is not True
            or evidence.demo_confirmed is not True
            or evidence.account_id != account_id
            or evidence.credential_digest != credential_digest(self._credentials)
            or evidence.expires_at.tzinfo is None
            or now.tzinfo is None
            or evidence.expires_at <= now
            or type(evidence.customer_id) is not int
            or evidence.customer_id <= 0
            or type(evidence.broker_account_id) is not int
            or evidence.broker_account_id <= 0
        ):
            raise ExecutionError("DEMO_IDENTITY_UNCONFIRMED")

    def _request(
        self,
        method: str,
        path: str,
        *,
        reference: str | None = None,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> tuple[int, dict[str, Any], int]:
        allowed = (
            (method, path) in {("POST", OPEN), ("POST", ELIGIBILITY), ("GET", LOOKUP)}
            or (method == "POST" and re.fullmatch(re.escape(CLOSE) + r"[1-9][0-9]*", path))
            or (method == "GET" and re.fullmatch(re.escape(CLOSE_LOOKUP) + r"[1-9][0-9]*", path))
        )
        if not allowed:
            raise ExecutionError("ENDPOINT_BLOCKED")
        self.confirm(self.identity.account_id, now or datetime.now(UTC))
        if method == "GET" and body is not None:
            raise ExecutionError("PAYLOAD_BLOCKED")
        if path == LOOKUP:
            if params is None or set(params) not in ({"referenceId"}, {"orderId"}):
                raise ExecutionError("QUERY_BLOCKED")
            if "referenceId" in params:
                UUID(params["referenceId"])
            elif not re.fullmatch(r"[1-9][0-9]*", params["orderId"]):
                raise ExecutionError("QUERY_BLOCKED")
        elif params:
            raise ExecutionError("QUERY_BLOCKED")
        request_id = reference or str(uuid4())
        UUID(request_id)
        failure = False
        response = None
        try:
            response = self._http.request(
                method,
                ORIGIN + path,
                params=params,
                content=encode_body(body) if body is not None else None,
                headers={
                    "x-api-key": self._credentials.api_key,
                    "x-user-key": self._credentials.user_key,
                    "x-request-id": request_id,
                    "Content-Type": "application/json",
                },
            )
        except (httpx.HTTPError, ValueError):
            failure = True
        if failure or response is None:
            raise ExecutionError("TRANSPORT_UNCERTAIN")
        cooldown = 3  # Conservative 20/min across execution and eligibility calls.
        for header in ("Retry-After", "RateLimit-Reset"):
            if header == "Retry-After" or response.headers.get("RateLimit-Remaining") == "0":
                raw = response.headers.get(header)
                if raw:
                    try:
                        cooldown = max(cooldown, int(raw))
                    except ValueError:
                        cooldown = max(cooldown, 60)
        data: Any = None
        try:
            data = json.loads(response.content, parse_float=Decimal)
        except (ValueError, UnicodeError):
            pass
        finally:
            response.close()
        return response.status_code, data if isinstance(data, dict) else {}, cooldown
