from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any

from .errors import Diagnostic
from .facts import Fact, numeric_value
from .models import TargetIndicator
from .plans import CalculationPlan


def decimal_string(value: Decimal, scale: int | None = None) -> str:
    if scale is not None:
        quantum = Decimal(1).scaleb(-scale)
        value = value.quantize(quantum, rounding=ROUND_HALF_UP)
        return f"{value:.{scale}f}"
    return format(value, "f")


def _row_correspondence(linking: dict[str, Any]) -> set[frozenset[tuple[str, str]]]:
    pairs: set[frozenset[tuple[str, str]]] = set()
    for link in linking.get("links", []):
        if link.get("relationship_type") != "line_item_correspondence":
            continue
        left, right = link.get("source_row_id"), link.get("target_row_id")
        if left and right:
            pairs.add(frozenset({(link["source_document_id"], left), (link["target_document_id"], right)}))
    return pairs


def related_links_for_fact(fact: Fact, linking: dict[str, Any]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for link in linking.get("links", []):
        match = fact.document_id in {link.get("source_document_id"), link.get("target_document_id")}
        row_ids = {link.get("source_row_id"), link.get("target_row_id")}
        if fact.row_id and fact.row_id in row_ids:
            match = True
        if match:
            related.append(link)
    return related


def validate_plan(
    plan: CalculationPlan,
    target: TargetIndicator,
    facts: list[Fact],
    linking: dict[str, Any],
    period_start: Any = None,
    period_end: Any = None,
    human_confirmed_fact_ids: set[str] | None = None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    human_confirmed_fact_ids = human_confirmed_fact_ids or set()
    fact_by_id = {fact.fact_id: fact for fact in facts}
    included_ids = [item.fact_id for item in plan.included]
    duplicates = [key for key, count in Counter(included_ids).items() if count > 1]
    for fact_id in duplicates:
        diagnostics.append(Diagnostic("duplicate_fact_in_plan", "$.plan.included", "A source fact may be included only once", {"fact_id": fact_id}))
    selected_facts: list[Fact] = []
    for fact_id in included_ids:
        fact = fact_by_id.get(fact_id)
        if fact is None:
            diagnostics.append(Diagnostic("unknown_fact_id", "$.plan.included", "Plan refers to a fact outside the supplied extraction snapshot", {"fact_id": fact_id}))
            continue
        selected_facts.append(fact)
        if fact.status != "extracted" and not (fact.status == "review" and fact.fact_id in human_confirmed_fact_ids):
            diagnostics.append(Diagnostic("source_not_usable", f"{fact.source_path}.status", "A review value needs an explicit human confirmation before it can enter arithmetic", {"fact_id": fact_id, "status": fact.status}))
        if numeric_value(fact) is None:
            diagnostics.append(Diagnostic("source_not_numeric", fact.source_path, "The selected normalized value is missing or non-numeric", {"fact_id": fact_id, "value": fact.normalized_value}))
        if target.currency and not fact.currency:
            diagnostics.append(Diagnostic("currency_missing", fact.source_path, "Source currency is absent while the target requires an explicit currency", {"fact_id": fact_id, "expected": target.currency}))
        elif fact.currency and target.currency and fact.currency != target.currency:
            diagnostics.append(Diagnostic("currency_mismatch", fact.source_path, "Source currency does not match the target currency", {"fact_id": fact_id, "expected": target.currency, "actual": fact.currency}))
        if target.unit and not fact.unit:
            diagnostics.append(Diagnostic("unit_missing", fact.source_path, "Source unit is absent while the target requires an explicit unit", {"fact_id": fact_id, "expected": target.unit}))
        elif fact.unit and target.unit and fact.unit != target.unit:
            diagnostics.append(Diagnostic("unit_mismatch", fact.source_path, "Source unit does not match the target unit", {"fact_id": fact_id, "expected": target.unit, "actual": fact.unit}))
        if period_start and period_end and target.period_basis == "document_period" and fact.period_start and fact.period_end:
            if fact.period_end < period_start or fact.period_start > period_end:
                diagnostics.append(Diagnostic("period_outside_context", fact.source_path, "Source document period does not overlap the requested reconciliation period", {"fact_id": fact_id, "source_period": [fact.period_start.isoformat(), fact.period_end.isoformat()], "requested_period": [period_start.isoformat(), period_end.isoformat()]}))
    currencies = {fact.currency for fact in selected_facts if fact.currency}
    units = {fact.unit for fact in selected_facts if fact.unit}
    if len(currencies) > 1:
        diagnostics.append(Diagnostic("mixed_currencies", "$.plan.included", "Selected source values use different currencies; no exchange-rate conversion was supplied", {"currencies": sorted(currencies)}))
    if len(units) > 1:
        diagnostics.append(Diagnostic("mixed_units", "$.plan.included", "Selected source values use incompatible units; no conversion was supplied", {"units": sorted(units)}))
    if plan.target_id != target.target_id:
        diagnostics.append(Diagnostic("target_mismatch", "$.plan.target_id", "Plan target_id does not match the requested target", {"expected": target.target_id, "actual": plan.target_id}))
    if target.amount_basis != "unspecified" and plan.amount_basis != target.amount_basis:
        diagnostics.append(Diagnostic("amount_basis_mismatch", "$.plan.amount_basis", "Plan amount basis does not match the target", {"expected": target.amount_basis, "actual": plan.amount_basis}))
    if plan.rounding_scale != target.rounding_scale:
        diagnostics.append(Diagnostic("rounding_scale_mismatch", "$.plan.rounding_scale", "Plan rounding scale does not match the target", {"expected": target.rounding_scale, "actual": plan.rounding_scale}))
    if target.currency and plan.currency != target.currency:
        diagnostics.append(Diagnostic("currency_mismatch", "$.plan.currency", "Plan currency does not match the target", {"expected": target.currency, "actual": plan.currency}))
    if target.unit and plan.unit != target.unit:
        diagnostics.append(Diagnostic("unit_mismatch", "$.plan.unit", "Plan unit does not match the target", {"expected": target.unit, "actual": plan.unit}))
    if plan.currency and any(fact.currency and fact.currency != plan.currency for fact in selected_facts):
        diagnostics.append(Diagnostic("currency_mismatch", "$.plan.currency", "Plan currency does not match one or more selected source values", {"expected": plan.currency, "actual": sorted(currencies)}))
    if plan.unit and any(fact.unit and fact.unit != plan.unit for fact in selected_facts):
        diagnostics.append(Diagnostic("unit_mismatch", "$.plan.unit", "Plan unit does not match one or more selected source values", {"expected": plan.unit, "actual": sorted(units)}))

    # A report total and its own line items can be overlapping representations.
    by_document: dict[str, list[Fact]] = {}
    for fact_id in included_ids:
        fact = fact_by_id.get(fact_id)
        if fact:
            by_document.setdefault(fact.document_id, []).append(fact)
    for document_id, selected in by_document.items():
        roles = {fact.role for fact in selected}
        if "line_item" in roles and roles.intersection({"field", "indicator"}):
            diagnostics.append(Diagnostic("header_and_rows_overlap", "$.plan.included", "A document summary and its line-item values are both selected; establish that they are disjoint before adding", {"document_id": document_id, "fact_ids": [fact.fact_id for fact in selected]}))

    selected_rows = {(fact_by_id[fid].document_id, fact_by_id[fid].row_id) for fid in included_ids if fid in fact_by_id and fact_by_id[fid].row_id}
    for pair in _row_correspondence(linking):
        if pair.issubset(selected_rows):
            diagnostics.append(Diagnostic("corresponding_rows_double_counted", "$.plan.included", "Linking marks these rows as corresponding views of one line; they cannot both be summed", {"rows": [list(item) for item in sorted(pair)]}))

    # Validate an acyclic, explicit arithmetic DAG. Inputs may refer only to earlier
    # steps or selected facts; arbitrary constants are never accepted.
    known = set(included_ids)
    used_facts: list[str] = []
    step_ids: set[str] = set()
    for index, step in enumerate(plan.steps):
        path = f"$.plan.steps[{index}]"
        if step.step_id in step_ids or step.step_id in fact_by_id:
            diagnostics.append(Diagnostic("duplicate_step_id", f"{path}.step_id", "Step IDs must be unique and cannot shadow fact IDs", {"step_id": step.step_id}))
        step_ids.add(step.step_id)
        arity = len(step.inputs)
        expected = {"subtract": 2, "multiply": 2, "divide": 2, "round": 1}
        if step.operation in expected and arity != expected[step.operation]:
            diagnostics.append(Diagnostic("invalid_operation_arity", f"{path}.inputs", f"{step.operation} requires {expected[step.operation]} inputs", {"actual": arity}))
        if step.operation == "sum" and arity < 1:
            diagnostics.append(Diagnostic("invalid_operation_arity", f"{path}.inputs", "sum requires at least one input", {"actual": arity}))
        if step.operation == "add" and arity < 2:
            diagnostics.append(Diagnostic("invalid_operation_arity", f"{path}.inputs", "add requires at least two inputs", {"actual": arity}))
        if step.operation == "round" and step.scale is None:
            diagnostics.append(Diagnostic("round_scale_required", f"{path}.scale", "A rounding step must specify scale"))
        if step.operation != "round" and step.scale is not None:
            diagnostics.append(Diagnostic("unexpected_step_scale", f"{path}.scale", "scale is supported only by a round step"))
        for input_index, source_id in enumerate(step.inputs):
            if source_id not in known:
                diagnostics.append(Diagnostic("unknown_step_input", f"{path}.inputs[{input_index}]", "Step input must reference an included fact or a previous step", {"input": source_id}))
            elif source_id in fact_by_id:
                used_facts.append(source_id)
        known.add(step.step_id)
    if plan.result_step_id not in step_ids:
        diagnostics.append(Diagnostic("missing_result_step", "$.plan.result_step_id", "result_step_id must identify a calculation step", {"result_step_id": plan.result_step_id}))
    if set(used_facts) != set(included_ids):
        diagnostics.append(Diagnostic("unused_or_unreferenced_fact", "$.plan.steps", "Every included fact must be used by the calculation and no included fact may be used twice", {"included": included_ids, "used": used_facts}))
    duplicate_uses = [key for key, count in Counter(used_facts).items() if count > 1]
    if duplicate_uses:
        diagnostics.append(Diagnostic("fact_used_multiple_times", "$.plan.steps", "A source fact may contribute only once to prevent accidental duplication", {"fact_ids": duplicate_uses}))

    excluded_fact_ids = {item.fact_id for item in plan.excluded if item.fact_id}
    excluded_group_ids = {item.source_group_id for item in plan.excluded if item.source_group_id}
    missing_explanations = sorted(
        fact.fact_id for fact in facts
        if fact.fact_id not in set(included_ids)
        and fact.document_id not in excluded_group_ids
        and fact.fact_id not in excluded_fact_ids
        and numeric_value(fact) is not None
        and fact.status in {"extracted", "review"}
    )
    if missing_explanations:
        diagnostics.append(Diagnostic("excluded_source_reason_missing", "$.plan.excluded", "Every unused numeric candidate needs an explicit exclusion reason", {"fact_ids": missing_explanations}))
    return diagnostics


def execute_plan(plan: CalculationPlan, facts: list[Fact]) -> tuple[Decimal, list[dict[str, Any]]]:
    fact_by_id = {fact.fact_id: fact for fact in facts}
    values: dict[str, Decimal] = {}
    trace: list[dict[str, Any]] = []
    with localcontext() as context:
        context.prec = 38
        for step in plan.steps:
            args: list[Decimal] = []
            for source_id in step.inputs:
                if source_id in fact_by_id:
                    number = numeric_value(fact_by_id[source_id])
                    if number is None:
                        raise ValueError(f"Non-numeric source fact {source_id}")
                    args.append(number)
                else:
                    args.append(values[source_id])
            if step.operation in {"sum", "add"}:
                value = sum(args, Decimal(0))
            elif step.operation == "subtract":
                value = args[0] - args[1]
            elif step.operation == "multiply":
                value = args[0] * args[1]
            elif step.operation == "divide":
                if args[1] == 0:
                    raise ZeroDivisionError(f"Division by zero in step {step.step_id}")
                value = args[0] / args[1]
            elif step.operation == "round":
                quantum = Decimal(1).scaleb(-(step.scale or 0))
                value = args[0].quantize(quantum, rounding=ROUND_HALF_UP)
            else:  # Pydantic excludes this branch; keep the engine defensive.
                raise ValueError(f"Unsupported operation: {step.operation}")
            values[step.step_id] = value
            trace.append({
                "step_id": step.step_id,
                "operation": step.operation,
                "inputs": step.inputs,
                "value": decimal_string(value),
            })
        result = values[plan.result_step_id]
    return result, trace

