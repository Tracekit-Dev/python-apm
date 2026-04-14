"""
TraceKit Portable Expression Evaluator

Evaluates the portable subset of TraceKit expressions locally without
server round-trips. Uses a custom recursive-descent parser -- never
eval()/exec().

Spec reference: docs/EXPRESSION_SPEC.md
Go reference: tracekit/go-sdk/tracekit/evaluator.go
"""

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "UnsupportedExpressionError",
    "is_sdk_evaluable",
    "evaluate_condition",
    "evaluate_expression",
    "evaluate_expressions",
]

# Sentinel for missing / nil values
_NIL = object()


class UnsupportedExpressionError(Exception):
    """Expression requires server-side evaluation."""
    pass


# ---------------------------------------------------------------------------
# Classification: is_sdk_evaluable
# ---------------------------------------------------------------------------

# Patterns that indicate server-only expressions
_FUNC_CALL_RE = re.compile(r"\b[a-zA-Z_]\w*\s*\(")
_MATCHES_RE = re.compile(r"\bmatches\b")
_REGEX_OP_RE = re.compile(r"=~")
_ARRAY_INDEX_RE = re.compile(r"\[\d")
_COMPOUND_ASSIGN_RE = re.compile(r"[+\-*/]=")


def is_sdk_evaluable(expression: str) -> bool:
    """Return True if the expression can be evaluated locally by the SDK."""
    if _FUNC_CALL_RE.search(expression):
        return False
    if _MATCHES_RE.search(expression):
        return False
    if _REGEX_OP_RE.search(expression):
        return False

    # Bitwise NOT ~ (but not =~ which is already rejected)
    for i, ch in enumerate(expression):
        if ch == "~" and (i == 0 or expression[i - 1] != "="):
            return False

    # Bitwise AND: single & not part of &&
    i = 0
    while i < len(expression):
        if expression[i] == "&":
            if i + 1 < len(expression) and expression[i + 1] == "&":
                i += 2
                continue
            return False
        i += 1

    # Bitwise OR: single | not part of ||
    i = 0
    while i < len(expression):
        if expression[i] == "|":
            if i + 1 < len(expression) and expression[i + 1] == "|":
                i += 2
                continue
            return False
        i += 1

    if "<<" in expression or ">>" in expression:
        return False
    if "${" in expression:
        return False
    if ".." in expression:
        return False
    if "?" in expression:
        return False
    if _ARRAY_INDEX_RE.search(expression):
        return False
    if _COMPOUND_ASSIGN_RE.search(expression):
        return False

    return True


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class _TokenType:
    NUMBER = "NUMBER"
    STRING = "STRING"
    IDENT = "IDENT"
    BOOL = "BOOL"
    NIL = "NIL"
    OP = "OP"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    DOT = "DOT"
    EOF = "EOF"


class _Token:
    __slots__ = ("type", "value")

    def __init__(self, type_: str, value: Any):
        self.type = type_
        self.value = value

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


# Regex for tokenizing
_TOKEN_RE = re.compile(
    r"""
    (?P<whitespace>\s+)                          |
    (?P<float>\d+\.\d+)                          |
    (?P<int>-?\d+)                               |
    (?P<dstring>"(?:[^"\\]|\\.)*")               |
    (?P<sstring>'(?:[^'\\]|\\.)*')               |
    (?P<op>&&|\|\||[!<>=]=|[<>!+\-*/])           |
    (?P<in>\bin\b)                               |
    (?P<ident>[a-zA-Z_][a-zA-Z0-9_]*)           |
    (?P<lparen>\()                               |
    (?P<rparen>\))                               |
    (?P<lbracket>\[)                             |
    (?P<rbracket>\])                             |
    (?P<dot>\.)
    """,
    re.VERBOSE,
)


def _tokenize(expression: str) -> List[_Token]:
    tokens = []
    pos = 0
    while pos < len(expression):
        m = _TOKEN_RE.match(expression, pos)
        if m is None:
            raise ValueError(f"Unexpected character at position {pos}: {expression[pos]!r}")
        pos = m.end()

        if m.lastgroup == "whitespace":
            continue
        elif m.lastgroup == "float":
            tokens.append(_Token(_TokenType.NUMBER, float(m.group())))
        elif m.lastgroup == "int":
            # Handle negative numbers: if the last token is a number/ident/rparen,
            # this minus is a binary operator, not a negative sign
            val = m.group()
            if val.startswith("-") and tokens and tokens[-1].type in (
                _TokenType.NUMBER, _TokenType.IDENT, _TokenType.RPAREN,
                _TokenType.RBRACKET, _TokenType.BOOL, _TokenType.NIL,
            ):
                # Split into minus operator and positive number
                tokens.append(_Token(_TokenType.OP, "-"))
                tokens.append(_Token(_TokenType.NUMBER, int(val[1:])))
            else:
                tokens.append(_Token(_TokenType.NUMBER, int(val)))
        elif m.lastgroup in ("dstring", "sstring"):
            # Strip quotes and unescape
            raw = m.group()[1:-1]
            raw = raw.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
            tokens.append(_Token(_TokenType.STRING, raw))
        elif m.lastgroup == "op":
            tokens.append(_Token(_TokenType.OP, m.group()))
        elif m.lastgroup == "in":
            tokens.append(_Token(_TokenType.OP, "in"))
        elif m.lastgroup == "ident":
            word = m.group()
            if word in ("true", "false"):
                tokens.append(_Token(_TokenType.BOOL, word == "true"))
            elif word in ("nil", "null", "None"):
                tokens.append(_Token(_TokenType.NIL, None))
            else:
                tokens.append(_Token(_TokenType.IDENT, word))
        elif m.lastgroup == "lparen":
            tokens.append(_Token(_TokenType.LPAREN, "("))
        elif m.lastgroup == "rparen":
            tokens.append(_Token(_TokenType.RPAREN, ")"))
        elif m.lastgroup == "lbracket":
            tokens.append(_Token(_TokenType.LBRACKET, "["))
        elif m.lastgroup == "rbracket":
            tokens.append(_Token(_TokenType.RBRACKET, "]"))
        elif m.lastgroup == "dot":
            tokens.append(_Token(_TokenType.DOT, "."))

    tokens.append(_Token(_TokenType.EOF, None))
    return tokens


# ---------------------------------------------------------------------------
# Recursive-descent parser + evaluator
# ---------------------------------------------------------------------------

class _Parser:
    """
    Grammar (precedence low to high):
        or_expr     : and_expr ( '||' and_expr )*
        and_expr    : not_expr ( '&&' not_expr )*
        not_expr    : '!' not_expr | equality
        equality    : comparison ( ('==' | '!=') comparison )*
        comparison  : addition ( ('<' | '>' | '<=' | '>=') addition )*
        addition    : multiply ( ('+' | '-') multiply )*
        multiply    : unary ( ('*' | '/') unary )*
        unary       : '-' unary | membership
        membership  : primary ( 'in' primary )?
        primary     : NUMBER | STRING | BOOL | NIL | IDENT access* | '(' or_expr ')'
        access      : '.' IDENT | '[' or_expr ']'
    """

    def __init__(self, tokens: List[_Token], env: Dict[str, Any]):
        self.tokens = tokens
        self.pos = 0
        self.env = env

    def peek(self) -> _Token:
        return self.tokens[self.pos]

    def advance(self) -> _Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, type_: str) -> _Token:
        tok = self.advance()
        if tok.type != type_:
            raise ValueError(f"Expected {type_}, got {tok}")
        return tok

    def parse(self) -> Any:
        result = self.or_expr()
        if self.peek().type != _TokenType.EOF:
            raise ValueError(f"Unexpected token: {self.peek()}")
        return result

    def or_expr(self) -> Any:
        left = self.and_expr()
        while self.peek().type == _TokenType.OP and self.peek().value == "||":
            self.advance()
            right = self.and_expr()
            left = left or right
        return left

    def and_expr(self) -> Any:
        left = self.not_expr()
        while self.peek().type == _TokenType.OP and self.peek().value == "&&":
            self.advance()
            right = self.not_expr()
            left = left and right
        return left

    def not_expr(self) -> Any:
        if self.peek().type == _TokenType.OP and self.peek().value == "!":
            self.advance()
            val = self.not_expr()
            return not val
        return self.equality()

    def equality(self) -> Any:
        left = self.comparison()
        while self.peek().type == _TokenType.OP and self.peek().value in ("==", "!="):
            op = self.advance().value
            right = self.comparison()
            left = _safe_eq(left, right, op)
        return left

    def comparison(self) -> Any:
        left = self.addition()
        while self.peek().type == _TokenType.OP and self.peek().value in ("<", ">", "<=", ">="):
            op = self.advance().value
            right = self.addition()
            left = _safe_compare(left, right, op)
        return left

    def addition(self) -> Any:
        left = self.multiply()
        while self.peek().type == _TokenType.OP and self.peek().value in ("+", "-"):
            op = self.advance().value
            right = self.multiply()
            if op == "+":
                if isinstance(left, str) and isinstance(right, str):
                    left = left + right
                elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    left = left + right
                else:
                    left = None
            else:
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    left = left - right
                else:
                    left = None
        return left

    def multiply(self) -> Any:
        left = self.unary()
        while self.peek().type == _TokenType.OP and self.peek().value in ("*", "/"):
            op = self.advance().value
            right = self.unary()
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if op == "*":
                    left = left * right
                else:
                    if right == 0:
                        left = None
                    else:
                        result = left / right
                        # Keep as int if result is whole
                        if isinstance(left, int) and isinstance(right, int) and result == int(result):
                            left = int(result)
                        else:
                            left = result
            else:
                left = None
        return left

    def unary(self) -> Any:
        if self.peek().type == _TokenType.OP and self.peek().value == "-":
            self.advance()
            val = self.unary()
            if isinstance(val, (int, float)):
                return -val
            return None
        return self.membership()

    def membership(self) -> Any:
        left = self.primary()
        if self.peek().type == _TokenType.OP and self.peek().value == "in":
            self.advance()
            right = self.primary()
            if isinstance(right, dict) and isinstance(left, str):
                return left in right
            return False
        return left

    def primary(self) -> Any:
        tok = self.peek()

        if tok.type == _TokenType.NUMBER:
            self.advance()
            return tok.value

        if tok.type == _TokenType.STRING:
            self.advance()
            return tok.value

        if tok.type == _TokenType.BOOL:
            self.advance()
            return tok.value

        if tok.type == _TokenType.NIL:
            self.advance()
            return None

        if tok.type == _TokenType.LPAREN:
            self.advance()
            val = self.or_expr()
            self.expect(_TokenType.RPAREN)
            return val

        if tok.type == _TokenType.IDENT:
            self.advance()
            # Resolve from environment
            val = self.env.get(tok.value, None)
            # Handle property access chains
            val = self._access_chain(val)
            return val

        raise ValueError(f"Unexpected token: {tok}")

    def _access_chain(self, val: Any) -> Any:
        """Handle .prop and ["key"] access with null safety."""
        while True:
            if self.peek().type == _TokenType.DOT:
                self.advance()
                prop_tok = self.expect(_TokenType.IDENT)
                val = _safe_get(val, prop_tok.value)
            elif self.peek().type == _TokenType.LBRACKET:
                self.advance()
                key = self.or_expr()
                self.expect(_TokenType.RBRACKET)
                val = _safe_get(val, key)
            else:
                break
        return val


# ---------------------------------------------------------------------------
# Safe access helpers
# ---------------------------------------------------------------------------

def _safe_get(obj: Any, key: Any) -> Any:
    """Null-safe property/key access. Returns None on missing or nil."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key, None)
    return None


def _safe_eq(left: Any, right: Any, op: str) -> bool:
    """Equality with int-to-float promotion."""
    # Promote int to float for comparison
    if isinstance(left, int) and not isinstance(left, bool) and isinstance(right, float):
        left = float(left)
    elif isinstance(right, int) and not isinstance(right, bool) and isinstance(left, float):
        right = float(right)

    if op == "==":
        # Strict type check: don't equate different types (except int/float)
        if type(left) is not type(right) and not (
            isinstance(left, (int, float)) and isinstance(right, (int, float))
            and not isinstance(left, bool) and not isinstance(right, bool)
        ):
            # None == None is allowed
            if left is None and right is None:
                return True
            return False
        return left == right
    else:  # !=
        if type(left) is not type(right) and not (
            isinstance(left, (int, float)) and isinstance(right, (int, float))
            and not isinstance(left, bool) and not isinstance(right, bool)
        ):
            if left is None and right is None:
                return False
            return True
        return left != right


def _safe_compare(left: Any, right: Any, op: str) -> bool:
    """Comparison with type safety. Incompatible types return False."""
    if left is None or right is None:
        return False

    # Int-to-float promotion
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        if op == "<":
            return left < right
        elif op == ">":
            return left > right
        elif op == "<=":
            return left <= right
        else:  # >=
            return left >= right

    if isinstance(left, str) and isinstance(right, str):
        if op == "<":
            return left < right
        elif op == ">":
            return left > right
        elif op == "<=":
            return left <= right
        else:
            return left >= right

    # Incompatible types
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_expression(expression: str, env: Dict[str, Any]) -> Any:
    """
    Evaluate an expression and return the raw result.
    Raises UnsupportedExpressionError for server-only expressions.
    """
    if not expression:
        return None

    if not is_sdk_evaluable(expression):
        raise UnsupportedExpressionError(
            f"Expression requires server-side evaluation: {expression}"
        )

    tokens = _tokenize(expression)
    parser = _Parser(tokens, env)
    return parser.parse()


def evaluate_condition(expression: str, env: Dict[str, Any]) -> bool:
    """
    Evaluate an expression as a boolean condition.
    Empty expression returns True (no condition = always fire).
    Raises UnsupportedExpressionError for server-only expressions.
    """
    if not expression:
        return True

    result = evaluate_expression(expression, env)

    if isinstance(result, bool):
        return result
    if result is None:
        return False
    raise ValueError(f"Condition must evaluate to bool, got {type(result).__name__}")


def evaluate_expressions(
    expressions: List[str], env: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evaluate multiple expressions. Results keyed by expression string.
    On error, None is stored for that expression.
    """
    results = {}
    for expr in expressions:
        try:
            results[expr] = evaluate_expression(expr, env)
        except Exception:
            results[expr] = None
    return results
