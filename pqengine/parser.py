"""Tokenizer, recursive-descent parser and AST for physical expressions.

Grammar::

    expression := term (("+" | "-") term)*
    term       := factor (("*" | "/") factor)*
    factor     := unary ("^" exponent)?
    exponent   := "-" number | number | "(" expression ")"
    unary      := "-" unary | "+" unary | NAME "(" expression ")" | primary
    primary    := number | NAME | "(" expression ")"
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import EngineError, ErrorCode

UNARY_FUNCTIONS = ("neg", "abs", "sqrt", "sqr", "sin", "cos", "tan",
                   "log", "ln", "exp")


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: Node


@dataclass(frozen=True)
class Binary:
    op: str
    left: Node
    right: Node


Node = Number | Name | Unary | Binary

_TOKEN_RE = re.compile(
    r"\s*("
    r"[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?"
    r"|\.[0-9]+(?:[eE][+-]?[0-9]+)?"
    r"|[A-Za-z_][A-Za-z0-9_]*"
    r"|[+\-*/^()]"
    r")"
)


class _Tokenizer:
    def __init__(self, text: str) -> None:
        self.tokens: list[str] = []
        pos = 0
        while pos < len(text):
            m = _TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                raise EngineError(
                    ErrorCode.PARSE_ERROR,
                    f"unexpected character at position {pos}: {text[pos:]!r}",
                )
            self.tokens.append(m.group(1))
            pos = m.end()
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> str | None:
        tok = self.peek()
        if tok is not None:
            self.pos += 1
        return tok


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tok = _Tokenizer(text)

    def parse(self) -> Node:
        if self.tok.peek() is None:
            raise EngineError(ErrorCode.PARSE_ERROR, "empty expression")
        node = self.expression()
        if self.tok.peek() is not None:
            raise EngineError(
                ErrorCode.PARSE_ERROR,
                f"unexpected token {self.tok.peek()!r} at position "
                f"{self.tok.pos}",
            )
        return node

    def expression(self) -> Node:
        node = self.term()
        while self.tok.peek() in ("+", "-"):
            op = self.tok.next()
            right = self.term()
            node = Binary(op, node, right)
        return node

    def term(self) -> Node:
        node = self.factor()
        while self.tok.peek() in ("*", "/"):
            op = self.tok.next()
            right = self.factor()
            node = Binary(op, node, right)
        return node

    def factor(self) -> Node:
        base = self.unary()
        if self.tok.peek() == "^":
            self.tok.next()
            exponent = self.factor()  # right associative: a^b^c == a^(b^c)
            base = Binary("^", base, exponent)
        return base

    def unary(self) -> Node:
        tok = self.tok.peek()
        if tok in ("+", "-"):
            self.tok.next()
            operand = self.unary()
            return Unary("neg" if tok == "-" else "pos", operand)
        if tok is not None and (tok[0].isalpha() or tok == "_") and self.is_call():
            name = self.tok.next()
            self.tok.next()  # "("
            if name not in UNARY_FUNCTIONS:
                raise EngineError(
                    ErrorCode.PARSE_ERROR,
                    f"unknown function {name!r}",
                )
            arg = self.expression()
            self.expect(")")
            return Unary(name, arg)
        return self.primary()

    def is_call(self) -> bool:
        name = self.tok.peek()
        return (
            name is not None
            and (name[0].isalpha() or name[0] == "_")
            and self.tok.pos + 1 < len(self.tok.tokens)
            and self.tok.tokens[self.tok.pos + 1] == "("
        )

    def primary(self) -> Node:
        tok = self.tok.next()
        if tok is None:
            raise EngineError(ErrorCode.PARSE_ERROR, "unexpected end of expression")
        if tok == "(":
            inner = self.expression()
            self.expect(")")
            return inner
        if re.fullmatch(
            r"[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?|\.[0-9]+(?:[eE][+-]?[0-9]+)?",
            tok,
        ):
            return Number(float(tok))
        if tok[0].isalpha() or tok[0] == "_":
            return Name(tok)
        raise EngineError(
            ErrorCode.PARSE_ERROR, f"unexpected token {tok!r}"
        )

    def expect(self, expected: str) -> None:
        tok = self.tok.next()
        if tok != expected:
            raise EngineError(
                ErrorCode.PARSE_ERROR,
                f"expected {expected!r}, got {tok!r}",
            )


def _validate_exponents(node: Node) -> None:
    """Exponents must be numeric constant expressions (no named quantities)."""
    if isinstance(node, Number):
        return
    if isinstance(node, Name):
        raise EngineError(
            ErrorCode.PARSE_ERROR, "exponent must be a numeric constant"
        )
    if isinstance(node, Unary):
        if node.op not in ("neg", "pos"):
            raise EngineError(
                ErrorCode.PARSE_ERROR, "exponent must be a numeric constant"
            )
        _validate_exponents(node.operand)
        return
    _validate_exponents(node.left)
    _validate_exponents(node.right)


def parse(expression: str) -> Node:
    if not isinstance(expression, str):
        raise EngineError(ErrorCode.PARSE_ERROR, "expression must be a string")
    node = _Parser(expression).parse()
    _check_exponent_nodes(node)
    return node


def _check_exponent_nodes(node: Node) -> None:
    if isinstance(node, (Number, Name)):
        return
    if isinstance(node, Unary):
        _check_exponent_nodes(node.operand)
        return
    if node.op == "^":
        _validate_exponents(node.right)
    _check_exponent_nodes(node.left)
    _check_exponent_nodes(node.right)
