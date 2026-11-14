from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from typing import Any

from app.models import VerificationContext


ROUNDING_MODES = {
    "HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
    "DOWN": ROUND_DOWN,
    "UP": ROUND_UP,
}


@dataclass
class ComparisonOutcome:
    comparable: bool
    equal: bool | None
    difference: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    uncertainty_reasons: list[str] = field(default_factory=list)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        raise InvalidOperation
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _number_and_currency(value: Any, fallback_currency: str | None) -> tuple[Decimal, str | None]:
    if isinstance(value, dict):
        currency = value.get("currency", fallback_currency)
        if "amount" not in value:
            raise InvalidOperation
        return _decimal(value["amount"]), str(currency) if currency is not None else None
    return _decimal(value), fallback_currency


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("String values must be strings")
    return " ".join(unicodedata.normalize("NFC", value).split())


def _within_tolerance(delta: Decimal, expected: Decimal, unit: str | None, context: VerificationContext) -> tuple[bool, str, list[str]]:
    policy = context.tolerance
    reasons: list[str] = []
    if policy.rounding_scale is not None:
        quantum = Decimal(1).scaleb(-policy.rounding_scale)
        mode = ROUNDING_MODES[policy.rounding_mode]
        actual_rounded = (expected + delta).quantize(quantum, rounding=mode)
        expected_rounded = expected.quantize(quantum, rounding=mode)
        if actual_rounded == expected_rounded:
            return True, "rounding", reasons
    if policy.absolute is not None:
        if policy.absolute_unit == unit:
            if abs(delta) <= Decimal(policy.absolute):
                return True, "absolute_tolerance", reasons
        else:
            reasons.append("absolute_tolerance_unit_does_not_match_measure")
    if policy.relative is not None and expected != 0:
        if abs(delta / abs(expected)) <= Decimal(policy.relative):
            return True, "relative_tolerance", reasons
    elif policy.relative is not None:
        reasons.append("relative_difference_undefined_for_zero_expected_value")
    return False, "none", reasons


def compare_metric(
    actual: Any,
    expected: Any,
    value_type: str,
    context: VerificationContext,
    actual_currency: str | None = None,
    expected_currency: str | None = None,
    actual_unit: str | None = None,
    expected_unit: str | None = None,
) -> ComparisonOutcome:
    if value_type in {"money", "decimal", "quantity", "integer"}:
        try:
            actual_number, value_currency = _number_and_currency(actual, actual_currency)
            expected_number, expected_value_currency = _number_and_currency(expected, expected_currency)
        except (InvalidOperation, TypeError, ValueError) as exc:
            return ComparisonOutcome(
                comparable=False,
                equal=None,
                issues=[{"code": "invalid_numeric_value", "message": "Actual or expected value is not a finite normalized decimal"}],
            )
        actual_currency = value_currency
        expected_currency = expected_value_currency
        if value_type == "money":
            if not actual_currency or not expected_currency:
                return ComparisonOutcome(
                    comparable=False,
                    equal=None,
                    issues=[{"code": "currency_unknown", "message": "Both financial values require explicit currency codes"}],
                    uncertainty_reasons=["currency_unknown"],
                )
            if actual_currency != expected_currency:
                return ComparisonOutcome(
                    comparable=False,
                    equal=None,
                    issues=[{"code": "currency_mismatch", "message": f"Currency codes differ: {actual_currency} vs {expected_currency}"}],
                )
        if value_type == "quantity":
            if not actual_unit or not expected_unit:
                return ComparisonOutcome(
                    comparable=False,
                    equal=None,
                    issues=[{"code": "unit_unknown", "message": "Both quantity values require explicit units"}],
                    uncertainty_reasons=["unit_unknown"],
                )
            if actual_unit != expected_unit:
                return ComparisonOutcome(
                    comparable=False,
                    equal=None,
                    issues=[{"code": "unit_mismatch", "message": f"Units differ: {actual_unit} vs {expected_unit}"}],
                )
        if value_type == "integer" and (actual_number != actual_number.to_integral_value() or expected_number != expected_number.to_integral_value()):
            return ComparisonOutcome(
                comparable=False,
                equal=None,
                issues=[{"code": "non_integral_value", "message": "An integer indicator contains a fractional value"}],
            )
        delta = actual_number - expected_number
        denominator = abs(expected_number)
        relative = delta / denominator if denominator != 0 else None
        measure = actual_currency if value_type == "money" else actual_unit
        accepted, accepted_by, reasons = _within_tolerance(delta, expected_number, measure, context)
        difference = {
            "absolute": format(delta, "f"),
            "relative": format(relative, "f") if relative is not None else None,
            "formula": "actual - expected",
            "evaluated_actual": format(actual_number, "f"),
            "evaluated_expected": format(expected_number, "f"),
            "accepted_by": accepted_by if accepted else "none",
        }
        if relative is None:
            reasons.append("relative_difference_undefined_for_zero_expected_value")
        if delta != 0 and context.tolerance.rounding_scale is None and context.tolerance.absolute is None and context.tolerance.relative is None:
            reasons.append("no_rounding_rule_or_tolerance_was_supplied")
        return ComparisonOutcome(comparable=True, equal=(delta == 0 or accepted), difference=difference, uncertainty_reasons=reasons)

    if value_type == "period":
        if not isinstance(actual, dict) or not isinstance(expected, dict) or not {"start", "end"} <= actual.keys() or not {"start", "end"} <= expected.keys():
            return ComparisonOutcome(comparable=False, equal=None, issues=[{"code": "invalid_period", "message": "Period values must contain start and end"}])
        equal = actual["start"] == expected["start"] and actual["end"] == expected["end"]
        return ComparisonOutcome(comparable=True, equal=equal, difference={"formula": "actual period equals expected period", "accepted_by": "exact" if equal else "none"})

    if value_type == "boolean":
        if not isinstance(actual, bool) or not isinstance(expected, bool):
            return ComparisonOutcome(comparable=False, equal=None, issues=[{"code": "invalid_boolean", "message": "Boolean comparison requires boolean values"}])
        return ComparisonOutcome(comparable=True, equal=actual is expected, difference={"formula": "actual equals expected", "accepted_by": "exact" if actual is expected else "none"})

    if value_type in {"string", "date"}:
        try:
            left = _normalized_text(actual)
            right = _normalized_text(expected)
        except TypeError:
            return ComparisonOutcome(comparable=False, equal=None, issues=[{"code": "invalid_text_value", "message": "Text comparison requires string values"}])
        equal = left == right
        return ComparisonOutcome(comparable=True, equal=equal, difference={"formula": "normalized actual equals normalized expected", "evaluated_actual": left, "evaluated_expected": right, "accepted_by": "exact" if equal else "none"})

    return ComparisonOutcome(comparable=False, equal=None, issues=[{"code": "unsupported_value_type", "message": f"Unsupported value_type {value_type!r}"}])
