from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from reconciliation_engine.config import Settings
from reconciliation_engine.engine import validate_plan
from reconciliation_engine.facts import Fact, extract_facts
from reconciliation_engine.models import ConfirmedDecision, TargetIndicator
from reconciliation_engine.planner import LLMPlanner
from reconciliation_engine.plans import CalculationPlan, PlanExclusion, PlanInclusion, PlanStep
from reconciliation_engine.service import bind_decision_to_request, reconcile

from conftest import clone_extraction, load_upstream, make_linking, make_request, make_target, plan_for, set_amount


def _fact(facts: list[Fact], document_id: str, key: str, row_id: str | None = None) -> Fact:
    return next(item for item in facts if item.document_id == document_id and item.key == key and (row_id is None or item.row_id == row_id))


def _codes(calculation: dict) -> set[str]:
    return {item["code"] for item in calculation["diagnostics"]}


def test_kfz_target_cannot_be_used_as_its_own_evidence(settings):
    kfz = load_upstream("kfz-2026-q1.json")
    fact = _fact(extract_facts([kfz]), kfz["document_id"], "reported_total")
    target = make_target(target_fact_id=fact.fact_id, kfz_document_id=kfz["document_id"], kfz_source_path=fact.source_path)
    request = make_request([kfz], plan_for([kfz], [fact]), target)

    result = reconcile(request, settings)["calculations"][0]

    assert result["status"] == "manual_review"
    assert result["expected_value"] is None
    assert "target_fact_self_reference" in _codes(result)


def test_result_dag_rejects_steps_unreachable_from_the_result():
    act = load_upstream("act-2026-0424.json")
    fact = _fact(extract_facts([act]), act["document_id"], "amount_due")
    plan = plan_for([act], [fact], steps=[
        PlanStep(step_id="detached", operation="sum", inputs=[fact.fact_id]),
        PlanStep(step_id="result", operation="sum", inputs=[fact.fact_id]),
    ])

    diagnostics = validate_plan(plan, make_target(), extract_facts([act]), make_linking([act]))

    assert "unreachable_calculation_steps" in {item.code for item in diagnostics}


def test_result_dag_counts_repeated_facts_through_intermediate_nodes():
    act = load_upstream("act-2026-0424.json")
    fact = _fact(extract_facts([act]), act["document_id"], "amount_due")
    plan = plan_for([act], [fact], steps=[
        PlanStep(step_id="subtotal", operation="sum", inputs=[fact.fact_id]),
        PlanStep(step_id="result", operation="add", inputs=["subtotal", "subtotal"]),
    ])

    diagnostics = validate_plan(plan, make_target(), extract_facts([act]), make_linking([act]))

    assert "fact_used_multiple_times" in {item.code for item in diagnostics}


def test_subtract_requires_two_operands_and_reports_exact_path():
    act = load_upstream("act-2026-0424.json")
    fact = _fact(extract_facts([act]), act["document_id"], "amount_due")
    plan = plan_for([act], [fact], steps=[PlanStep(step_id="result", operation="subtract", inputs=[fact.fact_id])])

    diagnostics = validate_plan(plan, make_target(), extract_facts([act]), make_linking([act]))

    item = next(item for item in diagnostics if item.code == "invalid_operation_arity")
    assert item.path == "$.plan.steps[0].inputs"


def test_division_by_zero_becomes_diagnostic_instead_of_http_500(settings):
    act = load_upstream("act-2026-0424.json")
    set_amount(act, 0, "100.00")
    set_amount(act, 1, "0.00")
    facts = extract_facts([act])
    numerator = _fact(facts, act["document_id"], "amount", act["line_items"][0]["row_id"])
    denominator = _fact(facts, act["document_id"], "amount", act["line_items"][1]["row_id"])
    plan = plan_for([act], [numerator, denominator], steps=[PlanStep(step_id="result", operation="divide", inputs=[numerator.fact_id, denominator.fact_id])])

    result = reconcile(make_request([act], plan), settings)["calculations"][0]

    assert result["status"] == "manual_review"
    assert result["expected_value"] is None
    assert "division_by_zero" in _codes(result)


def test_changed_confirmed_fact_value_invalidates_prior_decision(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "amount_due")
    request = make_request([act], plan_for([act], [source]), accepted_fact_ids=[source.fact_id])
    request.extraction_results[0]["fields"]["amount_due"]["value"]["amount"] = "1180301.00"

    result = reconcile(request, settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "stale_human_decision" in _codes(result)


def test_changed_linking_snapshot_invalidates_prior_decision(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "amount_due")
    request = make_request([act], plan_for([act], [source]), accepted_fact_ids=[source.fact_id])
    request.linking_result["linking_run_id"] = "a-different-linking-run"

    result = reconcile(request, settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "stale_human_decision" in _codes(result)


def test_unconfirmed_cross_document_sources_are_not_assumed_independent(settings):
    left = clone_extraction(load_upstream("act-2026-0424.json"), "no-edge-a")
    right = clone_extraction(load_upstream("act-2026-0424.json"), "no-edge-b")
    facts = extract_facts([left, right])
    selected = [_fact(facts, doc["document_id"], "amount", doc["line_items"][0]["row_id"]) for doc in (left, right)]
    result = reconcile(make_request([left, right], plan_for([left, right], selected)), settings)["calculations"][0]

    assert result["expected_value"] is None
    assert "independence_not_established" in _codes(result)


def test_period_partial_overlap_is_blocked_without_proration():
    act = load_upstream("act-2026-0424.json")
    fact = _fact(extract_facts([act]), act["document_id"], "amount_due")
    plan = plan_for([act], [fact])
    diagnostics = validate_plan(plan, make_target(period_basis="document_period"), extract_facts([act]), make_linking([act]), period_start=__import__("datetime").date(2026, 4, 5), period_end=__import__("datetime").date(2026, 4, 30))

    assert "period_partial_overlap" in {item.code for item in diagnostics}


def test_operation_date_overrides_document_period_for_the_value():
    act = load_upstream("act-2026-0424.json")
    act["line_items"][0]["operation_date"] = {"value": "2026-04-10", "status": "extracted"}
    source = _fact(extract_facts([act]), act["document_id"], "amount", act["line_items"][0]["row_id"])

    assert source.period_start.isoformat() == "2026-04-10"
    assert source.period_end.isoformat() == "2026-04-10"


def test_planned_and_actual_values_cannot_be_combined():
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "amount_due")
    actual = replace(source, fact_id="fact_actual", economic_measure="actual")
    planned = replace(source, fact_id="fact_planned", source_path="#/fields/planned_amount", economic_measure="planned")
    plan = CalculationPlan(
        target_id="expected-total", method_description="Test mixed measure types",
        included=[PlanInclusion(fact_id=actual.fact_id, reason="actual"), PlanInclusion(fact_id=planned.fact_id, reason="planned")],
        excluded=[], steps=[PlanStep(step_id="result", operation="add", inputs=[actual.fact_id, planned.fact_id])],
        result_step_id="result", currency="RUB",
    )

    diagnostics = validate_plan(plan, make_target(economic_measure="actual"), [actual, planned], make_linking([act]))

    assert {"mixed_economic_measures", "economic_measure_mismatch"} <= {item.code for item in diagnostics}


def test_planner_batches_all_candidates_without_truncating(settings, monkeypatch):
    act = load_upstream("act-2026-0424.json")
    base = _fact(extract_facts([act]), act["document_id"], "amount_due")
    facts = [
        replace(base, fact_id=f"fact_{index:05d}", source_path=f"#/generated/{index}", key=f"amount_{index}", value=Decimal(index + 1), normalized_value={"amount": str(index + 1), "currency": "RUB"}, row_id=f"row-{index}")
        for index in range(1200)
    ]
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="test", llm_max_candidates=100))
    calls: list[dict] = []

    def review_batch(payload, sensitive_data):
        calls.append(payload)
        return CalculationPlan(
            target_id="target_001", method_description="Candidate review only",
            included=[], excluded=[PlanExclusion(fact_id=item["fact_id"], reason="Not applicable to this target") for item in payload["candidates"]],
            unprocessed_fact_ids=[], steps=[], result_step_id=None, requires_manual_review=True,
        )

    monkeypatch.setattr(planner, "_request_plan", review_batch)
    target = TargetIndicator(target_id="target", label="Expected amount", kfz_document_id="test-kfz", kfz_source_path="#/indicators/0/extracted")
    result = planner.plan(target, facts, {act["document_id"]: "opaque-source", "test-kfz": "opaque-target"}, make_linking([act]))
    reviewed_refs = [candidate["fact_id"] for call in calls for candidate in call["candidates"]]

    assert len(calls) == 12
    assert sum(len(call["candidates"]) for call in calls) == 1200
    assert len(set(reviewed_refs)) == 1200
    assert len(result.excluded) == 1200
    assert result.requires_manual_review


def test_llm_selection_without_human_confirmed_target_link_stays_unresolved(settings, monkeypatch):
    from reconciliation_engine.models import ReconciliationContext
    from reconciliation_engine.planner import LLMPlanner

    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "amount_due")
    plan = plan_for([act], [source])
    request = make_request([act], None)
    request.context = request.context.model_copy(update={"data_classification": "open", "external_llm_allowed": True})
    monkeypatch.setattr(LLMPlanner, "plan", lambda *args, **kwargs: plan)

    result = reconcile(request, Settings(llm_enabled=True, llm_api_key="test"))["calculations"][0]

    assert result["expected_value"] is None
    assert "source_applicability_unverified" in _codes(result)


def test_one_bad_target_does_not_abort_other_target_results(settings):
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "amount_due")
    plan = plan_for([act], [source])
    base = make_request([act], None)
    good_target = base.context.targets[0]
    bad_target = make_target(target_id="missing-target", kfz_document_id="absent-kfz", kfz_source_path="#/indicators/missing/extracted")
    context = base.context.model_copy(update={"targets": [bad_target, good_target]})
    unbound = base.model_copy(update={"context": context})
    decision = ConfirmedDecision(decision_id="good-decision", target_id=good_target.target_id, reviewer_id="reviewer", confirmed_at="2026-11-13T00:00:00Z", plan=plan.as_dict(), accepted_fact_ids=[], accepted_link_ids=[])
    request = unbound.model_copy(update={"prior_decisions": [bind_decision_to_request(unbound, decision, plan)]})

    result = reconcile(request, settings)

    assert result["calculations"][0]["expected_value"] is None
    assert result["calculations"][1]["expected_value"] == "1180300.00"
    assert result["calculations"][1]["status"] == "calculated"


def test_request_schema_accepts_snapshot_bound_confirmation_and_economic_measure():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/reconciliation-request-1.0.0.schema.json").read_text(encoding="utf-8"))
    act = load_upstream("act-2026-0424.json")
    source = _fact(extract_facts([act]), act["document_id"], "amount_due")
    request = make_request([act], plan_for([act], [source]))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(request.model_dump(mode="json")))

    assert not errors, [item.message for item in errors]
