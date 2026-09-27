# Physical Quantity Evaluation Service (Python)

A local service that evaluates expressions over **named physical quantities**
with **unit conversion** and **uncertainty propagation**, enforcing
dimensional consistency with stable, deterministic error codes.

## Features

- Expression parsing and evaluation with named quantities, decimal scalar
  literals, `+ - * / ^`, parentheses and common unary functions.
- Strict dimensional analysis: adding incompatible quantities, passing a
  dimensioned value to a dimensionless function, or converting between
  incompatible units is rejected with a distinct, explainable error.
- SI base units, all SI prefixes and named derived units (`N`, `Pa`, `J`,
  `W`, `V`, `Ohm`, ...) plus selected accepted units (`min`, `h`, `L`, `t`,
  `eV`, `degC`); compound units such as `kg*m/s^2` or `km/h`.
- First-order uncertainty propagation treating inputs as independent; fixed
  precision (50 decimal digits), fixed rounding (`ROUND_HALF_EVEN`) and a
  fixed GUM-style presentation rule, so the same request always yields the
  same bytes.
- Append-only, versioned catalog with **atomic** commits. Every evaluation
  is pinned to one immutable version; concurrent commits never expose a
  mixed snapshot, and stale commits fail with `CATALOG_CONFLICT`.
- Deterministic rejection of non-finite values, overflow, division by zero
  and dimension mismatch — never `null` or a fake success.
- Isolated batch evaluation with per-item timeout and cooperative
  cancellation; one item failing never pollutes another and timeout or
  cancellation leaves no partial result.

## Quick start

```bash
uv sync
uv run uvicorn pqe.__main__:app --port 8000
```

Run the tests:

```bash
uv run pytest
```

## Worked example

Add quantities (values are converted to SI base units at commit time):

```bash
curl -sX POST localhost:8000/catalog/commit -H 'content-type: application/json' \
  -d '{"entries":[{"name":"distance","value":"100","unit":"km"},
                  {"name":"elapsed","value":"2","unit":"h"}]}'
# {"version":1,"entry_count":2}
```

Evaluate and convert the result:

```bash
curl -sX POST localhost:8000/evaluate -H 'content-type: application/json' \
  -d '{"expression":"distance / elapsed","version":1,"outputUnit":"km/h"}'
# {"value":"50.0000000000","unit":"km/h","uncertainty":null,
#  "dimension":[1,0,-1,0,0,0,0],"version":1,
#  "expression":"distance / elapsed"}
```

Direct unit conversion:

```bash
curl -sX POST localhost:8000/convert -H 'content-type: application/json' \
  -d '{"value":"0","unit":"degC","targetUnit":"K"}'
# {"value":"273.150000000","unit":"K","uncertainty":null,...}
```

## Documentation

- [docs/rules.md](docs/rules.md) — arithmetic, dimension, precision and
  rounding rules; uncertainty formulas.
- [docs/units.md](docs/units.md) — supported units, prefixes and the
  compound-unit grammar.
- [docs/api.md](docs/api.md) — HTTP endpoints and request/response shapes.
- [docs/errors.md](docs/errors.md) — error codes, HTTP status and semantics.

## Layout

```
pqe/
  errors.py      stable error codes + EngineError
  dimensions.py  7-component SI dimension vectors
  numeric.py     fixed Decimal context and deterministic rounding
  units.py       base/prefixed/derived units + compound parser
  quantity.py    arithmetic, unary functions, uncertainty propagation
  parser.py      tokenizer + recursive-descent expression parser
  catalog.py     append-only atomic versioned catalog
  evaluator.py   AST evaluation, output conversion
  batch.py       isolated, timeout-aware, cancellable batch runner
  service.py     FastAPI application
tests/           pytest suite (dimension, units, uncertainty, concurrency,
                 exceptional inputs, cancellation, HTTP)
```
