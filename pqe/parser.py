"""Tokenizer and recursive-descent parser for physical-quantity expressions.

Grammar::

    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := unary ('^' signed_int)?
    unary  := ('+' | '-') unary | primary
    primary:= number | constant | NAME ('(' expr ')')? | '(' expr ')'

Names match ``[A-Za-z_][A-Za-z0-9_]*``. Numbers are finite decimal literals
(integer, fractional or exponent form); ``inf`` and ``NaN`` are rejected.
``^`` accepts only integer exponents so dimensions stay well-defined.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ErrorCode, EngineError


@dataclass(frozen=True)
class Node:
    pass


@dataclass(frozen=True)
class Number(Node):
    text: str


@dataclass(frozen=True)
class Name(Node):
    name: str


@dataclass(frozen=True)
class Unary(Node):
    op: str
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class FuncCall(Node):
    name: str
    arg: Node


@dataclass(frozen=True)
class _Token:
    kind: str          # NUMBER, NAME, OP, LPAREN, RPAREN, COMMA, END
    text: str
    pos: int


class _Tokenizer:
    _OPS = set("+-*/^()")

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.n = len(text)

    def tokenize(self) -> list[_Token]:
        tokens: list[_Token] = []
        while self.pos < self.n:
            ch = self.text[self.pos]
            if ch in " \t\r\n":
                self.pos += 1
                continue
            if ch.isdigit() or (ch == "." and self.pos + 1 < self.n
                                and self.text[self.pos + 1].isdigit()):
                tokens.append(self._read_number())
                continue
            if ch.isalpha() or ch == "_":
                tokens.append(self._read_name())
                continue
            if ch in self._OPS:
                kind = "LPAREN" if ch == "(" else (
                    "RPAREN" if ch == ")" else "OP")
                tokens.append(_Token(kind, ch, self.pos))
                self.pos += 1
                continue
            raise EngineError(
                ErrorCode.PARSE_ERROR,
                f"unexpected character {ch!r} at position {self.pos}",
            )
        tokens.append(_Token("END", "", self.n))
        return tokens

    def _read_number(self) -> _Token:
        start = self.pos
        saw_digit = False
        while self.pos < self.n and self.text[self.pos].isdigit():
            saw_digit = True
            self.pos += 1
        if self.pos < self.n and self.text[self.pos] == ".":
            self.pos += 1
            while self.pos < self.n and self.text[self.pos].isdigit():
                saw_digit = True
                self.pos += 1
        if self.pos < self.n and self.text[self.pos] in "eE":
            save = self.pos
            self.pos += 1
            if self.pos < self.n and self.text[self.pos] in "+-":
                self.pos += 1
            exp_digits = 0
            while self.pos < self.n and self.text[self.pos].isdigit():
                exp_digits += 1
                self.pos += 1
            if exp_digits == 0:
                self.pos = save  # not an exponent; leave 'e' for name scan
        if not saw_digit:
            raise EngineError(
                ErrorCode.PARSE_ERROR,
                f"malformed number at position {start}")
        return _Token("NUMBER", self.text[start:self.pos], start)

    def _read_name(self) -> _Token:
        start = self.pos
        while self.pos < self.n and (
                self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        return _Token("NAME", self.text[start:self.pos], start)


class _Parser:
    def __init__(self, tokens: list[_Token], text: str) -> None:
        self.tokens = tokens
        self.text = text
        self.i = 0

    def peek(self) -> _Token:
        return self.tokens[self.i]

    def take(self) -> _Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind: str, text: str | None = None) -> _Token:
        tok = self.peek()
        if tok.kind != kind or (text is not None and tok.text != text):
            want = text if text is not None else kind
            raise EngineError(
                ErrorCode.PARSE_ERROR,
                f"expected {want!r} at position {tok.pos} in {self.text!r}")
        return self.take()

    def parse(self) -> Node:
        node = self.parse_expr()
        if self.peek().kind != "END":
            tok = self.peek()
            raise EngineError(
                ErrorCode.PARSE_ERROR,
                f"unexpected token {tok.text!r} at position {tok.pos}")
        return node

    def parse_expr(self) -> Node:
        node = self.parse_term()
        while self.peek().kind == "OP" and self.peek().text in "+-":
            op = self.take().text
            right = self.parse_term()
            node = Binary(op, node, right)
        return node

    def parse_term(self) -> Node:
        node = self.parse_factor()
        while self.peek().kind == "OP" and self.peek().text in "*/":
            op = self.take().text
            right = self.parse_factor()
            node = Binary(op, node, right)
        return node

    def parse_factor(self) -> Node:
        # '^' binds tighter than '*'/'/' and is right associative.
        node = self.parse_unary()
        if self.peek().kind == "OP" and self.peek().text == "^":
            caret = self.take()
            right = self.parse_factor()
            exponent_text = self._exponent_text(right, caret.pos)
            return Binary("^", node, Number(exponent_text))
        return node

    def _exponent_text(self, node: Node, caret_pos: int) -> str:
        # Accept a signed integer literal or a tower of integer literal
        # powers (all statically evaluable), e.g. 2^-3, 2^3^2.
        value = self._static_int(node, caret_pos)
        return str(value)

    def _static_int(self, node: Node, caret_pos: int) -> int:
        if isinstance(node, Number) and _is_integer_text(node.text):
            return int(node.text)
        if isinstance(node, Unary) and node.op in "+-":
            inner = self._static_int(node.operand, caret_pos)
            return -inner if node.op == "-" else inner
        if isinstance(node, Binary) and node.op == "^":
            base = self._static_int(node.left, caret_pos)
            exp = self._static_int(node.right, caret_pos)
            return base ** exp
        raise EngineError(
            ErrorCode.PARSE_ERROR,
            f"exponent must be an integer at position {caret_pos}")

    def parse_unary(self) -> Node:
        tok = self.peek()
        if tok.kind == "OP" and tok.text in "+-":
            self.take()
            return Unary(tok.text, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Node:
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.take()
            return Number(tok.text)
        if tok.kind == "LPAREN":
            self.take()
            inner = self.parse_expr()
            self.expect("RPAREN", ")")
            return inner
        if tok.kind == "NAME":
            self.take()
            if self.peek().kind == "LPAREN":
                self.take()
                arg = self.parse_expr()
                self.expect("RPAREN", ")")
                return FuncCall(tok.text, arg)
            return Name(tok.text)
        raise EngineError(
            ErrorCode.PARSE_ERROR,
            f"unexpected token {tok.text!r} at position {tok.pos}")


def _is_integer_text(text: str) -> bool:
    body = text[1:] if text[:1] in "+-" else text
    return body.isdigit()


def parse(expression: str) -> Node:
    """Parse *expression*; raise EngineError(PARSE_ERROR) on syntax errors."""
    if not isinstance(expression, str):
        raise EngineError(
            ErrorCode.PARSE_ERROR, "expression must be a string")
    if not expression.strip():
        raise EngineError(
            ErrorCode.PARSE_ERROR, "expression is empty")
    tokens = _Tokenizer(expression).tokenize()
    return _Parser(tokens, expression).parse()
