# Units and prefixes

Units are converted to coherent SI base units through

```
value_base = scale * value + offset
```

## Base units

| symbol | dimension | base scale |
|---|---|---|
| `m`   | length | 1 (m) |
| `g`   | mass | 0.001 (the coherent unit is `kg`) |
| `s`   | time | 1 (s) |
| `A`   | electric current | 1 (A) |
| `K`   | thermodynamic temperature | 1 (K) |
| `mol` | amount of substance | 1 (mol) |
| `cd`  | luminous intensity | 1 (cd) |

`kg` is registered explicitly, and every other mass prefix is built from
the gram (`mg`, `Mg`, ...), so `1 kg = 1000 g` always.

## SI prefixes

All 20 SI prefixes are supported on prefixable units, for example
`km`, `mm`, `ms`, `MHz`, `kN`, `µg`/`ug`, `nmol`, `TWh`.

```
Q R Y Z E P T G M k h da d c m u/µ n p f a z y r q
```

The Greek `µ` and ASCII `u` are equivalent.

## Named derived units

| unit | quantity | base dimensions |
|---|---|---|
| `Hz`  | frequency | T⁻¹ |
| `N`   | force | L·M·T⁻² |
| `Pa`  | pressure | L⁻¹·M·T⁻² |
| `J`   | energy | L²·M·T⁻² |
| `W`   | power | L²·M·T⁻³ |
| `C`   | charge | I·T |
| `V`   | voltage | L²·M·T⁻³·I⁻¹ |
| `F`   | capacitance | I²·T⁴·L⁻²·M⁻¹ |
| `Ohm` (`Ω`) | resistance | L²·M·T⁻³·I⁻² |
| `S`   | conductance | L⁻²·M⁻¹·T³·I² |
| `Wb`  | magnetic flux | L²·M·T⁻²·I⁻¹ |
| `T`   | magnetic flux density | M·T⁻²·I⁻¹ |
| `H`   | inductance | L²·M·T⁻²·I⁻² |
| `rad`, `sr` | dimensionless | 1 |
| `Gy`, `Sv` | absorbed/equivalent dose | L²·T⁻² |

Derived units accept SI prefixes too (`kPa`, `MJ`, `GHz`, `mOhm`).

## Accepted non-SI units

| unit | meaning |
|---|---|
| `min` | minute = 60 s |
| `h`   | hour = 3600 s |
| `d`   | day = 86 400 s |
| `L` (also `l`) | litre = 0.001 m³ (prefixable: `mL`) |
| `t`   | tonne = 1000 kg |
| `eV`  | electronvolt = 1.602176634e-19 J (prefixable) |
| `degC` / `°C` | degree Celsius, offset 273.15 K |
| `percent` | 0.01 (dimensionless) |

`degC` is an **affine** unit: `0 °C = 273.15 K`. It is accepted only as a
standalone unit. It cannot be multiplied, divided or raised to a power
(`degC/s` is rejected with `UNIT_CONVERSION_FAILED`), because an offset is
not meaningful in a compound unit.

## Compound units

A compound unit is a product/quotient of simple units with integer
exponents:

```
unit      := factor (('*' | '/') factor)*
factor    := NAME ('^' signed_int)?
```

Examples:

- `m/s^2`
- `kg*m/s^2`
- `km/h`
- `m*s^-2`
- `N*m`
- `mol/L`

Division groups a single following factor; write `kg/(m*s^2)` without
spaces around parentheses, or equivalently `kg*m^-1*s^-2`. A bare
registered name (including `degC`) is always accepted directly.

## Errors

- unknown or misspelled unit → `UNKNOWN_UNIT`
- offset unit inside a compound → `UNIT_CONVERSION_FAILED`
- converting between units of different dimension → `DIMENSION_MISMATCH`
