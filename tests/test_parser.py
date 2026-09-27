import pytest

from pqengine.errors import EngineError, ErrorCode
from pqengine.parser import (
    Binary,
    Name,
    Number,
    Unary,
    parse,
)


def test_number():
    node = parse("3.14")
    assert node == Number(3.14)
    assert parse("1e-3") == Number(0.001)
    assert parse(".5") == Number(0.5)


def test_name():
    assert parse("x") == Name("x")
    assert parse("v_1") == Name("v_1")


def test_binary_precedence():
    node = parse("a + b * c")
    assert node == Binary("+", Name("a"), Binary("*", Name("b"), Name("c")))
    node = parse("a * b + c")
    assert node == Binary("+", Binary("*", Name("a"), Name("b")), Name("c"))


def test_left_associative():
    assert parse("a - b - c") == Binary(
        "-", Binary("-", Name("a"), Name("b")), Name("c")
    )
    assert parse("a / b / c") == Binary(
        "/", Binary("/", Name("a"), Name("b")), Name("c")
    )


def test_unary_and_functions():
    assert parse("-a") == Unary("neg", Name("a"))
    assert parse("--a") == Unary("neg", Unary("neg", Name("a")))
    assert parse("sqrt(a)") == Unary("sqrt", Name("a"))
    node = parse("sin(a + b)")
    assert node == Unary("sin", Binary("+", Name("a"), Name("b")))


def test_power_precedence_and_exponents():
    node = parse("a^2")
    assert node == Binary("^", Name("a"), Number(2.0))
    node = parse("a^-2")
    assert node == Binary("^", Name("a"), Unary("neg", Number(2.0)))
    node = parse("a^(1+1)")
    assert node == Binary("^", Name("a"), Binary("+", Number(1.0), Number(1.0)))
    assert parse("a^2^3") == Binary(
        "^", Name("a"), Binary("^", Number(2.0), Number(3.0))
    )


def test_parentheses():
    assert parse("(a + b) * c") == Binary(
        "*", Binary("+", Name("a"), Name("b")), Name("c")
    )


@pytest.mark.parametrize("text", [
    "", "   ", "a +", "* a", "a b", "(a", "a)", "frob(a)",
    "a^b", "a^", "2..3", "@", "a + * b", "sqrt(a",
])
def test_parse_errors(text):
    with pytest.raises(EngineError) as exc:
        parse(text)
    assert exc.value.code == ErrorCode.PARSE_ERROR


def test_non_string():
    with pytest.raises(EngineError) as exc:
        parse(123)  # type: ignore[arg-type]
    assert exc.value.code == ErrorCode.PARSE_ERROR
