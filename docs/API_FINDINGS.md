# Verified eToro API findings

Reviewed 2026-10-27. Verification means public documentation retrieval and schema inspection, not authenticated integration testing. No orders were submitted.

## Official sources

- https://api-portal.etoro.com
- https://api-portal.etoro.com/core/getting-started/authentication
- https://api-portal.etoro.com/core/getting-started/rate-limits
- https://api-portal.etoro.com/api-reference/openapi.json (source for every endpoint and schema below)
- https://builders.etoro.com
- https://builders.etoro.com/learn/authentication-and-api-keys

Both requested sites returned HTTP 200. The API server in OpenAPI is `https://public-api.etoro.com`. Documentation pages are not the API server.

## Authentication and existing credentials

Personal API access uses `x-api-key` (application identity), `x-user-key` (user identity), and `x-request-id` (UUID). JSON bodies use `Content-Type: application/json`. Proposed local variables are `ETORO_API_KEY` and `ETORO_USER_KEY`; neither values nor credential files were accessed.

The portal explicitly states: each key is generated for **Demo or Real**, and each key can only be used for one environment; using both requires two keys. Permissions distinguish Read from Write; expiry and IP allowlisting are optional. The application key alone does not prove a user's environment or rights. The spec also offers OAuth scopes as an alternative; OAuth is outside this personal-key design.

There are no configured secret/runtime-variable bindings reported by the environment tool and no exported variable names containing ETORO in the current process. This does not prove credentials do not exist elsewhere. The user's existing keys' environment, permissions, expiry and usability therefore remain unverified. We did not request keys, inspect secret files, test Real endpoints or make authenticated API requests.

Use only a Demo-bound user key, initially Read-only. Confirm environment and permissions via non-secret key-management metadata before later read-only integration. Never test a Real route to classify a key. Absence of a documented standalone key-introspection route means key scope cannot be inferred locally from an opaque key string.

## Strict Demo-only policy

Pin HTTPS host public-api.etoro.com and exact approved methods and route templates below, not an arbitrary URL or generic `/demo/` substring test. No redirects, mode switch, fallback to Real, account transfers or copy-trading routes. Execution routes remain disabled until separately approved implementation and exact-order authorization. Separate read-only analysis from the future executor; the model never receives credentials or approval authority.

Require explicit leverage 1, long-only instrument eligibility, and underlying-asset settlement. In this schema `settlementType: "real"` means the fully funded underlying asset; it is NOT a Real-money environment selector. It is compatible with a Demo URL. Reject `cfd`, `realFutures`, `marginTrade`, short transactions and unknown eligibility. An environment must be selected by Demo-bound credentials AND the exact Demo route. Start with market orders only: MIT auto-selects settlement and is unsuitable for the initial explicit-settlement safety contract.

Never copy the documentation's sample leverage 2 payloads. The proposed initial v3 payload shape is action=open, transaction=buy, instrumentId=<verified ID>, settlementType=real, orderType=mkt, leverage=1, amount=<approved positive amount>, orderCurrency=usd. This is a schema description, not a submitted or authorized order. Exactly one of symbol/instrumentId and one of amount/units/contracts is allowed. Contracts are excluded by project policy. Optional stops must be included in the exact user-authorized ticket because they can cause subsequent automated closure.

## Version and execution semantics

Prefer v3 asynchronous create for a future executor; v2 create and v1 close are documented separately. Unified order schemas enumerate close/sell but descriptions explicitly say only open and buy/sellShort are currently supported. Project policy further restricts this to open/buy. Use the dedicated v1 close route only after separate approval; do not infer unified close support from enum values or what-if cost examples.

v3 creation returns 202 with orderId/referenceId, not proof of a fill. X-Request-Id is explicitly documented for idempotency on v3 create; referenceId echoes it. Persist it before dispatch and reconcile via orders:lookup using exactly one of orderId or referenceId. Never assume the header supplies idempotency on every endpoint. Retention duration and repeat/conflicting-payload semantics still need confirmation.

Documented execution statuses: 3 Filled, 5 PartiallyFilled; 4 Rejected and 10 RejectedPartiallyFilled include error details. 1 Received, 2 Placed, 11 WaitingForMarket and 12 PendingTriggeredRate remain in flight. Partial rejection still requires exposure reconciliation. Read positionExecutions for resulting position IDs. Unknown statuses fail closed.

## Rate limits and documentation discrepancy

The general rate-limit page says per-user-key rolling one-minute windows, generally 60 reads/minute and 20 writes/heavy operations/minute; excess returns 429. However, the current OpenAPI explicitly documents **120 requests/60 seconds shared across the market-data group**, including v1 candles and v2 rates. Do not silently treat the overview's 60 as the exact current market-data quota. Start conservatively at at most 60 combined market-data requests/minute and honor response headers; verify actual quota later.

Demo portfolio/pnl/v2 instrument-breakdown share 60/60 seconds. Demo order lookup and the listed related order-info endpoints share a separate 60/60 seconds quota. Demo execution mutations share 20/60 seconds. Eligibility has a dedicated 20/60 seconds quota. Full operation-specific quota descriptions are preserved below. A quota shared across endpoints is not a per-endpoint allowance.

The spec documents RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset (seconds), and RateLimit-Policy. Builders documents Retry-After on 429. Honor these when supplied; bounded backoff with jitter for safe reads; reconcile ambiguous mutations before any retry. Rate limits are operational constraints, not evidence of free commercial access.

## Remaining uncertainties and gates

- Actual key access and Demo binding remain untested; no secrets were accessed.
- Rate-limit overview and OpenAPI disagree on market-data quota; runtime headers/support should settle this.
- Some quota lists reference legacy routes absent from current paths; these references do not authorize implementing legacy endpoints.
- Unified close enums conflict with explicit unsupported-operation prose; treat close as unsupported there.
- v2 instrument-breakdown requires CID; provenance and availability for personal-key access need confirmation before enabling it. Prefer v1 portfolio initially.
- Free-access terms, account/region eligibility, underlying-instrument availability and quote entitlement/delay require account-specific confirmation. Do not enable paid services.
- Idempotency retention, exact cancellation races, partial fills, error handling and availability of historical lookup after restart need contract tests and later authorized integration.
- No WebSocket integration was validated; REST market data is the initial scope.
- Builders sample code includes a live fallback and a portfolio path without demo, and omits x-request-id in some examples. Do not copy it into this project; use the current portal and operation schema, subject to the contradictions noted above.

## Endpoint and schema catalogue

The following is extracted from the official OpenAPI document. It is documentation, not a client implementation. Copy trading is excluded. Request parameter required flags and body schemas are preserved as published; conditional requirements in descriptions still apply. No GET below has a request body unless explicitly shown. Common auth headers above apply throughout.

OpenAPI SHA-256: `549e77e8f37dc167dfb6295e4771faf1f9bb71f62d0e925109cd6aa9a5d299a0`


### GET /api/v1/market-data/exchanges

List supported exchanges

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

Parameters (excluding common headers):
```json
[
  {
    "name": "exchangeIds",
    "in": "query",
    "description": "A comma seperated list of exchange ids to retrieve",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  }
]
```

Success 200: Success; schema `{"$ref": "#/components/schemas/ExchangesResponse"}`.


### GET /api/v1/market-data/instrument-types

List instrument types

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

Parameters (excluding common headers):
```json
[
  {
    "name": "instrumentTypeIds",
    "in": "query",
    "description": "A comma seperated list of instrument type ids to retrieve",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  }
]
```

Success 200: Success; schema `{"$ref": "#/components/schemas/InstrumentTypesResponse"}`.


### GET /api/v1/market-data/instruments

Get instrument display data

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

Parameters (excluding common headers):
```json
[
  {
    "name": "instrumentIds",
    "in": "query",
    "description": "A comma seperated list of instrument ids to filter on",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  },
  {
    "name": "exchangeIds",
    "in": "query",
    "description": "A comma seperated list of exchange ids to filter on",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  },
  {
    "name": "stocksIndustryIds",
    "in": "query",
    "description": "A comma seperated list of stock industry ids to filter on",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  },
  {
    "name": "instrumentTypeIds",
    "in": "query",
    "description": "A comma seperated list of instrument type ids to filter on",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  }
]
```

Success 200: Success; schema `{"$ref": "#/components/schemas/InstrumentsResponse"}`.


### GET /api/v1/market-data/instruments/history/closing-price

Get historical closing prices

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

Parameters (excluding common headers):
```json
[]
```

Success 200: Successful retrieval of closing prices; schema `{"$ref": "#/components/schemas/closingPricesResponse"}`.


### GET /api/v1/market-data/instruments/rates

Get instrument market rates

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

---

Provides real-time market data including bid/ask prices, conversion rates, and execution prices for specified financial instruments. Essential for price discovery and trade execution decisions.

Parameters (excluding common headers):
```json
[
  {
    "name": "instrumentIds",
    "in": "query",
    "style": "form",
    "description": "Comma-separated list of instrument IDs to retrieve market rates for. Each ID represents a unique tradable asset in the system.",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      },
      "maxItems": 100
    },
    "example": "1,2,3",
    "required": true
  }
]
```

Success 200: Successfully retrieved current market rates; schema `{"$ref": "#/components/schemas/LiveRatesResponse"}`.


### GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}

Get instrument candle history

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

---

Retrieves historical price data in OHLCV (Open, High, Low, Close, Volume) format for a specified instrument. The data is organized into time-based candles of various intervals, from one minute to one week.

Parameters (excluding common headers):
```json
[
  {
    "name": "direction",
    "in": "path",
    "description": "Sorting direction of the candles data. Use 'asc' for oldest to newest, or 'desc' for newest to oldest.",
    "required": true,
    "schema": {
      "type": "string",
      "enum": [
        "asc",
        "desc"
      ]
    }
  },
  {
    "name": "interval",
    "in": "path",
    "description": "Time interval for each candle. Determines the granularity of the price data. Shorter intervals provide more detailed price action but require more data points.",
    "required": true,
    "schema": {
      "type": "string",
      "enum": [
        "OneMinute",
        "FiveMinutes",
        "TenMinutes",
        "FifteenMinutes",
        "ThirtyMinutes",
        "OneHour",
        "FourHours",
        "OneDay",
        "OneWeek"
      ]
    }
  },
  {
    "name": "candlesCount",
    "in": "path",
    "description": "Number of candles to retrieve. Maximum value is 1000. For longer historical periods, consider using a larger time interval or making multiple requests.",
    "required": true,
    "schema": {
      "type": "integer",
      "default": 100,
      "maximum": 1000
    }
  },
  {
    "name": "instrumentId",
    "in": "path",
    "description": "Unique identifier of the financial instrument to retrieve candles for. This ID is consistent across all etoro systems.",
    "required": true,
    "schema": {
      "type": "integer"
    }
  }
]
```

Success 200: Successful retrieval of candles data; schema `{"$ref": "#/components/schemas/candlesResponse"}`.


### GET /api/v1/market-data/search

Search for Instruments

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

---

Retrieve a paginated list of instruments. Any field in the Instrument response schema can be projected via the required `fields` parameter and/or used as a query-string filter (e.g. `fields=instrumentId,displayname&displayname=Bitcoin`). Use `pageSize`/`pageNumber` to paginate and `sort` to order. Filters that do not match an indexed instrument field are ignored.

Parameters (excluding common headers):
```json
[
  {
    "name": "pageSize",
    "in": "query",
    "description": "The number of results to return per page.",
    "required": false,
    "schema": {
      "type": "integer"
    }
  },
  {
    "name": "pageNumber",
    "in": "query",
    "description": "The page number to retrieve for pagination.",
    "required": false,
    "schema": {
      "type": "integer"
    }
  },
  {
    "name": "fields",
    "in": "query",
    "description": "A comma-separated list of fields to include in the response. Example: pop=popularityUniques7Day,displayname",
    "required": true,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "sort",
    "in": "query",
    "description": "The field to sort by. Ascending is the default; prefix the field with `-` for descending. Sort on several fields with a comma-separated list, applied left to right (e.g. `-dailyPriceChange,weeklyPriceChange`). There is no `asc`/`desc` keyword and no space in this value - `popularityUniques7Day desc` is rejected. Not every field in the Instrument schema is sortable: unlike a filter, an unsortable or unknown sort field fails the whole request rather than being ignored.",
    "required": false,
    "schema": {
      "type": "string",
      "example": "-popularityUniques7Day"
    },
    "example": "-popularityUniques7Day"
  }
]
```

Success 200: Successful response containing the list of instruments.; schema `{"$ref": "#/components/schemas/InstrumentSearchResponse"}`.


### GET /api/v1/market-data/stocks-industries

Get stocks industries

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

Parameters (excluding common headers):
```json
[
  {
    "name": "stocksIndustryIds",
    "in": "query",
    "description": "A comma seperated list of stock industry ids to retrieves",
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    }
  }
]
```

Success 200: Success; schema `{"$ref": "#/components/schemas/StocksIndustriesResponse"}`.


### POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}

Close demo position by units

**Rate limit:** 20 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `DELETE /api/v1/trading/execution/demo/limit-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /api/v2/trading/execution/demo/orders/{orderId}`
- `DELETE /api/v3/trading/execution/demo/orders/{orderId}`
- `POST /api/v1/trading/execution/demo/limit-orders`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-amount`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-units`
- `POST /api/v2/trading/execution/demo/orders`
- `POST /api/v3/trading/execution/demo/orders`

---

This endpoint allows traders to close an entire position or a portion of it at the current market rate. If `UnitsToDeduct` is provided, only the specified portion will be closed. If `UnitsToDeduct` is omitted or set to null, the full position will be closed. A 200 response means the close order was submitted, not that the position was closed. Confirm the outcome with GET /api/v1/trading/info/demo/close-orders/{orderId}, using the orderID returned under orderForClose.

Parameters (excluding common headers):
```json
[
  {
    "name": "positionId",
    "in": "path",
    "description": "The unique identifier of the position to close.",
    "required": true,
    "schema": {
      "type": "integer",
      "format": "int64"
    }
  }
]
```

Request body:
```json
{
  "content": {
    "application/json": {
      "schema": {
        "type": "object",
        "properties": {
          "InstrumentID": {
            "type": "integer",
            "format": "int32",
            "description": "The ID of the financial instrument associated with the position."
          },
          "UnitsToDeduct": {
            "type": "number",
            "format": "double",
            "nullable": true,
            "description": "The number of units to close. If omitted or null, the entire position will be closed."
          }
        },
        "required": [
          "InstrumentID"
        ]
      }
    }
  }
}
```

Success 200: Successfully closed a position or a part of it.; schema `{"type": "object", "properties": {"orderForClose": {"type": "object", "properties": {"positionID": {"type": "integer", "description": "The ID of the closed position."}, "instrumentID": {"type": "integer", "description": "The ID of the instrument traded."}, "unitsToDeduct": {"type": "number", "format": "double", "description": "The number of units closed in this order."}, "orderID": {"type": "integer", "description": "The unique identifier of the closing order."}, "orderType": {"type": "integer", "description": "The type of order executed."}, "statusID": {"type": "integer", "description": "The status of the closing order."}, "CID": {"type": "integer", "description": "Customer Account ID associated with the order."}, "openDateTime": {"type": "string", "format": "date-time", "description": "The timestamp when the order was placed."}, "lastUpdate": {"type": "string", "format": "date-time", "description": "The timestamp of the last update to this order."}}}, "token": {"type": "string", "format": "uuid", "description": "A unique confirmation token for the closing order."}}}`.


### DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}

Cancel pending demo close order

**Rate limit:** 20 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `DELETE /api/v1/trading/execution/demo/limit-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /api/v2/trading/execution/demo/orders/{orderId}`
- `DELETE /api/v3/trading/execution/demo/orders/{orderId}`
- `POST /api/v1/trading/execution/demo/limit-orders`
- `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-amount`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-units`
- `POST /api/v2/trading/execution/demo/orders`
- `POST /api/v3/trading/execution/demo/orders`

---

This endpoint allows traders to cancel a previously placed market order for close before execution. If the order has already been processed, cancellation will not be possible. A 200 response confirms the cancellation request was received, not that the order was cancelled. Confirm with GET /api/v1/trading/info/demo/close-orders/{orderId}, using the orderId of the close order you tried to cancel. If the DELETE response is lost (timeout or network error), do not resend the cancel - poll that GET endpoint with the same orderId. Units reported as executed in its positions[] array were closed before the cancel took effect; the remainder was not closed. No executed entries in positions[] means nothing was closed. Poll until statusID is terminal: 7 (CANCELED) = cancelled with nothing executed, 9 (CANCELED_PARTIALLY_FILLED) = cancelled after a partial fill (executed units in positions[]), 3 (FILLED) = fully executed before the cancel; 1, 2, 5, 6 and 11 are still pending.

Parameters (excluding common headers):
```json
[
  {
    "name": "orderId",
    "in": "path",
    "required": true,
    "schema": {
      "type": "integer",
      "format": "int64"
    },
    "description": "The unique identifier of the market order for close to be canceled."
  }
]
```

Success 200: Successfully canceled the market order for close. The response includes a confirmation token.; schema `{"type": "object", "properties": {"token": {"type": "string", "format": "uuid", "description": "A confirmation token indicating the order cancellation."}}, "required": ["token"]}`.


### GET /api/v1/trading/info/demo/aggregate-portfolio

Get aggregated portfolio snapshot

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `POST /api/v1/trading/info/demo/aggregate-portfolio`

---

Returns a complete snapshot of the authenticated user's demo account investment portfolio, organized by asset. The response includes account-level balances and equity, individually held positions grouped by asset, and any copy-trading relationships the user has active. Use the instrumentIds filter to scope results to a specific set of assets, or mirrorIds to isolate specific copy-trading relationships. Account totals always reflect the full portfolio regardless of filters applied.

Parameters (excluding common headers):
```json
[
  {
    "name": "conversionMode",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "enum": [
        "eToroApp",
        "Realtime"
      ],
      "default": "eToroApp"
    },
    "description": "Determines which conversion to use for non-USD assets when the market is closed. 'Realtime' uses the realtime conversion rate. 'eToroApp' uses the last conversion rate at market close time. Default is 'eToroApp'."
  },
  {
    "name": "instrumentIds",
    "in": "query",
    "required": false,
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    },
    "description": "Scope the response to a specific list of assets by their etoro instrument ID. When omitted, all held assets are returned. Does not affect account-level totals."
  },
  {
    "name": "mirrorIds",
    "in": "query",
    "required": false,
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    },
    "description": "Scope copy-trading data to specific relationships by their mirror ID. A mirrorId of 0 refers to positions held directly (not via copy trading). When omitted, all copy-trading relationships are included."
  },
  {
    "name": "pnlLevel",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "enum": [
        "None",
        "Pnl",
        "DailyPnl"
      ],
      "default": "Pnl"
    },
    "description": "None = no pnl calculations. Pnl = pnl calculations. DailyPnl = pnl and today's pnl calculations. Default is 'Pnl'."
  },
  {
    "name": "dailyCutoffUtc",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "format": "date-time"
    },
    "description": "UTC timestamp representing the start of 'today' in the user's local timezone \u2014 normally the user's most recent local midnight, expressed in UTC. Required when pnlLevel=DailyPnl; rejected otherwise. Must not be more than 48 hours in the past or more than 5 minutes in the future."
  }
]
```

Success 200: Successfully retrieved aggregated portfolio data; schema `{"$ref": "#/components/schemas/TradingPortfolioDemoApi_AggregatedPortfolioResponse"}`.


### POST /api/v1/trading/info/demo/aggregate-portfolio

Get a filtered aggregated portfolio snapshot

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/trading/info/demo/aggregate-portfolio`

---

Returns the demo portfolio using aggregation levels and structured per-mirror instrument filters from the request body. This filter does not affect the account totals, that are still calculated based on the full portfolio.

Parameters (excluding common headers):
```json
[]
```

Request body:
```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/AggregatedPortfolioDemoPostRequest"
      }
    }
  }
}
```

Success 200: Successfully retrieved aggregated portfolio data; schema `{"$ref": "#/components/schemas/TradingPortfolioDemoApi_AggregatedPortfolioResponse"}`.


### GET /api/v1/trading/info/demo/close-orders/{orderId}

Get close order information and closed position details

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/trading/info/demo/orders/{orderId}`
- `GET /api/v2/trading/info/demo/orders:lookup`

---

Retrieves information about a close order, including its execution status and the positions that were closed as a result of the request. Use this to track the outcome of a position-closing order and identify which positions were affected. This is a read-only call and is the supported way to confirm the outcome of POST or DELETE /api/v1/trading/execution/demo/market-close-orders/... - including when the DELETE response was lost: poll this endpoint with the same close orderId instead of resending the cancel. Executed quantity is reported per affected position in positions[] (units and amount, with occurred and rate set once that position was closed); the order-level proceeds field totals what was realized. A close order that was cancelled before anything executed has no executed entries in positions[]. Any requested units that do not appear as executed in positions[] were not closed. errorCode and errorMessage are populated when processing failed.

Parameters (excluding common headers):
```json
[
  {
    "name": "orderId",
    "in": "path",
    "required": true,
    "description": "The unique identifier of the order.",
    "schema": {
      "type": "integer",
      "format": "int64"
    }
  }
]
```

Success 200: Close order information retrieved successfully.; schema `{"$ref": "#/components/schemas/OrderForCloseInfoResponse"}`.


### GET /api/v1/trading/info/demo/pnl

Get account PnL and portfolio details

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/trading/info/demo/portfolio`
- `GET /api/v2/trading/info/demo/instrument-breakdown`

---

Retrieves the demo account's current portfolio, including credit, open positions, orders, mirrors, and PnL details.

Parameters (excluding common headers):
```json
[]
```

Success 200: Successfully retrieved demo account PnL and portfolio information.; schema `{"$ref": "#/components/schemas/PortfolioResponseWithPnl"}`.


### GET /api/v1/trading/info/demo/portfolio

Get demo portfolio breakdown

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/trading/info/demo/pnl`
- `GET /api/v2/trading/info/demo/instrument-breakdown`

---

Returns detailed portfolio information including active positions, pending orders, mirror trading details, and account balances. This endpoint provides a complete overview of the user's trading activity and current market exposure.

Parameters (excluding common headers):
```json
[]
```

Success 200: Successfully retrieved portfolio information; schema `{"$ref": "#/components/schemas/PortfolioResponse"}`.


### GET /api/v1/trading/info/trade/demo/history

List trading history

**Rate limit:** 60 requests per 60 seconds. This is the **default shared quota** — it is shared with every other endpoint that has no dedicated limit, so requests across those endpoints all draw from the same budget.

---

Returns closed trades for the authenticated account from `minDate` through the present. Keep each request's lookback to less than 1 year (maximum 1 year minus 1 day). For longer history, split the range into successive windows of at most that length (advance `minDate` per batch) and use `page` / `pageSize` within each window.

Parameters (excluding common headers):
```json
[
  {
    "name": "minDate",
    "description": "The start date of the period you would like to view.",
    "in": "query",
    "schema": {
      "type": "string",
      "format": "date"
    },
    "required": true
  },
  {
    "name": "page",
    "description": "The page number.",
    "in": "query",
    "schema": {
      "type": "integer"
    },
    "required": false
  },
  {
    "name": "pageSize",
    "description": "The amount of trades in each page.",
    "in": "query",
    "schema": {
      "type": "integer"
    },
    "required": false
  }
]
```

Success 200: OK; schema `{"type": "array", "items": {"type": "object", "properties": {"netProfit": {"type": "number", "format": "float", "description": "The net profit of the trade"}, "closeRate": {"type": "number", "format": "float", "description": "The closing rate of the trade"}, "closeTimestamp": {"type": "string", "format": "date-time", "description": "The closing timestamp of the trade"}, "positionId": {"type": "integer", "format": "int64", "description": "The position ID of the trade"}, "instrumentId": {"type": "integer", "format": "int32", "description": "The instrument ID of the instrument that was traded"}, "isBuy": {"type": "boolean", "description": "Indicates if the trade was a buy or sell"}, "leverage": {"type": "integer", "format": "int32", "description": "The leverage used in the trade"}, "openRate": {"type": "number", "format": "float", "description": "The opening rate of the trade"}, "openTimestamp": {"type": "string", "format": "date-time", "description": "The opening timestamp of the trade"}, "stopLossRate": {"type": "number", "format": "float", "description": "The stop loss rate of the trade"}, "takeProfitRate": {"type": "number", "format": "float", "description": "The take profit rate of the trade"}, "trailingStopLoss": {"type": "boolean", "description": "Indicates if the trade had a trailing stop loss"}, "orderId": {"type": "integer", "format": "int64", "description": "The order ID of the trade"}, "socialTradeId": {"type": "integer", "format": "int64", "description": "The social trade ID of the trade"}, "parentPositionId": {"type": "integer", "format": "int64", "description": "The parent position ID of the trade"}, "investment": {"type": "number", "format": "float", "description": "The investment amount of the trade"}, "initialInvestment": {"type": "number", "format": "float", "description": "The initial investment amount of the trade"}, "fees": {"type": "number", "format": "float", "description": "The fees of the trade"}, "units": {"type": "number", "format": "float", "description": "The number of units traded"}}}}`.


### GET /api/v2/market-data/instruments

Search for securities (instruments) by ID or symbol

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments/search`
- `GET /api/v2/market-data/rates`

---

Returns instrument (security) metadata, optionally filtered by instrument IDs or symbols, with cursor-based pagination.

`instrumentsIds` and `symbols` are mutually exclusive. All filters are optional and independent; if neither `instrumentsIds` nor `symbols` is provided, results are not filtered by instrument and are simply paginated by `pageSize`.

Parameters (excluding common headers):
```json
[
  {
    "name": "instrumentsIds",
    "in": "query",
    "description": "Filter by instrument IDs. Mutually exclusive with symbols.",
    "required": false,
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer"
      }
    }
  },
  {
    "name": "symbols",
    "in": "query",
    "description": "Filter by trading symbols (e.g. AAPL). Mutually exclusive with instrumentsIds.",
    "required": false,
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  {
    "name": "pageSize",
    "in": "query",
    "description": "Maximum number of results per page. Defaults to 100 when omitted.",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 100
    }
  },
  {
    "name": "pageToken",
    "in": "query",
    "description": "Pagination cursor from the previous response's pagination.nextPageToken.",
    "required": false,
    "schema": {
      "type": "string"
    }
  },
  {
    "name": "exchangeId",
    "in": "query",
    "description": "Filter by exchange ID.",
    "required": false,
    "schema": {
      "type": "integer"
    }
  },
  {
    "name": "type",
    "in": "query",
    "description": "Filter by instrument type.",
    "required": false,
    "schema": {
      "type": "string",
      "enum": [
        "Forex",
        "Commodity",
        "CFD",
        "Indices",
        "Stocks",
        "ETF",
        "Bonds",
        "TrustFunds",
        "Options",
        "Crypto"
      ]
    }
  }
]
```

Success 200: Matching securities and pagination metadata; schema `{"$ref": "#/components/schemas/marketDataResponse"}`.


### GET /api/v2/market-data/instruments/search

Search instruments by free-text query

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/rates`

---

Free-text search of instruments by name or symbol. Results are relevance-ranked by the upstream search index; non-public instruments are filtered out.

Parameters (excluding common headers):
```json
[
  {
    "name": "query",
    "in": "query",
    "description": "Free-text query to match instruments by name or symbol (1-100 chars).",
    "required": true,
    "schema": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    }
  },
  {
    "name": "limit",
    "in": "query",
    "description": "Maximum number of results (1-50, default 10).",
    "required": false,
    "schema": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "default": 10
    }
  }
]
```

Success 200: Relevance-ranked search results; schema `{"$ref": "#/components/schemas/searchInstrumentsResponse"}`.


### GET /api/v2/market-data/rates

Retrieve bid/ask rates for one or more instruments

**Rate limit:** 120 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/market-data/exchanges`
- `GET /api/v1/market-data/instrument-types`
- `GET /api/v1/market-data/instruments`
- `GET /api/v1/market-data/instruments/history/closing-price`
- `GET /api/v1/market-data/instruments/rates`
- `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
- `GET /api/v1/market-data/search`
- `GET /api/v1/market-data/stocks-industries`
- `GET /api/v2/market-data/instruments`
- `GET /api/v2/market-data/instruments/search`

---

Returns current bid/ask rates keyed by instrument ID. Each rate carries a `quoteType` indicating whether it is `realtime` or `delayed`.

Returns 200 when all requested instruments are found, 206 when only a subset is available.

Parameters (excluding common headers):
```json
[
  {
    "name": "instrumentIds",
    "in": "query",
    "description": "List of instrument IDs to fetch rates for (max 1000).",
    "required": true,
    "style": "form",
    "explode": false,
    "schema": {
      "type": "array",
      "items": {
        "type": "integer"
      },
      "maxItems": 1000
    }
  }
]
```

Success 200: Rates for all requested instruments; schema `{"$ref": "#/components/schemas/ratesResponse"}`.

Success 206: Rates for a subset of the requested instruments; schema `{"$ref": "#/components/schemas/ratesResponse"}`.


### PATCH /api/v2/trading/demo/positions/{positionId}

Modify stop-loss and take-profit settings on an open position

**Rate limit:** 60 requests per 60 seconds. This is the **default shared quota** — it is shared with every other endpoint that has no dedicated limit, so requests across those endpoints all draw from the same budget.

---

Submits an asynchronous request to update stop-loss and/or take-profit on an open position. You can set a new stopLossRate, takeProfitRate, stopLossType, or clear either value (clearStopLoss, clearTakeProfit). At least one SL/TP-related field is required. The response returns acceptance and correlation metadata only.

Parameters (excluding common headers):
```json
[
  {
    "name": "positionId",
    "in": "path",
    "required": true,
    "description": "The open position identifier.",
    "schema": {
      "type": "integer",
      "format": "int64"
    },
    "example": 13902598
  }
]
```

Request body:
```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/UpdatePositionRequest"
      }
    }
  }
}
```

Success 202: Request accepted and queued for asynchronous execution.; schema `{"$ref": "#/components/schemas/UpdatePositionResponse"}`.


### POST /api/v2/trading/execution/demo/orders

Create an order

**Rate limit:** 20 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `DELETE /api/v1/trading/execution/demo/limit-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /api/v2/trading/execution/demo/orders/{orderId}`
- `DELETE /api/v3/trading/execution/demo/orders/{orderId}`
- `POST /api/v1/trading/execution/demo/limit-orders`
- `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-amount`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-units`
- `POST /api/v3/trading/execution/demo/orders`

---

This endpoint allows traders to place an order. Leverage, stop-loss, and take-profit settings can be applied. Order size must use exactly one of amount, units, or contracts. For open orders the instrument must be identified by exactly one of symbol or instrumentId - providing both is rejected. A stopLossRate is required when leverage is greater than 1, when transaction is sellShort, when settlementType is realFutures, or when stopLossType is trailing. Only the buy and sellShort transactions are currently supported. A unique X-Request-Id header (GUID) is required for idempotency. Currently only orders to open a position are supported. On this v2 create path, settlementType remains optional (stricter settlementType rules apply only on v3). A 200 response means the order was accepted for processing, not that it was executed. Confirm the outcome with GET /api/v2/trading/info/demo/orders:lookup, passing the returned orderId - or referenceId, which echoes your X-Request-Id and is the only handle you have if this response is lost. In that response, status.id 3 (Filled) and 5 (PartiallyFilled) mean the order executed; 4 (Rejected) and 10 (RejectedPartiallyFilled) carry the reason in status.errorCode and status.errorMessage; 1 (Received), 2 (Placed), 11 (WaitingForMarket) and 12 (PendingTriggeredRate) are still in flight and should be polled again. positionExecutions lists the positionId values the order produced.

Parameters (excluding common headers):
```json
[]
```

Request body:
```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TradingDemoAdminApi_UnifiedOrderRequest"
      }
    }
  }
}
```

Success 200: Order submitted successfully. Returns the created order details.; schema `{"$ref": "#/components/schemas/UnifiedOrderResponse"}`.


### DELETE /api/v2/trading/execution/demo/orders/{orderId}

Cancels an order before it is executed

**Rate limit:** 20 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `DELETE /api/v1/trading/execution/demo/limit-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /api/v3/trading/execution/demo/orders/{orderId}`
- `POST /api/v1/trading/execution/demo/limit-orders`
- `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-amount`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-units`
- `POST /api/v2/trading/execution/demo/orders`
- `POST /api/v3/trading/execution/demo/orders`

---

This endpoint sends a cancellation request to cancel an order before execution. An order can be cancelled if it is waiting for the market to open, or for the trigger rate to be published (MIT orders). The cancellation request may be successful, and the order is cancelled, or unsuccessful, and the order is not cancelled. This operation is idempotent when the order is already closed or cancelled. A 200 response confirms the cancellation request was accepted, not that the order was cancelled - it may already have executed. Confirm with GET /api/v2/trading/info/demo/orders:lookup: status.id 7 (Canceled) or 9 (CanceledPartiallyFilled) means the cancellation took effect, while 6 (PendingCancel) means it is still being processed.

Parameters (excluding common headers):
```json
[
  {
    "name": "orderId",
    "in": "path",
    "required": true,
    "description": "The ID of the order to cancel.",
    "schema": {
      "type": "integer",
      "format": "int64"
    },
    "example": 13902598
  }
]
```

Success 200: Order cancellation request submitted successfully.; schema `{"type": "object", "description": "Acknowledgment when the service returns a confirmation payload.", "properties": {"token": {"type": "string", "format": "uuid", "description": "Optional confirmation token for the cancellation request."}}}`.


### POST /api/v2/trading/info/demo/costs

Get what-if trading cost breakdown

**Rate limit:** 20 requests per 60 seconds. This is a **dedicated** limit for this endpoint — it is **not shared** with (pooled across) any other endpoint, so the full rate is available to this endpoint alone.

---

Returns the markup, market spread, transaction fee, overnight fee, over-weekend fee, and tax that would apply if the supplied order were executed now against the demo account. For `action: open`, exactly one of `symbol` or `instrumentId` must be provided and `leverage` must be at least 1. For `action: close`, `positionIds` must be non-empty.

Parameters (excluding common headers):
```json
[]
```

Request body:
```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TradingDemoAdminApi_UnifiedOrderRequest"
      }
    }
  }
}
```

Success 200: Cost breakdown resolved successfully.; schema `{"$ref": "#/components/schemas/GetCostResponse"}`.


### POST /api/v2/trading/info/demo/eligibility

Check instrument trading eligibility

**Rate limit:** 20 requests per 60 seconds. This is a **dedicated** limit for this endpoint — it is **not shared** with (pooled across) any other endpoint, so the full rate is available to this endpoint alone.

---

Returns per-instrument trading configuration for the authenticated account - position limits, permitted order types, stop-loss and take-profit boundaries, and available leverage by settlement type and direction. Instruments not found are listed in notFoundInstrumentIds and notFoundSymbols. At least one of instrumentIds or symbols must be supplied; the combined length must not exceed 100 instruments. This configuration changes rarely for a given instrument and account, so call it once and reuse the result for the rest of the session instead of re-querying before every order.

Parameters (excluding common headers):
```json
[]
```

Request body:
```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/InstrumentEligibilityRequest"
      }
    }
  }
}
```

Success 200: Eligibility resolved successfully; schema `{"$ref": "#/components/schemas/InstrumentEligibilityResponse"}`.


### GET /api/v2/trading/info/demo/instrument-breakdown

Get instrument breakdown (demo)

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/trading/info/demo/pnl`
- `GET /api/v1/trading/info/demo/portfolio`

---

Returns the demo portfolio grouped by instrument, including per-position data, pending orders, and PnL.

Parameters (excluding common headers):
```json
[
  {
    "name": "CID",
    "in": "header",
    "required": true,
    "description": "Client identifier.",
    "schema": {
      "type": "integer",
      "format": "int32"
    }
  },
  {
    "name": "conversionMode",
    "in": "query",
    "required": false,
    "description": "Conversion to use for non-USD assets when the market is closed. 'eToroApp' uses the last conversion at market close; 'Realtime' uses the realtime conversion.",
    "schema": {
      "type": "string",
      "enum": [
        "eToroApp",
        "Realtime"
      ],
      "default": "eToroApp"
    }
  },
  {
    "name": "positionLevel",
    "in": "query",
    "required": false,
    "description": "Level of position data to return. 'Normal' returns position-level data; 'None' omits it.",
    "schema": {
      "type": "string",
      "enum": [
        "None",
        "Normal"
      ],
      "default": "Normal"
    }
  },
  {
    "name": "orderLevel",
    "in": "query",
    "required": false,
    "description": "Level of order data to return. 'Normal' returns order-level data; 'None' omits it.",
    "schema": {
      "type": "string",
      "enum": [
        "None",
        "Normal"
      ],
      "default": "Normal"
    }
  },
  {
    "name": "mirrorLevel",
    "in": "query",
    "required": false,
    "description": "Level of mirror data to return. 'None' returns only the manual part of the portfolio; 'Details' includes position/order-level data inside mirrors.",
    "schema": {
      "type": "string",
      "enum": [
        "None",
        "Details"
      ],
      "default": "None"
    }
  },
  {
    "name": "instrumentIds",
    "in": "query",
    "required": false,
    "description": "Filter by instrument IDs. Default: all instruments. Maximum 100 IDs.",
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      },
      "maxItems": 100
    }
  },
  {
    "name": "mirrorIds",
    "in": "query",
    "required": false,
    "description": "Filter by mirror IDs. MirrorId=0 means the manual part of the portfolio. When mirrorLevel=None the default is manual only ([0]); otherwise the default is all mirrors and manual. Maximum 100 IDs.",
    "schema": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      },
      "maxItems": 100
    }
  }
]
```

Success 200: Demo portfolio instrument breakdown.; schema `{"$ref": "#/components/schemas/InstrumentBreakdownResponseDemo"}`.


### GET /api/v2/trading/info/demo/orders:lookup

Get order information and position details

**Rate limit:** 60 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `GET /api/v1/trading/info/demo/close-orders/{orderId}`
- `GET /api/v1/trading/info/demo/orders/{orderId}`

---

Retrieves comprehensive information about a specific order, including the order status, execution details, and all positions that were opened or closed from this order. This endpoint is essential for tracking order execution and identifying which positions were created as a result of a specific order request. The response includes detailed position information with PositionID values that can be used to query position-specific details. Provide exactly one of orderId or referenceId.

Parameters (excluding common headers):
```json
[
  {
    "name": "orderId",
    "in": "query",
    "description": "Numeric order identifier. Mutually exclusive with referenceId.",
    "schema": {
      "type": "integer",
      "format": "int64"
    }
  },
  {
    "name": "referenceId",
    "in": "query",
    "description": "Request ID header sent during order submission. Mutually exclusive with orderId.",
    "schema": {
      "type": "string"
    }
  }
]
```

Success 200: Order information retrieved successfully.; schema `{"$ref": "#/components/schemas/GetOrderInfoResponse"}`.


### POST /api/v3/trading/execution/demo/orders

Submit an order for asynchronous processing

**Rate limit:** 20 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `DELETE /api/v1/trading/execution/demo/limit-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /api/v2/trading/execution/demo/orders/{orderId}`
- `DELETE /api/v3/trading/execution/demo/orders/{orderId}`
- `POST /api/v1/trading/execution/demo/limit-orders`
- `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-amount`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-units`
- `POST /api/v2/trading/execution/demo/orders`

---

This endpoint allows traders to place an order. Leverage, stop-loss, and take-profit settings can be applied. Order size must use exactly one of amount, units, or contracts. For open orders the instrument must be identified by exactly one of symbol or instrumentId - providing both is rejected. A stopLossRate is required when leverage is greater than 1, when transaction is sellShort, when settlementType is realFutures, or when stopLossType is trailing. Only the buy and sellShort transactions are currently supported. A unique X-Request-Id header (GUID) is required for idempotency. Currently only orders to open a position are supported. On this v3 create path, settlementType is mandatory for non-MIT orders and must be omitted for MIT orders. A 202 response means the order was accepted for processing, not that it was executed. Confirm the outcome with GET /api/v2/trading/info/demo/orders:lookup, passing the returned orderId - or referenceId, which echoes your X-Request-Id and is the only handle you have if this response is lost. In that response, status.id 3 (Filled) and 5 (PartiallyFilled) mean the order executed; 4 (Rejected) and 10 (RejectedPartiallyFilled) carry the reason in status.errorCode and status.errorMessage; 1 (Received), 2 (Placed), 11 (WaitingForMarket) and 12 (PendingTriggeredRate) are still in flight and should be polled again. positionExecutions lists the positionId values the order produced.

Parameters (excluding common headers):
```json
[]
```

Request body:
```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TradingDemoAdminApi_UnifiedOrderRequest"
      }
    }
  }
}
```

Success 202: Order accepted and queued for asynchronous processing. Returns the created order details.; schema `{"$ref": "#/components/schemas/UnifiedOrderResponse"}`.


### DELETE /api/v3/trading/execution/demo/orders/{orderId}

Request cancellation of a pending order

**Rate limit:** 20 requests per 60 seconds. This is a **shared quota** — the same budget is consumed by a group of related endpoints, so calling any of them reduces what is left for the others (you cannot call each at the full rate independently). Endpoints sharing this quota:
- `DELETE /api/v1/trading/execution/demo/limit-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-close-orders/{orderId}`
- `DELETE /api/v1/trading/execution/demo/market-open-orders/{orderId}`
- `DELETE /api/v2/trading/execution/demo/orders/{orderId}`
- `POST /api/v1/trading/execution/demo/limit-orders`
- `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-amount`
- `POST /api/v1/trading/execution/demo/market-open-orders/by-units`
- `POST /api/v2/trading/execution/demo/orders`
- `POST /api/v3/trading/execution/demo/orders`

---

This endpoint sends a cancellation request to cancel an order before execution. An order can be cancelled if it is waiting for the market to open, or for the trigger rate to be published (MIT orders). The cancellation request may be successful, and the order is cancelled, or unsuccessful, and the order is not cancelled. This operation is idempotent when the order is already closed or cancelled. A 202 response confirms the cancellation request was accepted, not that the order was cancelled - it may already have executed. Confirm with GET /api/v2/trading/info/demo/orders:lookup: status.id 7 (Canceled) or 9 (CanceledPartiallyFilled) means the cancellation took effect, while 6 (PendingCancel) means it is still being processed.

Parameters (excluding common headers):
```json
[
  {
    "name": "orderId",
    "in": "path",
    "required": true,
    "description": "The ID of the order to cancel.",
    "schema": {
      "type": "integer",
      "format": "int64"
    },
    "example": 13902598
  }
]
```

Success 202: Order cancellation request accepted and queued for asynchronous processing.; schema `{"$ref": "#/components/schemas/CancelOrderResponse"}`.


### Request schema: AggregatedPortfolioDemoPostRequest
```json
{
  "type": "object",
  "description": "All aggregation levels are honored. Omitted properties use the same defaults as GET.",
  "properties": {
    "conversionMode": {
      "type": "string",
      "enum": [
        "eToroApp",
        "realtime"
      ],
      "default": "eToroApp"
    },
    "pnlLevel": {
      "type": "string",
      "enum": [
        "none",
        "pnl",
        "dailyPnl"
      ],
      "default": "pnl"
    },
    "accountLevel": {
      "type": "string",
      "enum": [
        "none",
        "totals",
        "details"
      ],
      "default": "totals",
      "description": "Controls accountTotals. none omits it; totals and details include full-portfolio totals."
    },
    "instrumentLevel": {
      "type": "string",
      "enum": [
        "none",
        "totals",
        "details"
      ],
      "default": "totals",
      "description": "Controls per-instrument aggregates for both the manual (non copy-trading) portfolio and each mirror's positions \u2014 a single request-level setting, not scoped per mirror. none omits instrument-level aggregates; totals and details include them at the requested level."
    },
    "mirrorLevel": {
      "type": "string",
      "enum": [
        "none",
        "totals",
        "details"
      ],
      "default": "totals",
      "description": "Controls copy-trading data. none omits mirrors and requires mirrorFilters to be absent; totals includes mirrors without their instrument-level aggregates; details additionally includes each mirror's instrument-level aggregates, per instrumentLevel."
    },
    "instrumentIds": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      }
    },
    "mirrorFilters": {
      "type": "array",
      "nullable": true,
      "description": "Filters which copy-trading relationships to include, by mirror ID. Mirror ID 0 represents the manual (non copy-trading) part of the portfolio. When mirrorLevel is none, mirrorFilters must be absent \u2014 only the manual part of the portfolio is returned. When mirrorLevel is totals or details, an absent mirrorFilters returns all mirrors plus the manual part; an empty array returns none.",
      "items": {
        "$ref": "#/components/schemas/AggregatedPortfolioDemoMirrorFilter"
      }
    },
    "dailyCutoffUtc": {
      "type": "string",
      "format": "date-time",
      "description": "UTC timestamp representing the start of 'today' in the user's local timezone \u2014 normally the user's most recent local midnight, expressed in UTC. Required when pnlLevel is dailyPnl; rejected otherwise. Must not be more than 48 hours in the past or more than 5 minutes in the future."
    }
  }
}
```


### Request schema: InstrumentEligibilityRequest
```json
{
  "type": "object",
  "description": "Request payload for checking instrument eligibility. At least one of `instrumentIds` or `symbols` must be provided; combined length must not exceed 100 instruments.",
  "properties": {
    "instrumentIds": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int32"
      },
      "nullable": true,
      "description": "Optional list of instrument IDs to check."
    },
    "symbols": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "nullable": true,
      "description": "Optional list of instrument symbols to check."
    },
    "currency": {
      "type": "string",
      "default": "USD",
      "description": "Requested currency for financial amounts in the eligibility response (e.g. minimum position size). Currently only USD is supported."
    }
  }
}
```


### Request schema: TradingDemoAdminApi_UnifiedOrderRequest
```json
{
  "type": "object",
  "description": "Request payload for creating an order to open or close a position.",
  "required": [
    "action",
    "transaction"
  ],
  "properties": {
    "action": {
      "type": "string",
      "description": "The order action whether to open or close a position. Currently only `open` is supported in this endpoint.",
      "enum": [
        "open",
        "close"
      ],
      "example": "open"
    },
    "transaction": {
      "type": "string",
      "description": "The transaction direction: `buy` opens a long position, `sell` closes a long position, `sellShort` opens a short position, and `buyToCover` closes a short position. Currently only `buy` and `sellShort` are supported; `sell` and `buyToCover` are rejected and will be enabled in a future release alongside the `close` action.",
      "enum": [
        "buy",
        "sell",
        "sellShort",
        "buyToCover"
      ],
      "example": "buy"
    },
    "symbol": {
      "type": "string",
      "description": "The asset ticker symbol. For open orders provide exactly one of symbol or instrumentId - providing both is rejected.",
      "nullable": true,
      "example": "AAPL"
    },
    "instrumentId": {
      "type": "integer",
      "format": "int32",
      "description": "The etoro instrument identifier. For open orders provide exactly one of symbol or instrumentId - providing both is rejected.",
      "nullable": true,
      "example": 101
    },
    "settlementType": {
      "type": "string",
      "description": "The settlement type. Possible values: cfd, real, realFutures, marginTrade. Version rules: on Public API v2 create (`POST /api/v2/trading/execution/demo/orders`, Admin v1) settlementType remains optional. On Public API v3 create (`POST /api/v3/trading/execution/demo/orders`, Admin v2) it must NOT be set for MIT orders (the platform resolves it), and for all other order types it must be set to an eligible settlement type. A mismatch is rejected during execution after the order has already been accepted with an order id. The valid values differ per instrument, direction and leverage - call `POST /api/v2/trading/info/demo/eligibility` and read `leverageConfigs[].settlementType` for the relevant combinations of `direction`, `leverage` and `settlementType` before supplying them; that configuration changes rarely, so one call can be cached and reused for the whole session. `real` - the real instrument held in full value. `realFutures` - the real future contract, which is a derivative of an underlying instrument. Each future contract usually maintains a different number of underlying instrument units than 1. The number of units held in a single future contract is called the multiplier, which can be bigger, lower, or equal to 1. `marginTrade` - the real instrument held with only a portion of its value called margin (leveraged asset). `cfd` - contract for difference, which is a derivative following the underlying instrument.",
      "nullable": true,
      "enum": [
        "cfd",
        "real",
        "realFutures",
        "marginTrade"
      ]
    },
    "orderType": {
      "type": "string",
      "description": "The order execution type. Possible values: mkt (market), mit (market if touched), limitIOC. `mkt` - a market order that executes at the available market price. `mit` - a market-if-touched order that waits until the triggerRate or better is published in the market feed and then executes at the market price at that time. `limitIOC` - an immediate limit order that executes now at the limitRate or better if such a rate is available at the market, or gets cancelled immediately if no such rate is available now. `mit` is not supported when settlementType is realFutures.",
      "enum": [
        "mkt",
        "mit",
        "limitIOC"
      ],
      "example": "mkt"
    },
    "triggerRate": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "The trigger rate for mit orders. Required for mit orders, and must be greater than zero. Must not be provided for mkt or limitIOC orders - supplying it is rejected."
    },
    "leverage": {
      "type": "integer",
      "format": "int32",
      "description": "The leverage multiplier to apply. Optional - defaults to 1 (no leverage) when omitted, and must be 1 or greater. Any value greater than 1 requires stopLossRate.",
      "nullable": true,
      "example": 2
    },
    "amount": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "The monetary amount to invest in the order currency. Mutually exclusive with units and contracts. Must be greater than 0.",
      "example": 1000.0
    },
    "orderCurrency": {
      "type": "string",
      "description": "The currency for the order amount. Typically usd. Only USD is currently supported.",
      "nullable": true,
      "example": "usd"
    },
    "units": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "The number of units to trade. Mutually exclusive with amount and contracts. Must be greater than 0."
    },
    "contracts": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "The number of contracts to trade, used for real futures instead of units. Mutually exclusive with amount and units. Only accepted when settlementType is realFutures, and must be a whole number greater than 0."
    },
    "stopLossRate": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "The stop-loss rate at which the position will automatically close. Required when leverage is greater than 1, when transaction is sellShort, when settlementType is realFutures, or when stopLossType is trailing. Optional otherwise, and must be 0 or greater.",
      "example": 1.2
    },
    "takeProfitRate": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "The take-profit rate at which the position will automatically close. Must be 0 or greater.",
      "example": 1.5
    },
    "stopLossType": {
      "type": "string",
      "nullable": true,
      "description": "The stop-loss type. Possible values: fixed, trailing. The default is `fixed`. `fixed` - the stop-loss rate does not change. `trailing` - the stop-loss rate moves up whenever the instrument rate goes up such that the stop loss is triggered from the same distance from the last peak rate as the distance of the stop-loss rate from the rate at the open. Setting `trailing` requires stopLossRate.",
      "enum": [
        "fixed",
        "trailing"
      ],
      "example": "fixed"
    },
    "additionalMargin": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "Additional funds in the order currency added to the invested amount (margin), if the desire is for the stop-loss rate to be set lower than normally permitted. Only accepted when settlementType is realFutures - supplying it for any other settlement type is rejected. Must be greater than 0."
    },
    "limitRate": {
      "type": "number",
      "format": "double",
      "nullable": true,
      "description": "LimitRate should be set for LimitIOC orders only, where it is required and must be greater than zero; supplying it for any other order type is rejected. it is the client submitted price which will be routed to the exchange for execution. Please note that a client submitted price cannot exceed a 10% deviation from current market price otherwise it will be rejected on pre trade",
      "example": 1.5
    },
    "positionIds": {
      "type": "array",
      "items": {
        "type": "integer",
        "format": "int64"
      },
      "nullable": true,
      "description": "List of position IDs to close. Reserved for the close action, which is not supported yet - supplying any value is currently rejected."
    }
  }
}
```


### Request schema: UpdatePositionRequest
```json
{
  "type": "object",
  "description": "Request payload for patching position stop-loss and take-profit risk parameters.",
  "properties": {
    "stopLossRate": {
      "type": "number",
      "format": "decimal",
      "nullable": true,
      "description": "New stop-loss rate for the position. Note that deepening a stop loss beyond the allowed maximum stop loss will cause funds to be transferred from the account balance into the position margin."
    },
    "takeProfitRate": {
      "type": "number",
      "format": "decimal",
      "nullable": true,
      "description": "New take-profit rate for the position."
    },
    "stopLossType": {
      "type": "string",
      "nullable": true,
      "enum": [
        "fixed",
        "trailing"
      ],
      "description": "Stop-loss type. `fixed` - the stop-loss rate does not change. `trailing` - the stop-loss rate moves up whenever the instrument rate goes up such that the stop loss is triggered from the same distance from the last peak rate as the distance of the stop-loss rate from the rate at the open."
    },
    "clearStopLoss": {
      "type": "boolean",
      "nullable": true,
      "description": "When true, removes stop-loss from the position, if the system allows the position to clear its stop loss. Normally it cannot be done for leveraged and future positions."
    },
    "clearTakeProfit": {
      "type": "boolean",
      "nullable": true,
      "description": "When true, removes take-profit from the position."
    }
  },
  "additionalProperties": false
}
```

## Phase 3 execution schema verification (2026-10-27)

Re-fetched https://api-portal.etoro.com/api-reference/openapi.json before implementation. Relevant additional schema details:

- `InstrumentEligibility`: currency-normalized `minPositionExposure`, `maxUnitsPerOrder`, allowOpen/Close/PartialClosePosition, unitsQuantityType (`whole`/`fractional`), allowedOrderQuantityType (`unitsOnly`/`amountOnly`/`all`), tradeUnitType, additionalBufferPercent and leverageConfigs.
- `LeverageConfiguration`: settlementType, direction, leverageValues, isPotential, minPositionAmount, allowStopLossTakeProfit and min/maxStopLossPercentage. Percentages are explicitly described relative to allocated margin. Positive broker buffer percentages are not implemented because their exact reservation convention remains unclear.
- `UnifiedOrderResponse`: orderId, referenceId (echoes x-request-id), token. 202 is acceptance only.
- `GetOrderInfoResponse`: accountId, orderId, action, transaction, type, status.id, asset (instrumentId, currency, settlementType, leverage, side), requestedUnits and positionExecutions[].openingData.units. RemainingUnits must not be used to infer historical executed quantity.
- `GetOrderInfoStatus`: 1 Received, 2 Placed, 3 Filled, 4 Rejected, 5 PartiallyFilled, 6 PendingCancel, 7 Canceled, 8 Expired, 9 CanceledPartiallyFilled, 10 RejectedPartiallyFilled, 11 WaitingForMarket, 12 PendingTriggeredRate.
- Close submission: `POST /api/v1/trading/execution/demo/market-close-orders/positions/{positionId}` with InstrumentID and explicit UnitsToDeduct. Its 200 means submitted, not filled; use orderForClose.orderID to poll `GET /api/v1/trading/info/demo/close-orders/{orderId}`.
- `OrderForCloseInfoResponse`: orderID, CID, instrumentID, statusID and positions[] with positionID/occurred/rate/units. Close statuses 3/4/7/8/9/10 are terminal; 1/2/5/6/11 pending. Statuses 9/10 include real partial execution within the Demo account. A cancelled order without execution has no executed position entries.
- No documented close lookup by client request UUID was found. Without a returned close order ID, timeout recovery remains manual. No close POST idempotency guarantee is inferred from opening order documentation.

The implementation uses fixed attached stopLossRate only after account eligibility confirms support. Take-profit, trailing stops, stop modification, cancel submissions and unified v3 close are not implemented. See DEMO_EXECUTION.md for the exact allowlist, payload policy, dispatch journal and deployment blockers.

## Phase 4 scanner contract review (2026-10-27)

A fresh GET of the official OpenAPI URL returned HTTP 403. Scanner implementation instead re-inspected the official schema successfully retrieved during Phase 3 earlier in this environment (SHA-256 `6fef7174f485d4bce880b85e7c0f5f0a71637f4dd9ced8258b94d2d4ce87a491`). This is a saved official source, not a newly successful remote verification. No authenticated requests or credential inspection occurred.

[MARKET_SCANNER.md](MARKET_SCANNER.md) records the exact four-route scanner allowlist, request/response fields, batching limits, indicator definitions and deployment gaps. Routes are v2 instruments (cursor pagination with `type=Stocks/ETF`), v2 rates (1000 IDs, 206 partial), documented v1 hourly OHLCV candles (100 candles requested; max documented 1000), and non-executing v2 Demo eligibility (100 IDs, USD). No fundamental-data route or FX instrument ID was invented. The v2 metadata schema does not establish currency, embedded ETF leverage, or a complete trading calendar; external verified evidence is required. Unknown/missing volume is not synthesized. Quota ownership must be shared with any future concurrent client using the same key.
