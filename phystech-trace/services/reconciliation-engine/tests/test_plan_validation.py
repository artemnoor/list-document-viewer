from reconciliation_engine.engine import execute_plan, validate_plan
from reconciliation_engine.facts import extract_facts

from conftest import load_upstream, make_linking, make_target, plan_for


def test_saved_plan_selection_is_validated_separately_from_arithmetic():
    act = load_upstream("act-2026-0424.json")
    facts = extract_facts([act])
    selected = next(fact for fact in facts if fact.role == "indicator" and fact.key == "amount_due")
    plan = plan_for([act], [selected])
    linking = make_linking([act])

    # Plan choice and source admissibility are assessed without running the calculator.
    assert validate_plan(plan, make_target(), facts, linking) == []

    # Independently execute the frozen plan and compare to a hand-calculated oracle.
    value, trace = execute_plan(plan, facts)
    assert str(value) == "1180300.00"
    assert trace == [{"step_id": "result", "operation": "sum", "inputs": [selected.fact_id], "value": "1180300.00"}]


def test_plan_selection_rejects_review_status_even_when_value_is_present():
    act = load_upstream("act-2026-0424.json")
    wrapper = act["line_items"][0]["amount"]
    wrapper["status"] = "review"
    facts = extract_facts([act])
    selected = next(fact for fact in facts if fact.role == "line_item" and fact.key == "amount" and fact.row_id == act["line_items"][0]["row_id"])
    diagnostics = validate_plan(plan_for([act], [selected]), make_target(), facts, make_linking([act]))
    assert any(item.code == "source_not_usable" for item in diagnostics)


def test_plan_selection_excludes_explicitly_out_of_period_registry_values():
    kfz = load_upstream("kfz-2026-q1.json")
    registry = load_upstream("registry-2026-04.json")
    facts = extract_facts([kfz, registry])
    selected = next(fact for fact in facts if fact.document_id == registry["document_id"] and fact.role == "line_item" and fact.key == "amount")
    plan = plan_for([kfz, registry], [selected])
    diagnostics = validate_plan(plan, make_target(period_basis="document_period"), facts, make_linking([kfz, registry]), period_start=__import__("datetime").date(2026, 1, 1), period_end=__import__("datetime").date(2026, 3, 31))
    assert any(item.code == "period_outside_context" for item in diagnostics)


def test_plan_selection_requires_reason_for_each_excluded_financial_candidate():
    act = load_upstream("act-2026-0424.json")
    facts = extract_facts([act])
    selected = next(fact for fact in facts if fact.role == "indicator" and fact.key == "amount_due")
    plan = plan_for([act], [selected], exclusions=[])
    diagnostics = validate_plan(plan, make_target(), facts, make_linking([act]))
    assert any(item.code == "excluded_source_reason_missing" for item in diagnostics)


def test_plan_selection_checks_target_rounding_scale():
    act = load_upstream("act-2026-0424.json")
    facts = extract_facts([act])
    selected = next(fact for fact in facts if fact.role == "indicator" and fact.key == "amount_due")
    plan = plan_for([act], [selected])
    plan.rounding_scale = 3
    diagnostics = validate_plan(plan, make_target(), facts, make_linking([act]))
    assert any(item.code == "rounding_scale_mismatch" for item in diagnostics)
def test_linking_reference_edge_is_not_a_plan_to_sum_both_documents():
    act = load_upstream("act-2026-0424.json")
    contract = load_upstream("contract-2026-0315.json")
    facts = extract_facts([act, contract])
    target = make_target()
    # A saved plan containing only the act amount is admissible. The contract amount
    # is independently excluded even though both documents can be connected upstream.
    selected = next(fact for fact in facts if fact.document_id == act["document_id"] and fact.role == "indicator" and fact.key == "amount_due")
    plan = plan_for([act, contract], [selected])
    linking = make_linking([act, contract])
    linking["links"] = [{
        "link_id": "reference-only",
        "relationship_type": "references_contract",
        "source_document_id": act["document_id"],
        "target_document_id": contract["document_id"],
        "evidence": [{"source": {"document_id": act["document_id"], "path": "fields.contract_reference", "raw_value": "contract", "normalized_value": "contract", "provenance": None}, "target": {"document_id": contract["document_id"], "path": "fields.contract_number", "raw_value": "contract", "normalized_value": "contract", "provenance": None}, "signal": "reference", "explanation": "References a contract."}],
        "explanation": "Document references contract.",
        "confidence": 0.9,
        "status": "confirmed",
        "verification_status": "not_reviewed",
        "detection_method": "llm",
        "conflicts": [],
    }]
    assert validate_plan(plan, target, facts, linking) == []
    assert contract["document_id"] not in {selected.document_id}

