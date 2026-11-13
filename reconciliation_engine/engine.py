from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re
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
        if fact.row_id:
            endpoints = {
                (link.get("source_document_id"), link.get("source_row_id")),
                (link.get("target_document_id"), link.get("target_row_id")),
            }
            match = (fact.document_id, fact.row_id) in endpoints
        else:
            match = fact.document_id in {link.get("source_document_id"), link.get("target_document_id")}
        if match:
            related.append(link)
    return related


def _explicit_net_conversion_facts(plan: CalculationPlan, facts: list[Fact], target: TargetIndicator) -> set[str]:
    if target.amount_basis != "net" or plan.amount_basis != "net":
        return set()
    selected = [fact for fact in facts if fact.fact_id in {item.fact_id for item in plan.included}]
    vat_facts = [fact for fact in selected if re.search(r"vat|ндс", f"{fact.key} {fact.label}", re.IGNORECASE)]
    if len(vat_facts) != 1:
        return set()
    vat = vat_facts[0]
    gross_candidates = [fact for fact in selected if fact.document_id == vat.document_id and fact.fact_id != vat.fact_id and fact.currency == vat.currency]
    for gross in gross_candidates:
        if any(step.operation == "subtract" and step.inputs == [gross.fact_id, vat.fact_id] for step in plan.steps):
            return {gross.fact_id, vat.fact_id}
    return set()


def validate_plan(
    plan: CalculationPlan,
    target: TargetIndicator,
    facts: list[Fact],
    linking: dict[str, Any],
    period_start: Any = None,
    period_end: Any = None,
    human_confirmed_fact_ids: set[str] | None = None,
    independence_confirmed: bool = False,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    human_confirmed_fact_ids = human_confirmed_fact_ids or set()
    fact_by_id = {fact.fact_id: fact for fact in facts}
    included_ids = [item.fact_id for item in plan.included]
    duplicates = [key for key, count in Counter(included_ids).items() if count > 1]
    for fact_id in duplicates:
        diagnostics.append(Diagnostic("duplicate_fact_in_plan", "$.plan.included", "A source fact may be included only once", {"fact_id": fact_id}))
    selected_facts: list[Fact] = []
    converted_net_fact_ids = _explicit_net_conversion_facts(plan, facts, target)
    included_paths = {item.fact_id: f"$.plan.included[{index}].fact_id" for index, item in enumerate(plan.included)}
    for fact_id in included_ids:
        fact = fact_by_id.get(fact_id)
        if fact is None:
            diagnostics.append(Diagnostic("unknown_fact_id", included_paths[fact_id], "Plan refers to a fact outside the supplied extraction snapshot", {"fact_id": fact_id}))
            continue
        selected_facts.append(fact)
        if fact.document_id == target.kfz_document_id or fact.document_type == "kfz_report":
            code = "target_fact_self_reference" if fact.fact_id == target.target_fact_id or fact.document_id == target.kfz_document_id else "kfz_source_forbidden"
            diagnostics.append(Diagnostic(code, included_paths[fact_id], "KФЗ values are context only and cannot be used as independent financial evidence", {"fact_id": fact_id, "document_id": fact.document_id}))
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
        if (period_start or period_end) and target.period_basis != "none":
            if fact.period_start is None or fact.period_end is None:
                diagnostics.append(Diagnostic("source_period_unknown", fact.source_path, "The selected financial value has no verifiable operation or document period", {"fact_id": fact_id}))
            elif (period_start and fact.period_end < period_start) or (period_end and fact.period_start > period_end):
                diagnostics.append(Diagnostic("period_outside_context", fact.source_path, "Source operation period does not overlap the requested reconciliation period", {"fact_id": fact_id, "source_period": [fact.period_start.isoformat(), fact.period_end.isoformat()], "requested_period": [period_start.isoformat() if period_start else None, period_end.isoformat() if period_end else None]}))
            elif (period_start and fact.period_start < period_start) or (period_end and fact.period_end > period_end):
                diagnostics.append(Diagnostic("period_partial_overlap", fact.source_path, "The source period only partially overlaps the requested reconciliation period; no prorating rule was supplied", {"fact_id": fact_id, "source_period": [fact.period_start.isoformat(), fact.period_end.isoformat()], "requested_period": [period_start.isoformat() if period_start else None, period_end.isoformat() if period_end else None]}))
    currencies = {fact.currency for fact in selected_facts if fact.currency}
    units = {fact.unit for fact in selected_facts if fact.unit}
    measure_types = {fact.economic_measure for fact in selected_facts if fact.economic_measure}
    amount_bases = {fact.amount_basis for fact in selected_facts if fact.amount_basis}
    if len(currencies) > 1:
        diagnostics.append(Diagnostic("mixed_currencies", "$.plan.included", "Selected source values use different currencies; no exchange-rate conversion was supplied", {"currencies": sorted(currencies)}))
    if len(units) > 1:
        diagnostics.append(Diagnostic("mixed_units", "$.plan.included", "Selected source values use incompatible units; no conversion was supplied", {"units": sorted(units)}))
    if len(measure_types) > 1:
        diagnostics.append(Diagnostic("mixed_economic_measures", "$.plan.included", "Planned, actual, accrued, or paid values cannot be combined without an explicit supported conversion", {"measures": sorted(measure_types)}))
    if len(amount_bases) > 1:
        diagnostics.append(Diagnostic("mixed_amount_bases", "$.plan.included", "Gross and net values cannot be combined without an explicitly evidenced conversion", {"amount_bases": sorted(amount_bases)}))
    if target.economic_measure != "unspecified":
        for fact in selected_facts:
            if fact.economic_measure is None:
                diagnostics.append(Diagnostic("economic_measure_unknown", fact.source_path, "The selected value is not identified as planned, actual, accrued, or paid", {"fact_id": fact.fact_id, "expected": target.economic_measure}))
            elif fact.economic_measure != target.economic_measure:
                diagnostics.append(Diagnostic("economic_measure_mismatch", fact.source_path, "The selected value has a different economic measure from the target", {"fact_id": fact.fact_id, "expected": target.economic_measure, "actual": fact.economic_measure}))
    if target.amount_basis != "unspecified":
        for fact in selected_facts:
            if fact.fact_id in converted_net_fact_ids:
                continue
            if fact.amount_basis is None:
                diagnostics.append(Diagnostic("amount_basis_unknown", fact.source_path, "The selected value does not identify whether it is gross or net", {"fact_id": fact.fact_id, "expected": target.amount_basis}))
            elif fact.amount_basis != target.amount_basis:
                diagnostics.append(Diagnostic("amount_basis_mismatch", fact.source_path, "The selected value has a different gross/net basis from the target", {"fact_id": fact.fact_id, "expected": target.amount_basis, "actual": fact.amount_basis}))
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
    monetary = [fact for fact in selected_facts if isinstance(fact.normalized_value, dict) and "amount" in fact.normalized_value]
    for fact in monetary:
        if not fact.currency:
            diagnostics.append(Diagnostic("source_currency_unknown", fact.source_path, "A monetary source value must identify its currency", {"fact_id": fact.fact_id}))
    if monetary and not (target.currency or plan.currency):
        diagnostics.append(Diagnostic("target_currency_unknown", "$.plan.currency", "The result currency is unknown for monetary source values"))

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
    # Treat correspondence as an equivalence relation, not only a set of direct
    # pairs: A↔B and B↔C also means A and C are representations of one operation.
    parents: dict[tuple[str, str], tuple[str, str]] = {}

    def find(item: tuple[str, str]) -> tuple[str, str]:
        parents.setdefault(item, item)
        if parents[item] != item:
            parents[item] = find(parents[item])
        return parents[item]

    for pair in _row_correspondence(linking):
        endpoints = list(pair)
        if len(endpoints) == 2:
            left, right = find(endpoints[0]), find(endpoints[1])
            if left != right:
                parents[right] = left
    selected_components: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for item in selected_rows:
        selected_components.setdefault(find(item), []).append(item)
    for rows in selected_components.values():
        if len(rows) > 1:
            diagnostics.append(Diagnostic("corresponding_rows_double_counted", "$.plan.included", "Linking identifies selected rows as representations of the same operation; they cannot both be summed", {"rows": [list(item) for item in sorted(rows)]}))

    selected_documents = {fact.document_id for fact in selected_facts}
    if len(selected_documents) > 1 and not independence_confirmed:
        diagnostics.append(Diagnostic("independence_not_established", "$.plan.included", "A missing or non-corresponding Linking edge does not establish that values from separate documents represent independent operations", {"document_ids": sorted(selected_documents)}))

    # Validate an acyclic, explicit arithmetic DAG. Inputs may refer only to earlier
    # steps or selected facts; arbitrary constants are never accepted.
    known = set(included_ids)
    step_ids: set[str] = set()
    step_index: dict[str, int] = {}
    for index, step in enumerate(plan.steps):
        path = f"$.plan.steps[{index}]"
        if step.step_id in step_ids or step.step_id in fact_by_id:
            diagnostics.append(Diagnostic("duplicate_step_id", f"{path}.step_id", "Step IDs must be unique and cannot shadow fact IDs", {"step_id": step.step_id}))
        step_ids.add(step.step_id)
        step_index.setdefault(step.step_id, index)
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
        known.add(step.step_id)
    if plan.result_step_id not in step_ids:
        diagnostics.append(Diagnostic("missing_result_step", "$.plan.result_step_id", "result_step_id must identify a calculation step", {"result_step_id": plan.result_step_id}))
    # Walk backward from the final expression. Merely appearing somewhere in the
    # submitted steps is not enough: detached or repeated intermediate nodes must
    # not silently influence validation or the reported provenance.
    reachable_steps: set[str] = set()
    expanded_steps: dict[str, Counter[str]] = {}

    def expand_step(step_id: str, active: set[str], parent_path: str) -> Counter[str]:
        if step_id in active:
            diagnostics.append(Diagnostic("calculation_cycle", parent_path, "The result expression contains a cycle", {"step_id": step_id}))
            return Counter()
        if step_id in expanded_steps:
            return expanded_steps[step_id].copy()
        index = step_index.get(step_id)
        if index is None:
            return Counter()
        reachable_steps.add(step_id)
        next_active = {*active, step_id}
        multiplicity: Counter[str] = Counter()
        step = plan.steps[index]
        for input_index, source_id in enumerate(step.inputs):
            if source_id in step_index:
                multiplicity.update(expand_step(source_id, next_active, f"$.plan.steps[{index}].inputs[{input_index}]"))
            elif source_id in fact_by_id:
                multiplicity[source_id] += 1
        expanded_steps[step_id] = multiplicity.copy()
        return multiplicity

    if plan.result_step_id in step_index:
        fact_multiplicity = expand_step(plan.result_step_id, set(), "$.plan.result_step_id")
    else:
        fact_multiplicity = Counter()
    unreachable = [step.step_id for step in plan.steps if step.step_id not in reachable_steps]
    if unreachable:
        diagnostics.append(Diagnostic("unreachable_calculation_steps", "$.plan.steps", "Every calculation step must contribute to result_step_id", {"step_ids": unreachable}))
    missing_from_result = [fact_id for fact_id in included_ids if fact_multiplicity[fact_id] == 0]
    repeated_in_result = {fact_id: count for fact_id, count in fact_multiplicity.items() if count > 1}
    if missing_from_result:
        diagnostics.append(Diagnostic("unused_or_unreferenced_fact", "$.plan.result_step_id", "Every included fact must contribute to the final result", {"fact_ids": missing_from_result}))
    if repeated_in_result:
        diagnostics.append(Diagnostic("fact_used_multiple_times", "$.plan.result_step_id", "A source fact contributes more than once through the expanded result expression", {"fact_multiplicity": repeated_in_result}))

    excluded_fact_ids = {item.fact_id for item in plan.excluded if item.fact_id}
    excluded_group_ids = {item.source_group_id for item in plan.excluded if item.source_group_id}
    missing_explanations = sorted(
        fact.fact_id for fact in facts
        if fact.fact_id not in set(included_ids)
        and fact.document_id != target.kfz_document_id
        and fact.document_type != "kfz_report"
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

