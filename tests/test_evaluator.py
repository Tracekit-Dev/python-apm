"""
Tests for the TraceKit portable expression evaluator.
Loads shared fixture file (testdata/expression_fixtures.json) and verifies
all 64 test cases against the Python evaluator.
"""

import json
import os
from pathlib import Path

import pytest

from tracekit.evaluator import (
    UnsupportedExpressionError,
    evaluate_condition,
    evaluate_expression,
    evaluate_expressions,
    is_sdk_evaluable,
)

FIXTURES_PATH = Path(__file__).parent.parent / "testdata" / "expression_fixtures.json"


def load_fixtures():
    with open(FIXTURES_PATH) as f:
        data = json.load(f)
    default_vars = data["default_variables"]
    cases = []
    for tc in data["test_cases"]:
        env = tc["variables"] if tc["variables"] is not None else default_vars
        cases.append(
            pytest.param(
                tc["expression"],
                env,
                tc["expected"],
                tc["classify"],
                id=tc["id"],
            )
        )
    return cases


FIXTURE_CASES = load_fixtures()


# ---------------------------------------------------------------------------
# Fixture-based parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("expression,env,expected,classify", FIXTURE_CASES)
def test_fixture_classification(expression, env, expected, classify):
    """is_sdk_evaluable must agree with the fixture's classify field."""
    if classify == "sdk-evaluable":
        assert is_sdk_evaluable(expression) is True, (
            f"Expected sdk-evaluable for: {expression}"
        )
    else:
        assert is_sdk_evaluable(expression) is False, (
            f"Expected server-only for: {expression}"
        )


@pytest.mark.parametrize("expression,env,expected,classify", FIXTURE_CASES)
def test_fixture_evaluation(expression, env, expected, classify):
    """For sdk-evaluable expressions, evaluation must produce the expected result."""
    if classify == "server-only":
        with pytest.raises(UnsupportedExpressionError):
            evaluate_expression(expression, env)
        return

    result = evaluate_expression(expression, env)

    # Normalize: fixture uses null for nil, Python uses None
    if expected is None:
        assert result is None, f"Expected None, got {result!r}"
    elif isinstance(expected, bool):
        assert result is expected, f"Expected {expected}, got {result!r}"
    elif isinstance(expected, int) and not isinstance(expected, bool):
        # Allow int or float match (e.g. 100 == 100.0)
        assert result == expected, f"Expected {expected}, got {result!r}"
    elif isinstance(expected, float):
        assert abs(result - expected) < 1e-9, f"Expected {expected}, got {result!r}"
    elif isinstance(expected, str):
        assert result == expected, f"Expected {expected!r}, got {result!r}"
    else:
        assert result == expected


# ---------------------------------------------------------------------------
# Unit tests for specific behaviors
# ---------------------------------------------------------------------------


class TestIsSDKEvaluable:
    def test_simple_comparison(self):
        assert is_sdk_evaluable("status == 200") is True

    def test_function_call(self):
        assert is_sdk_evaluable("matches(path, '/api')") is False

    def test_regex_operator(self):
        assert is_sdk_evaluable('path =~ "/api/.*"') is False

    def test_bitwise_and(self):
        assert is_sdk_evaluable("flags & 0x01") is False

    def test_logical_and_allowed(self):
        assert is_sdk_evaluable("a == 1 && b == 2") is True

    def test_array_indexing(self):
        assert is_sdk_evaluable("items[0]") is False

    def test_ternary(self):
        assert is_sdk_evaluable('status > 400 ? "error" : "ok"') is False

    def test_range(self):
        assert is_sdk_evaluable("1..10") is False

    def test_template_literal(self):
        assert is_sdk_evaluable("${name}") is False

    def test_compound_assignment(self):
        assert is_sdk_evaluable("count += 1") is False

    def test_bit_shift(self):
        assert is_sdk_evaluable("value << 2") is False


class TestEvaluateCondition:
    def test_empty_returns_true(self):
        assert evaluate_condition("", {}) is True

    def test_true_condition(self):
        assert evaluate_condition("status == 200", {"status": 200}) is True

    def test_false_condition(self):
        assert evaluate_condition("status == 500", {"status": 200}) is False

    def test_unsupported_raises(self):
        with pytest.raises(UnsupportedExpressionError):
            evaluate_condition("matches(path, '/api')", {"path": "/api"})

    def test_nil_access_returns_false(self):
        # Accessing missing property in a comparison returns false
        assert evaluate_condition("user.nonexistent == 42", {"user": {}}) is False

    def test_nil_equals_nil(self):
        assert evaluate_condition("user.nonexistent == nil", {"user": {}}) is True


class TestEvaluateExpression:
    def test_arithmetic(self):
        assert evaluate_expression("status + 100", {"status": 200}) == 300

    def test_string_concat(self):
        result = evaluate_expression(
            'method + " " + path', {"method": "GET", "path": "/api"}
        )
        assert result == "GET /api"

    def test_nil_property(self):
        result = evaluate_expression("user.missing", {"user": {}})
        assert result is None

    def test_deep_nil_property(self):
        result = evaluate_expression("user.settings.theme", {"user": {"settings": None}})
        assert result is None


class TestEvaluateExpressions:
    def test_batch(self):
        env = {"status": 200, "method": "GET"}
        results = evaluate_expressions(["status", "method", "status + 100"], env)
        assert results["status"] == 200
        assert results["method"] == "GET"
        assert results["status + 100"] == 300

    def test_error_returns_none(self):
        results = evaluate_expressions(["matches(x, 'y')"], {"x": "y"})
        assert results["matches(x, 'y')"] is None
