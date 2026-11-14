from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any
from urllib.parse import unquote


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _fact_period(extraction: dict[str, Any]) -> tuple[str | None, str | None]:
    fields = extraction.get("fields", {})
    for key in ("execution_period", "reporting_period", "period"):
        wrapper = fields.get(key) if isinstance(fields, dict) else None
        value = wrapper.get("value") if isinstance(wrapper, dict) else None
        if isinstance(value, dict):
            start, end = _date(value.get("start")), _date(value.get("end"))
            if start or end:
                return start, end
    for indicator in extraction.get("indicators", []) or []:
        if isinstance(indicator, dict) and indicator.get("key") == "reporting_period":
            value = (indicator.get("extracted") or {}).get("value")
            if isinstance(value, dict):
                return _date(value.get("start")), _date(value.get("end"))
    return None, None


def _pointer_value(extraction: dict[str, Any], fragment: str) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(fragment, str) or not fragment.startswith("#/"):
        return None
    pointer = unquote(fragment[1:])
    parts = [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]
    current: Any = extraction
    for token in parts:
        if isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            return None
    if not isinstance(current, dict) or "value" not in current:
        return None
    return pointer, current


def _expected_fact(extraction: dict[str, Any], source_path: str) -> dict[str, Any] | None:
    resolved = _pointer_value(extraction, source_path)
    if resolved is None:
        return None
    pointer, wrapper = resolved
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.lstrip("/").split("/")]
    if len(parts) < 2:
        return None
    row_id = None
    row_value = None
    role = parts[0]
    key = parts[-1]
    if role == "fields":
        role, key = "field", parts[1]
    elif role == "indicators" and len(parts) >= 3:
        role = "indicator"
        indicator = extraction.get("indicators", [])[int(parts[1])]
        key = str(indicator.get("key") or parts[1])
    elif role in {"line_items", "payment_schedule"} and len(parts) >= 3:
        row_value = extraction.get(role, [])[int(parts[1])]
        row_id = row_value.get("row_id") if isinstance(row_value, dict) else None
        role = "line_item" if parts[0] == "line_items" else "payment_schedule"
        key = parts[2]
    else:
        return None

    value = wrapper.get("value")
    currency = value.get("currency") if isinstance(value, dict) and isinstance(value.get("currency"), str) else None
    numeric_value = value.get("amount") if isinstance(value, dict) and "amount" in value else value
    unit = wrapper.get("unit")
    if isinstance(unit, dict):
        unit = unit.get("value")
    if unit is not None and not isinstance(unit, str):
        unit = str(unit)
    if role == "line_item" and key in {"quantity", "plan_quantity", "actual_quantity"} and isinstance(row_value, dict):
        unit = row_value.get("unit", unit)
        if isinstance(unit, dict):
            unit = unit.get("value")
        if unit is not None and not isinstance(unit, str):
            unit = str(unit)
    declared = wrapper.get("economic_measure") or wrapper.get("measure_type") or wrapper.get("amount_type")
    measure = declared if declared in {"planned", "actual", "accrued", "paid"} else None
    if measure is None:
        for prefix, candidate in (("planned_", "planned"), ("plan_", "planned"), ("actual_", "actual"), ("accrued_", "accrued"), ("paid_", "paid")):
            if key.lower().startswith(prefix):
                measure = candidate
                break
    if measure is None and isinstance(row_value, dict) and row_value.get("economic_measure") in {"planned", "actual", "accrued", "paid"}:
        measure = row_value["economic_measure"]
    period_start, period_end = _fact_period(extraction)
    if isinstance(row_value, dict):
        for period_key in ("operation_date", "service_date", "operation_period", "service_period", "period"):
            raw = row_value.get(period_key)
            raw = raw.get("value") if isinstance(raw, dict) else raw
            if isinstance(raw, dict):
                start, end = _date(raw.get("start")), _date(raw.get("end"))
                if start or end:
                    period_start, period_end = start, end
                    break
            parsed = _date(raw)
            if parsed:
                period_start = period_end = parsed
                break
    fact_id = "fact_" + hashlib.sha256(f"{extraction['document_id']}|{source_path}".encode("utf-8")).hexdigest()[:20]
    return {
        "fact_id": fact_id,
        "document_id": extraction["document_id"],
        "extraction_id": extraction["extraction_id"],
        "document_type": extraction.get("document_type") or (extraction.get("classification") or {}).get("type", "unknown"),
        "row_id": row_id,
        "source_path": source_path,
        "role": role,
        "key": key,
        "label": str(wrapper.get("label") or key),
        "value": numeric_value,
        "normalized_value": value,
        "source_value": wrapper.get("source_value"),
        "status": str(wrapper.get("status") or "missing"),
        "confidence": wrapper.get("confidence"),
        "provenance": wrapper.get("provenance") if isinstance(wrapper.get("provenance"), dict) else None,
        "currency": currency,
        "unit": unit,
        "period_start": period_start,
        "period_end": period_end,
        "amount_basis": str(wrapper.get("amount_basis") or wrapper.get("basis")) if wrapper.get("amount_basis") or wrapper.get("basis") is not None else None,
        "economic_measure": measure,
    }


def native_run_diagnostics(result: dict[str, Any], extractions: dict[str, dict[str, Any]], linking: dict[str, Any] | None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    snapshot = result.get("input_snapshot") or {}
    records = snapshot.get("extraction_results") or []
    seen: set[str] = set()
    for index, record in enumerate(records):
        document_id = record.get("document_id")
        if document_id in seen:
            issues.append({"code": "snapshot_document_duplicate", "message": "Reconciliation input snapshot lists a document more than once"})
            continue
        seen.add(document_id)
        extraction = extractions.get(document_id)
        if extraction is None:
            issues.append({"code": "supporting_extraction_missing", "message": "A document named by the Reconciliation snapshot was not supplied"})
            continue
        if record.get("extraction_id") != extraction.get("extraction_id"):
            issues.append({"code": "extraction_id_mismatch", "message": "Reconciliation snapshot references a different Extraction ID"})
        if record.get("schema_version") != extraction.get("schema_version") or record.get("version") != extraction.get("version"):
            issues.append({"code": "extraction_version_mismatch", "message": "Reconciliation snapshot references a different Extraction version"})
        expected_hash = record.get("sha256")
        actual_hash = sha256_json(extraction)
        if not expected_hash:
            issues.append({"code": "extraction_hash_missing", "message": "Reconciliation snapshot does not bind an Extraction to a hash"})
        elif expected_hash != actual_hash:
            issues.append({"code": "extraction_hash_mismatch", "message": "Reconciliation input hash differs from the supplied Extraction"})
    if not records:
        issues.append({"code": "snapshot_extractions_missing", "message": "Reconciliation input snapshot has no Extraction records"})
    linking_run_id = snapshot.get("linking_run_id")
    if linking_run_id and linking is None:
        issues.append({"code": "linking_result_missing", "message": "Reconciliation used a Linking run that was not supplied"})
    elif linking is not None:
        if linking_run_id and linking_run_id != linking.get("linking_run_id"):
            issues.append({"code": "linking_run_id_mismatch", "message": "Reconciliation snapshot references a different Linking run"})
        if snapshot.get("linking_contract_version") != linking.get("contract_version"):
            issues.append({"code": "linking_version_mismatch", "message": "Reconciliation snapshot references a different Linking contract version"})
        if snapshot.get("linking_sha256") != sha256_json(linking):
            issues.append({"code": "linking_hash_mismatch", "message": "Reconciliation input hash differs from the supplied Linking result"})
    return issues


def native_calculation_diagnostics(calculation: dict[str, Any], result: dict[str, Any], extractions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add(code: str, message: str, *, invalid: bool = False) -> None:
        issues.append({"code": code, "message": message, "proof_invalid": invalid})

    snapshot_hash = (result.get("input_snapshot") or {}).get("snapshot_sha256")
    provenance = calculation.get("provenance") or {}
    if not snapshot_hash or provenance.get("input_snapshot_sha256") != snapshot_hash:
        add("calculation_snapshot_hash_mismatch", "Calculation provenance is not bound to the declared input snapshot", invalid=True)
    origin = ((calculation.get("target") or {}).get("kfz_origin") or {})
    snapshot_documents = {
        item.get("document_id") for item in (result.get("input_snapshot") or {}).get("extraction_results", [])
        if isinstance(item, dict)
    }
    target_extraction = extractions.get(origin.get("document_id"))
    if origin.get("document_id") not in snapshot_documents:
        add("target_outside_snapshot", "Calculation target is outside the declared Reconciliation input snapshot", invalid=True)
    if target_extraction is None or target_extraction.get("extraction_id") != origin.get("extraction_id"):
        add("target_extraction_unresolved", "Calculation target does not resolve to the supplied KFZ Extraction", invalid=True)
    elif _pointer_value(target_extraction, origin.get("source_path")) is None:
        add("target_pointer_unresolved", "Calculation target source path does not resolve in the KFZ Extraction", invalid=True)
    elif (target_fact := _expected_fact(target_extraction, origin.get("source_path", ""))) is None or target_fact.get("fact_id") != origin.get("fact_id") or target_fact.get("row_id") != origin.get("row_id"):
        add("target_fact_identity_mismatch", "Calculation target fact ID or row ID differs from its Extraction source", invalid=True)
    elif origin.get("source_ref") and origin.get("source_ref") != (target_fact.get("provenance") or {}).get("source_ref"):
        add("target_source_locator_mismatch", "Calculation target source locator differs from Extraction provenance", invalid=True)
    if calculation.get("status") != "calculated":
        add("calculation_not_complete", "Reconciliation did not declare a complete calculation")
        return issues
    plan = calculation.get("calculation_plan")
    if not isinstance(plan, dict):
        add("calculation_plan_missing", "No formal calculation plan was supplied")
        return issues
    included = {entry.get("fact_id") for entry in plan.get("included", []) if isinstance(entry, dict)}
    used_records = calculation.get("used_sources", [])
    sources: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for source in used_records:
        fact_id = source.get("fact_id")
        if not isinstance(fact_id, str) or fact_id in sources:
            add("calculation_source_id_duplicate", "Calculation used source fact IDs must be unique", invalid=True)
            continue
        if source.get("used_in_result") is not True:
            add("calculation_source_not_used", "A listed used source is not marked as consumed by the Reconciliation result", invalid=True)
        extraction = extractions.get(source.get("document_id"))
        if source.get("document_id") not in snapshot_documents:
            add("calculation_source_outside_snapshot", "A used fact is outside the declared Reconciliation input snapshot", invalid=True)
        if extraction is None or source.get("extraction_id") != extraction.get("extraction_id"):
            add("calculation_source_extraction_mismatch", "A used fact does not resolve to its supplied Extraction version", invalid=True)
            continue
        fact = _expected_fact(extraction, source.get("source_path", ""))
        if fact is None:
            add("calculation_source_pointer_unresolved", "A used fact source path does not resolve", invalid=True)
            continue
        if fact["fact_id"] != fact_id:
            add("calculation_fact_id_mismatch", "A used fact ID does not match its document and JSON Pointer", invalid=True)
        if source.get("input_hash") != sha256_json(fact):
            add("calculation_fact_hash_mismatch", "A used fact hash differs from the supplied Extraction value", invalid=True)
        for key, fact_key in (("value", "normalized_value"), ("numeric_value", "value"), ("source_value", "source_value"), ("status", "status"), ("confidence", "confidence"), ("provenance", "provenance"), ("currency", "currency"), ("unit", "unit"), ("row_id", "row_id"), ("role", "role"), ("key", "key"), ("economic_measure", "economic_measure")):
            if source.get(key) != fact[fact_key]:
                add("calculation_fact_value_mismatch", "A used fact does not match the Extraction wrapper", invalid=True)
                break
        sources[fact_id] = (source, fact)
    if included != set(sources):
        add("calculation_source_coverage_mismatch", "Formal plan inputs and used source facts do not match", invalid=True)
    if set(provenance.get("used_fact_ids", [])) != set(sources):
        add("calculation_provenance_source_mismatch", "Calculation provenance source IDs differ from used source records", invalid=True)
    excluded = {entry.get("fact_id") for entry in plan.get("excluded", []) if isinstance(entry, dict)}
    if included & excluded:
        add("excluded_source_used", "A fact is both included and excluded", invalid=True)
    if plan.get("unprocessed_fact_ids"):
        add("calculation_unprocessed_facts", "Some candidate facts were not assessed by the calculation plan")
    if not excluded.issubset(set(provenance.get("excluded_fact_ids", []))):
        add("calculation_provenance_excluded_mismatch", "Calculation provenance excluded IDs differ from the formal plan", invalid=True)
    target = calculation.get("target") or {}
    if plan.get("target_id") != target.get("target_id"):
        add("calculation_target_id_mismatch", "Calculation plan target ID differs from the declared target", invalid=True)
    for field in ("currency", "unit", "amount_basis"):
        target_value = target.get(field)
        calculation_value = calculation.get(field)
        plan_value = plan.get(field)
        if target_value is not None and calculation_value != target_value or plan_value is not None and calculation_value != plan_value:
            add("calculation_measure_metadata_mismatch", "Calculation target, plan, and result measure metadata disagree", invalid=True)

    steps = plan.get("steps") or []
    trace = calculation.get("steps") or []
    if not steps:
        add("calculation_steps_missing", "Formal calculation plan has no operations")
        return issues
    if len(trace) != len(steps):
        add("calculation_trace_length_mismatch", "Recorded operation trace does not cover the complete plan", invalid=True)
    values: dict[str, Decimal] = {}
    expressions: dict[str, str] = {}
    fact_use_counts: dict[str, int] = {}
    seen_steps: set[str] = set()
    valid = True
    with localcontext() as context:
        context.prec = 38
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("step_id"), str) or step["step_id"] in seen_steps:
                add("calculation_step_id_invalid", "Calculation step IDs must be unique strings", invalid=True)
                valid = False
                continue
            step_id = step["step_id"]
            seen_steps.add(step_id)
            op = step.get("operation")
            inputs = step.get("inputs") or []
            args: list[Decimal] = []
            for ref in inputs:
                if ref in sources:
                    raw = sources[ref][0].get("numeric_value")
                    try:
                        number = Decimal(str(raw))
                    except Exception:
                        number = Decimal("NaN")
                    fact_use_counts[ref] = fact_use_counts.get(ref, 0) + 1
                elif ref in values:
                    number = values[ref]
                else:
                    add("calculation_step_reference_invalid", "Calculation step references a missing, forward, or nonnumeric input", invalid=True)
                    valid = False
                    continue
                if not number.is_finite():
                    add("calculation_source_nonnumeric", "A calculation input is not a finite decimal", invalid=True)
                    valid = False
                args.append(number)
            try:
                if op in {"sum", "add"} and args:
                    computed = sum(args, Decimal(0))
                elif op == "subtract" and len(args) == 2:
                    computed = args[0] - args[1]
                elif op == "multiply" and len(args) == 2:
                    computed = args[0] * args[1]
                elif op == "divide" and len(args) == 2 and args[1] != 0:
                    computed = args[0] / args[1]
                elif op == "round" and len(args) == 1 and isinstance(step.get("scale"), int) and 0 <= step["scale"] <= 12:
                    computed = args[0].quantize(Decimal(1).scaleb(-step["scale"]), rounding=ROUND_HALF_UP)
                else:
                    add("calculation_operation_unsupported", "A calculation step has an unsupported operation or invalid arity")
                    valid = False
                    continue
            except Exception:
                add("calculation_operation_invalid", "A calculation operation could not be evaluated", invalid=True)
                valid = False
                continue
            values[step_id] = computed
            refs_as_text = [expressions.get(ref, ref) for ref in inputs]
            if op in {"sum", "add"}:
                expressions[step_id] = " + ".join(refs_as_text)
            elif op == "subtract" and len(refs_as_text) == 2:
                expressions[step_id] = f"({refs_as_text[0]} - {refs_as_text[1]})"
            elif op == "multiply" and len(refs_as_text) == 2:
                expressions[step_id] = f"({refs_as_text[0]} × {refs_as_text[1]})"
            elif op == "divide" and len(refs_as_text) == 2:
                expressions[step_id] = f"({refs_as_text[0]} ÷ {refs_as_text[1]})"
            elif op == "round" and len(refs_as_text) == 1:
                expressions[step_id] = f"round({refs_as_text[0]}, {step.get('scale')})"
            if index < len(trace):
                recorded = trace[index]
                if recorded.get("step_id") != step_id or recorded.get("operation") != op or recorded.get("inputs") != inputs:
                    add("calculation_trace_mismatch", "Recorded operation trace does not match the formal plan", invalid=True)
                try:
                    recorded_value = Decimal(str(recorded.get("value")))
                except Exception:
                    recorded_value = Decimal("NaN")
                if not recorded_value.is_finite() or recorded_value != computed:
                    add("calculation_trace_value_mismatch", "Recorded operation value differs from independent Decimal evaluation", invalid=True)
        result_step_id = plan.get("result_step_id")
        if result_step_id not in values:
            add("calculation_result_step_missing", "Formal result step does not exist", invalid=True)
            valid = False
        else:
            reachable_steps: set[str] = set()
            reachable_facts: dict[str, int] = {}

            def visit(step_id: str) -> None:
                if step_id in reachable_steps:
                    return
                reachable_steps.add(step_id)
                step = next((candidate for candidate in steps if candidate.get("step_id") == step_id), None)
                if step is None:
                    return
                for ref in step.get("inputs", []):
                    if ref in sources:
                        reachable_facts[ref] = reachable_facts.get(ref, 0) + 1
                    elif ref in {candidate.get("step_id") for candidate in steps}:
                        visit(ref)

            visit(result_step_id)
            if reachable_steps != seen_steps or any(reachable_facts.get(fact_id) != 1 for fact_id in included):
                add("calculation_plan_coverage_invalid", "Every plan step and included fact must contribute exactly once to the final result", invalid=True)
            result_value = values[result_step_id]
            try:
                exact_value = Decimal(str(calculation.get("exact_value_before_rounding")))
                if not exact_value.is_finite() or exact_value != result_value:
                    add("calculation_exact_value_mismatch", "Exact result differs from independent Decimal evaluation", invalid=True)
                    valid = False
            except Exception:
                add("calculation_exact_value_missing", "Exact calculation result is missing or invalid", invalid=True)
                valid = False
            if (calculation.get("rounding") or {}).get("applied") is True:
                rounding = calculation.get("rounding") or {}
                if rounding.get("mode") != "ROUND_HALF_UP" or rounding.get("scale") != plan.get("rounding_scale"):
                    add("calculation_rounding_mismatch", "Declared rounding policy is inconsistent with the formal plan", invalid=True)
                    valid = False
                else:
                    result_value = result_value.quantize(Decimal(1).scaleb(-rounding["scale"]), rounding=ROUND_HALF_UP)
            try:
                expected = Decimal(str(calculation.get("expected_value")))
                if not expected.is_finite() or expected != result_value:
                    add("calculation_expected_value_mismatch", "Expected result differs from the independently evaluated plan", invalid=True)
                    valid = False
            except Exception:
                add("calculation_expected_value_missing", "Expected calculation result is missing or invalid", invalid=True)
            if expressions.get(result_step_id) != calculation.get("formula"):
                add("calculation_formula_mismatch", "Declared formula differs from the expression generated by the formal calculation plan", invalid=True)
                valid = False
    for fact_id in included:
        if fact_use_counts.get(fact_id) != 1:
            add("calculation_fact_multiplicity_invalid", "Each included source fact must contribute exactly once to the final calculation", invalid=True)
    if calculation.get("formula_status") != "executed":
        add("calculation_formula_unverified", "Reconciliation has not marked the formal calculation formula as executed")
    linking_context = calculation.get("linking_context") or {}
    if linking_context.get("review_required") or linking_context.get("link_validation_diagnostics"):
        add("calculation_linking_context_unresolved", "Linking review or validation diagnostics remain unresolved")
    return issues


def _decimal_operation(op: str, args: list[Decimal], scale: int | None) -> Decimal:
    with localcontext() as context:
        context.prec = 38
        if op == "sum" and args:
            return sum(args, Decimal(0))
        if op == "add" and len(args) == 2:
            return args[0] + args[1]
        if op == "subtract" and len(args) == 2:
            return args[0] - args[1]
        if op == "multiply" and len(args) == 2:
            return args[0] * args[1]
        if op == "divide" and len(args) == 2 and args[1] != 0:
            return args[0] / args[1]
        if op == "round" and len(args) == 1 and isinstance(scale, int) and 0 <= scale <= 12:
            return args[0].quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    raise ValueError("Unsupported operation or invalid arity")


def _provisional_formula_matches(operation: dict[str, Any]) -> bool:
    formula = operation.get("formula")
    if not isinstance(formula, str) or not formula.strip():
        return False
    op = operation.get("operation_type")
    inputs = operation.get("input_source_ids", [])
    normalized = re.sub(r"\s+", "", formula).lower()
    joined = ",".join(str(item) for item in inputs).lower()
    if op == "sum":
        return normalized == f"sum({joined})" or normalized == "+".join(str(item).lower() for item in inputs)
    function_name = {
        "add": "add", "subtract": "subtract", "multiply": "multiply", "divide": "divide",
    }.get(op)
    if function_name:
        return normalized == f"{function_name}({joined})"
    if op == "round" and len(inputs) == 1:
        scale = operation.get("scale")
        return normalized in {f"round({inputs[0]},{scale})", f"round({inputs[0]},{scale},half_up)"}
    if op == "period_selection" and len(inputs) == 1:
        # The value equality is verified against this exact source below.
        return True
    return False


def provisional_operation_diagnostics(expected: dict[str, Any], checks: list[Any]) -> list[dict[str, Any]]:
    """Independently evaluate the provisional adapter's simple operation trace."""
    issues: list[dict[str, Any]] = []
    sources = {item.source.get("source_id"): item for item in checks}
    operations = expected.get("operations", [])
    if not operations:
        return [{"code": "calculation_proof_unverified", "message": "No calculation operations were supplied to support the result"}]
    values: dict[str, Decimal] = {}
    copied_values: dict[str, Any] = {}
    for operation in operations:
        op_id = operation.get("operation_id")
        op = operation.get("operation_type")
        inputs = operation.get("input_source_ids", [])
        if not _provisional_formula_matches(operation):
            issues.append({"code": "calculation_formula_mismatch", "message": "Declared operation formula does not encode its operation and exact inputs"})
        args: list[Decimal] = []
        raw_args: list[Any] = []
        for ref in inputs:
            if ref in sources:
                value = sources[ref].resolved_value
                raw_args.append(value)
                if isinstance(value, dict):
                    value = value.get("amount")
                try:
                    args.append(Decimal(str(value)))
                except Exception:
                    args.append(Decimal("NaN"))
            elif ref in values:
                args.append(values[ref])
                raw_args.append(values[ref])
            else:
                issues.append({"code": "calculation_input_source_unresolved", "message": "A provisional operation input is unresolved"})
        if not inputs:
            continue
        try:
            if op == "period_selection" and len(raw_args) == 1:
                copied_values[op_id] = raw_args[0]
                value = None
            elif all(arg.is_finite() for arg in args): value = _decimal_operation(op, args, operation.get("scale"))
            else:
                issues.append({"code": "calculation_operation_unverified", "message": "A provisional calculation operation is unsupported or has invalid arity"})
                continue
        except Exception:
            issues.append({"code": "calculation_operation_invalid", "message": "A provisional calculation operation could not be evaluated"})
            continue
        if value is None:
            if canonical_json(operation.get("output_value")) != canonical_json(copied_values[op_id]):
                issues.append({"code": "calculation_operation_value_mismatch", "message": "Selected period differs from the exact source period"})
        else:
            values[op_id] = value
            try:
                declared = Decimal(str(operation.get("output_value")))
            except Exception:
                declared = Decimal("NaN")
            if not declared.is_finite() or declared != value:
                issues.append({"code": "calculation_operation_value_mismatch", "message": "Provisional operation output differs from independent Decimal evaluation"})
    expected_value = expected.get("expected_value")
    if isinstance(expected_value, dict) and "amount" in expected_value:
        expected_value = expected_value.get("amount")
    final_id = operations[-1].get("operation_id")
    if final_id in copied_values:
        output_matches = canonical_json(copied_values[final_id]) == canonical_json(expected_value)
    else:
        final = values.get(final_id)
        try:
            expected_decimal = Decimal(str(expected_value))
        except Exception:
            expected_decimal = Decimal("NaN")
        output_matches = final is not None and expected_decimal.is_finite() and final == expected_decimal
    if not output_matches:
        issues.append({"code": "calculation_output_mismatch", "message": "The final operation does not equal the Reconciliation expected value"})
    return issues
