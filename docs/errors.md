# Error codes and semantics

Every failure returns HTTP `4xx`/`5xx` with a single stable envelope:

```json
{"error": {"code": "<CODE>", "message": "human readable explanation"}}
```

Codes never change between releases; messages may be refined but always
state the operands/units/version involved. A failed call never returns a
result field and never returns `200`.

| code | HTTP | meaning |
|---|---|---|
| `PARSE_ERROR` | 400 | Expression (or compound unit) syntax error; non-integer exponent; malformed token. |
| `INVALID_ARGUMENT` | 400 | Well-formed request with an illegal value: malformed number, negative uncertainty, unknown function, function argument out of domain (`ln(-1)`, `asin(2)`, `tan` at a pole), invalid name, non-positive timeout, empty/duplicate batch. |
| `UNKNOWN_UNIT` | 400 | Unit name not registered, or malformed unit string. |
| `UNKNOWN_NAME` | 404 | Named quantity is absent in the pinned catalog version. |
| `VERSION_NOT_FOUND` | 404 | Requested catalog version does not exist. |
| `BATCH_NOT_FOUND` | 404 | Batch id is unknown. |
| `DIMENSION_MISMATCH` | 422 | Operands have incompatible dimensions in `+/-`, an argument to a dimensionless function is dimensioned, `sqrt` exponents are odd, the output/target unit dimension differs, or conversion spans dimensions. |
| `NON_FINITE_VALUE` | 422 | `inf`/`NaN` supplied as input or produced during conversion/evaluation. |
| `OVERFLOW` | 422 | A numeric result exceeds the 50-digit Decimal range (e.g. `exp(1e6000)`). |
| `DIVISION_BY_ZERO` | 422 | Division by the literal zero or by a quantity whose value is zero. |
| `UNIT_CONVERSION_FAILED` | 422 | Conversion is structurally invalid, currently only an offset unit (`degC`) appearing inside a compound unit. |
| `CATALOG_CONFLICT` | 409 | Optimistic commit: `baseVersion` is not the current head, or a catalog entry shadows a reserved constant. |
| `TASK_TIMEOUT` | 408 | A batch item exceeded its `timeout_ms`; no result is published for it. |
| `TASK_CANCELLED` | 499 | A batch (or item) was cancelled before or during execution; no result is published. |
| `INTERNAL_ERROR` | 500 | Unexpected defensive failure. Domain errors are always mapped to one of the specific codes above. |

## Distinguishable rejection reasons

The most important distinct codes for physical computations:

- syntactic problems → `PARSE_ERROR`
- missing data in the chosen version → `UNKNOWN_NAME` / `VERSION_NOT_FOUND`
- dimensional problems → `DIMENSION_MISMATCH`
- numeric-domain problems → `NON_FINITE_VALUE`, `OVERFLOW`,
  `DIVISION_BY_ZERO`, `INVALID_ARGUMENT`
- unit problems → `UNKNOWN_UNIT` / `UNIT_CONVERSION_FAILED`

Callers can therefore distinguish "I typed the expression wrong" from "the
units are incompatible" from "the quantity does not exist in this
version" from "the arithmetic is undefined".

## Batch error isolation

Inside a batch, evaluation errors appear **per item** (`status: ERROR`)
and never fail the whole batch or sibling items. `TASK_TIMEOUT` and
`TASK_CANCELLED` are likewise per item (and set the batch status); their
items always have `result: null`, so timeout or cancellation cannot leave
partial output.
