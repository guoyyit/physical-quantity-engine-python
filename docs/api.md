# HTTP API

All requests and responses are JSON. Errors use a stable envelope:

```json
{"error": {"code": "DIMENSION_MISMATCH", "message": "..."}}
```

See [errors.md](errors.md) for the code list and HTTP status mapping.

## `GET /health`

Liveness plus the current catalog head version.

```json
{"status": "ok", "head_version": 3}
```

## `GET /units`

Lists every registered unit name (base, prefixed, derived and accepted).

```json
{"units": ["A", "GeV", "kg", "km", "m/s^2", "..."]}
```

## `POST /catalog/commit`

Atomically add or replace entries; returns the new head version. Values
are converted to SI base units before publishing.

Request:

```json
{
  "baseVersion": 2,
  "entries": [
    {"name": "distance", "value": "100", "unit": "km", "uncertainty": "0.5"},
    {"name": "elapsed", "value": "2", "unit": "h"}
  ]
}
```

Response:

```json
{"version": 3, "entry_count": 4}
```

`baseVersion` is optional optimistic concurrency control: a stale value
yields `409 CATALOG_CONFLICT`. `uncertainty` is optional, must be
non-negative and is given in the same unit as `value`.

## `GET /catalog/versions/{version}`

Returns the complete, immutable content of one catalog version.

## `POST /evaluate`

Evaluates one expression against a catalog version.

Request:

```json
{
  "expression": "distance / elapsed",
  "version": 3,
  "outputUnit": "km/h"
}
```

- `version` optional (defaults to head at request start).
- `outputUnit` optional; defaults to the coherent SI base-unit string
  (e.g. `m*s^-1`).

Response:

```json
{
  "value": "50.0000000000",
  "unit": "km/h",
  "uncertainty": null,
  "dimension": [1, 0, -1, 0, 0, 0, 0],
  "version": 3,
  "expression": "distance / elapsed"
}
```

`dimension` is the `(L, M, T, I, Θ, N, J)` exponent vector. Values are
fixed-point decimal strings; `uncertainty` is `null` or a decimal string.

### Expression language

```
expr   := term (('+' | '-') term)*
term   := factor (('*' | '/') factor)*
factor := unary ('^' integer-power)?
unary  := ('+' | '-') unary | primary
primary:= number | constant | NAME | NAME '(' expr ')' | '(' expr ')'
```

- Names: `[A-Za-z_][A-Za-z0-9_]*`; numbers are finite decimal literals.
- Constants: `pi`, `e` (reserved, cannot be catalog names).
- Functions: `sqrt, abs, sin, cos, tan, asin, acos, atan, exp, ln,
  log10, log2` (trigonometry in radians).
- `^` takes an integer exponent.

## `POST /convert`

Converts a single value directly (no catalog needed).

Request:

```json
{"value": "100", "unit": "km/h", "targetUnit": "m/s", "uncertainty": "2"}
```

Response:

```json
{"value": "27.8", "unit": "m/s", "uncertainty": "0.6",
 "dimension": [1, 0, -1, 0, 0, 0, 0]}
```

The whole call is all-or-nothing: a dimension or unit error returns no
value.

## Batch evaluation

### `POST /batch`

Submit multiple independent items.

```json
{"items": [
  {"id": "a", "expression": "1+1", "timeout_ms": 10000},
  {"id": "b", "expression": "distance/elapsed", "version": 3,
   "outputUnit": "km/h", "timeout_ms": 5000}
]}
```

Response: `{"batch_id": "...", "status": "RUNNING"}`.

### `GET /batch/{batch_id}`

Polls status and per-item results. Each item has one terminal status:

- `OK` with `result`
- `ERROR` with `error` (any evaluation error code)
- `TIMEOUT` (`TASK_TIMEOUT`), no result
- `CANCELLED` (`TASK_CANCELLED`), no result

Items are isolated: a failure, timeout or cancellation of one item never
changes the outcome of another. Timeout or cancelled items never expose
partial results.

### `POST /batch/{batch_id}/cancel`

Cooperatively cancels a batch: pending items are marked `CANCELLED`
immediately and running items stop at their next cooperation point.
Returns `{"batch_id": "...", "status": "CANCELLED"}`.
