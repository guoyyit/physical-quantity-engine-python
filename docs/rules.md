# Evaluation, precision and uncertainty rules

This document fixes the rules used by the engine. Because all of them are
fixed (no platform floating point, no configurable rounding), the same
inputs evaluated under the same catalog version always produce **identical
output**.

## 1. Internal representation

- Every quantity is stored as a `Decimal` value expressed in **coherent SI
  base units** (`m, kg, s, A, K, mol, cd`) together with a 7-integer
  dimension vector `(L, M, T, I, Θ, N, J)` and an optional standard
  uncertainty in the same base units.
- Catalog inputs are converted to base units exactly when committed; the
  original unit string is retained for display.
- Internal arithmetic runs in a single `Decimal` context:

  | setting | value |
  |---|---|
  | precision | 50 significant digits |
  | rounding | `ROUND_HALF_EVEN` (banker's rounding) |
  | traps | `InvalidOperation`, `DivisionByZero`, `Overflow` |

  `inf`, `-inf` and `NaN` are never accepted at any boundary and never
  produced in output; encountering them raises `NON_FINITE_VALUE`.

## 2. Dimensions and consistency

- Addition/subtraction require identical dimension vectors.
- Multiplication/division add/subtract exponent vectors.
- The exponent operator `^` requires an **integer** exponent (a literal or
  a statically evaluable tower of integer literal powers) so that the
  resulting dimension always has integer exponents.
- `sqrt` is allowed only when every dimension exponent is even.
- `sin, cos, tan, asin, acos, atan, exp, ln, log10, log2` require a
  **dimensionless** argument. `abs` accepts any dimension. `sqrt` is the
  only function that changes dimension.
- A mismatch raises `DIMENSION_MISMATCH` with a message naming both
  dimensions (e.g. `L` vs `T`).

## 3. Uncertainty propagation

Input quantities are treated as **mutually independent** and uncertainties
are interpreted as standard uncertainties. First-order propagation
(root-sum-of-squares of partial derivatives) is used:

- addition / subtraction `z = x ± y`:

  `u(z) = sqrt(u(x)^2 + u(y)^2)`

- multiplication `z = x·y`:

  `u(z) = sqrt((u(x)·y)^2 + (x·u(y))^2)`

- division `z = x/y`:

  `u(z) = sqrt((u(x)/y)^2 + (x·u(y)/y^2)^2)`

- integer power `z = x^n`:

  `u(z) = |n·x^(n-1)·u(x)|`

- functions `z = f(x)`: `u(z) = |f'(x)|·u(x)`, e.g.
  `u(sin x) = |cos x|·u(x)`, `u(exp x) = exp(x)·u(x)`,
  `u(ln x) = u(x)/x`.

Quantities without an uncertainty behave as exactly known; an operation
produces an uncertainty only if at least one operand carried one (in which
case missing uncertainties are treated as zero). Uncertainties are always
non-negative.

## 4. Result rounding and presentation

- If a quantity has **no** uncertainty, its value is rounded to
  **12 significant digits**.
- If it has an uncertainty, the uncertainty is rounded with the standard
  GUM convention:
  - **2 significant digits** when the first two significant digits are in
    `10..29`;
  - **1 significant digit** otherwise (`30..99`).
- The value is then rounded to the **same decimal place** as the rounded
  uncertainty.
- Output uses fixed-point decimal text (never scientific notation);
  trailing zeros are preserved because they encode precision
  (`50.00`, not `50`).
- Rounding never changes the internal base-unit value; only the rendered
  result is rounded.

## 5. Unit conversion

- A unit maps to base units through `value_base = scale·value + offset`.
- Most units have zero offset; `degC` has offset `273.15`. Offset units are
  only accepted standalone (never inside compound units such as `degC/s`),
  because affine units do not multiply.
- Conversion first checks dimension equality. A mismatch raises
  `DIMENSION_MISMATCH`; an unparseable or unknown unit raises
  `UNKNOWN_UNIT`; using an offset unit inside a compound raises
  `UNIT_CONVERSION_FAILED`.
- Conversion is all-or-nothing: validation, base conversion and target
  conversion run in order and any failure raises before any result is
  returned — no partial result is possible.
- Uncertainties convert with the linear scale (offset does not affect an
  uncertainty interval).

## 6. Catalog versions and atomicity

- The catalog starts at immutable version `0` (empty).
- Each successful commit creates version `n+1` as a fully built immutable
  mapping; it is published in a single locked step, so readers always see a
  complete version.
- Requests may pin `version`; omitted means the current head at request
  start.
- A commit may carry `baseVersion` for optimistic concurrency control: if
  it differs from the head at commit time the commit is rejected with
  `CATALOG_CONFLICT` and nothing is written.

## 7. Exceptional inputs

| situation | code |
|---|---|
| `inf`/`NaN` input, or non-finite computed result | `NON_FINITE_VALUE` |
| intermediate result exceeds the 50-digit range | `OVERFLOW` |
| division by zero (numeric or zero-valued divisor) | `DIVISION_BY_ZERO` |
| incompatible dimensions | `DIMENSION_MISMATCH` |
| function argument out of domain (`ln(-1)`, `asin(2)`, ...) | `INVALID_ARGUMENT` |
| syntax error | `PARSE_ERROR` |
| unknown quantity name | `UNKNOWN_NAME` |

Failures always carry a stable `code` and a human-readable `message`; the
service never returns `null` in place of a result and never reports success
for a failed computation.

## 8. Determinism notes

- Transcendental functions (`sin`, `exp`, `ln`, ...) are computed from fixed
  high-precision constants and series under the shared Decimal context;
  results are bit-for-bit repeatable across runs on the same Python/decimal
  implementation.
- Trigonometric arguments use radians and are range-reduced against a fixed
  50-digit π; `pi` and `e` are reserved dimensionless constants.
