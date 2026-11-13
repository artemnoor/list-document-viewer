import hashlib
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import canonical_json


@dataclass(frozen=True)
class Fact:
    fact_id: str
    document_id: str
    extraction_id: str
    document_type: str
    row_id: str | None
    source_path: str
    role: str
    key: str
    label: str
    value: Any
    normalized_value: Any
    source_value: Any
    status: str
    confidence: float | None
    provenance: dict[str, Any] | None
    currency: str | None
    unit: str | None
    period_start: date | None
    period_end: date | None
    amount_basis: str | None
    economic_measure: str | None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["period_start"] = self.period_start.isoformat() if self.period_start else None
        result["period_end"] = self.period_end.isoformat() if self.period_end else None
        return result


def _as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _period(extraction: dict[str, Any]) -> tuple[date | None, date | None]:
    fields = extraction.get("fields", {})
    for key in ("execution_period", "reporting_period", "period"):
        wrapper = fields.get(key) if isinstance(fields, dict) else None
        value = wrapper.get("value") if isinstance(wrapper, dict) else None
        if isinstance(value, dict):
            start, end = _as_date(value.get("start")), _as_date(value.get("end"))
            if start or end:
                return start, end
    for index, item in enumerate(extraction.get("indicators", []) or []):
        if isinstance(item, dict) and item.get("key") == "reporting_period":
            value = ((item.get("extracted") or {}).get("value"))
            if isinstance(value, dict):
                return _as_date(value.get("start")), _as_date(value.get("end"))
    return None, None


def _row_period(row: dict[str, Any], document_period: tuple[date | None, date | None]) -> tuple[date | None, date | None]:
    """Prefer an operation-level date/period when the Extraction provides one."""
    for key in ("operation_date", "service_date", "operation_period", "service_period", "period"):
        wrapper = row.get(key)
        value = wrapper.get("value") if isinstance(wrapper, dict) else wrapper
        if isinstance(value, dict):
            start, end = _as_date(value.get("start")), _as_date(value.get("end"))
            if start or end:
                return start, end
        parsed = _as_date(value)
        if parsed:
            return parsed, parsed
    return document_period


def _measure_type(key: str, wrapper: dict[str, Any], row_value: Any = None) -> str | None:
    declared = wrapper.get("economic_measure") or wrapper.get("measure_type") or wrapper.get("amount_type")
    allowed = {"planned", "actual", "accrued", "paid"}
    if isinstance(declared, str) and declared in allowed:
        return declared
    normalized_key = key.lower()
    for prefix, measure in (("planned_", "planned"), ("plan_", "planned"), ("actual_", "actual"), ("accrued_", "accrued"), ("paid_", "paid")):
        if normalized_key.startswith(prefix):
            return measure
    if normalized_key in {"planned_amount", "plan_amount", "actual_amount", "accrued_amount", "paid_amount"}:
        return {
            "planned_amount": "planned", "plan_amount": "planned", "actual_amount": "actual",
            "accrued_amount": "accrued", "paid_amount": "paid",
        }[normalized_key]
    if isinstance(row_value, dict):
        row_measure = row_value.get("economic_measure")
        if isinstance(row_measure, str) and row_measure in allowed:
            return row_measure
    return None


def _fact(
    extraction: dict[str, Any], path: str, role: str, key: str, wrapper: Any,
    row_id: str | None, period: tuple[date | None, date | None], unit_override: str | None = None,
    row_value: Any = None,
) -> Fact | None:
    if not isinstance(wrapper, dict) or "value" not in wrapper:
        return None
    value = wrapper.get("value")
    currency = value.get("currency") if isinstance(value, dict) and isinstance(value.get("currency"), str) else None
    amount = value.get("amount") if isinstance(value, dict) and "amount" in value else value
    unit = unit_override if unit_override is not None else wrapper.get("unit")
    if isinstance(unit, dict):
        unit = unit.get("value")
    if unit is not None and not isinstance(unit, str):
        unit = str(unit)
    basis = wrapper.get("amount_basis") or wrapper.get("basis")
    economic_measure = _measure_type(key, wrapper, row_value)
    provenance = wrapper.get("provenance")
    doc_id = extraction["document_id"]
    identity = f"{doc_id}|{path}"
    fact_id = "fact_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return Fact(
        fact_id=fact_id,
        document_id=doc_id,
        extraction_id=extraction["extraction_id"],
        document_type=extraction.get("document_type") or extraction.get("classification", {}).get("type", "unknown"),
        row_id=row_id,
        source_path=path,
        role=role,
        key=key,
        label=str(wrapper.get("label") or key),
        value=amount,
        normalized_value=value,
        source_value=wrapper.get("source_value"),
        status=str(wrapper.get("status") or "missing"),
        confidence=wrapper.get("confidence"),
        provenance=provenance if isinstance(provenance, dict) else None,
        currency=currency,
        unit=unit,
        period_start=period[0],
        period_end=period[1],
        amount_basis=str(basis) if basis is not None else None,
        economic_measure=economic_measure,
    )


def extract_facts(extractions: list[dict[str, Any]]) -> list[Fact]:
    facts: list[Fact] = []
    for extraction in extractions:
        period = _period(extraction)
        for key, wrapper in (extraction.get("fields") or {}).items():
            fact = _fact(extraction, f"#/fields/{key}", "field", key, wrapper, None, period)
            if fact:
                facts.append(fact)
        for index, indicator in enumerate(extraction.get("indicators") or []):
            if not isinstance(indicator, dict):
                continue
            key = str(indicator.get("key") or index)
            wrapper = indicator.get("extracted")
            fact = _fact(extraction, f"#/indicators/{index}/extracted", "indicator", key, wrapper, None, period)
            if fact:
                facts.append(fact)
        # line_items is the canonical row collection in Structured Extraction 1.2.0.
        # tables are retained on input but not flattened again, avoiding duplicate facts.
        for index, row in enumerate(extraction.get("line_items") or []):
            if not isinstance(row, dict):
                continue
            row_id = row.get("row_id")
            row_unit = row.get("unit")
            row_unit = row_unit.get("value") if isinstance(row_unit, dict) else row_unit
            row_unit = str(row_unit) if row_unit is not None else None
            for key, wrapper in row.items():
                if key in {"row_id", "row_status", "source_cells"}:
                    continue
                unit_override = row_unit if key in {"quantity", "plan_quantity", "actual_quantity"} else None
                fact = _fact(extraction, f"#/line_items/{index}/{key}", "line_item", key, wrapper, row_id, _row_period(row, period), unit_override, row)
                if fact:
                    facts.append(fact)
        # Contract schedules and payment schedules are separate from completed operations.
        # They remain candidates for semantic planning and are never implicitly summed.
        for index, row in enumerate(extraction.get("payment_schedule") or []):
            if not isinstance(row, dict):
                continue
            row_id = row.get("row_id")
            for key, wrapper in row.items():
                if key in {"row_id", "row_status", "source_cells"}:
                    continue
                fact = _fact(extraction, f"#/payment_schedule/{index}/{key}", "payment_schedule", key, wrapper, row_id, _row_period(row, period), row_value=row)
                if fact:
                    facts.append(fact)
    # Extraction may expose the same cell as both a field and an indicator. Keep
    # one canonical candidate for identical source locators and values.
    unique: dict[tuple[Any, ...], Fact] = {}
    role_priority = {"indicator": 0, "field": 1, "line_item": 2, "payment_schedule": 3}
    result: list[Fact] = []
    for fact in facts:
        provenance = fact.provenance or {}
        locator = provenance.get("source_ref")
        part_id = provenance.get("source_part_id")
        if locator and part_id:
            identity = (fact.document_id, part_id, locator, canonical_json(fact.normalized_value), fact.status)
            existing = unique.get(identity)
            if existing and role_priority.get(existing.role, 9) <= role_priority.get(fact.role, 9):
                continue
            if existing:
                result.remove(existing)
            unique[identity] = fact
        result.append(fact)
    return result


def numeric_value(fact: Fact) -> Decimal | None:
    value = fact.value
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def fact_input_hash(fact: Fact) -> str:
    return hashlib.sha256(canonical_json(fact.as_dict()).encode("utf-8")).hexdigest()

