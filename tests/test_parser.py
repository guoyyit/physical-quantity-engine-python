import pytest

from pqe.errors import EngineError, ErrorCode
from pqe.parser import Binary, FuncCall, Number, Unary, parse


def test_operator_precedence():
    node = parse("1 + 2 * 3")
    assert isinstance(node, Binary)
    assert node.op == "+"
    assert isinstance(node.right, Binary)
    assert node.right.op == "*"


def test_parentheses_override_precedence():
    node = parse("(1 + 2) * 3")
    assert node.op == "*"
    assert node.left.op == "+"


def test_unary_minus_and_power():
    assert isinstance(parse("-x"), Unary)
    assert parse("2^-3").right.text == "-3"
    assert parse("2^3").right.text == "3"


def test_chained_integer_power_supported():
    # 2^3^2 = 2^(3^2) = 512, a statically integer exponent.
    node = parse("2^3^2")
    assert node.op == "^"
    assert node.right.text == "9"


def test_function_call():
    node = parse("sin(x + 1)")
    assert isinstance(node, FuncCall)
    assert node.name == "sin"
    assert isinstance(node.arg, Binary)


def test_number_forms_and_names():
    assert isinstance(parse("1e3"), Number)
    assert isinstance(parse(".5"), Number)
    assert parse("v_1").name == "v_1"


@pytest.mark.parametrize("text", [
    "", "1 +", "* 2", "(1+2", "1 2", "a@b", "1^x", "sin(x",
    "2^^3", "+", "()", "1 + )",
])
def test_syntax_errors(text):
    with pytest.raises(EngineError) as exc:
        parse(text)
    assert exc.value.code is ErrorCode.PARSE_ERROR


def test_non_string_rejected():
    with pytest.raises(EngineError) as exc:
        parse(123)
    assert exc.value.code is ErrorCode.PARSE_ERROR
