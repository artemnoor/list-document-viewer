import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import httpx
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "live_e2e"))

from prepare_cases import build_cases
from replay_saved_results import _validate_recorded_model_identity
from run_live_evaluation import REQUESTED_MODEL_ID, _aggregate, _formula_matches, _runtime_settings, _source_metrics, _validate_response_models

from reconciliation_engine.contracts import validate_upstream_inputs
from reconciliation_engine.config import Settings
from reconciliation_engine.engine import execute_plan, validate_plan
from reconciliation_engine.facts import extract_facts, numeric_value
from reconciliation_engine.models import ReconciliationRequest
from reconciliation_engine.plans import CalculationPlan, PlanExclusion, PlanInclusion, PlanStep
from reconciliation_engine.planner import IncompatibleChunkPlans, LLMPlanner, PROMPT_PATH, PlannerUnavailable, _dimension_mismatch, _validated_plan
from reconciliation_engine.service import reconcile


def test_live_e2e_cases_are_synthetic_contract_valid_and_have_independent_references():
    schema = json.loads((ROOT / "schemas" / "reconciliation-request-1.0.0.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    cases = build_cases()

    assert len(cases) == 10
    for case in cases:
        request = case["request"]
        reference = case["reference"]
        assert all(document.get("synthetic") is True for document in request["extraction_results"])
        assert reference["truth_source"] == "deterministic synthetic input specification; independent of all LLM outputs"
        errors = list(validator.iter_errors(request))
        assert not errors, [item.message for item in errors]
        validate_upstream_inputs(request["extraction_results"], request["linking_result"])
        valid_source_ids = {fact.fact_id for fact in extract_facts(request["extraction_results"]) if fact.document_type != "kfz_report"}
        assert all(fact_id in valid_source_ids for group in reference["expected_source_groups"] for fact_id in group)

    many = next(case for case in cases if case["reference"]["case_id"] == "10_hundreds_of_candidates")
    assert many["metadata"]["candidate_count"] == 320
    facts = extract_facts(many["request"]["extraction_results"])
    target_fact_id = many["reference"]["expected_source_groups"][0][0]
    target_index = next(index for index, fact in enumerate(facts) if fact.fact_id == target_fact_id and fact.document_type != "kfz_report")
    assert target_index >= 300
    assert "308" not in many["request"]["context"]["targets"][0]["description"]
    links = many["request"]["linking_result"]["links"]
    assert any(link["verification_status"] == "human_confirmed" for link in links)
    assert any(link["verification_status"] == "not_reviewed" for link in links)


def test_later_candidate_batch_is_sent_after_an_earlier_timeout(monkeypatch):
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "10_hundreds_of_candidates")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    facts = extract_facts(request.extraction_results)
    source_groups = {fact.document_id: fact.document_id for fact in facts}
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="unit-test", llm_max_candidates=300))
    calls = []
    target_alias = None

    def review_batch(payload, sensitive_data):
        nonlocal target_alias
        calls.append(payload)
        batch_index = payload["candidate_batch"]["index"]
        matching = [
            item for item in payload["candidates"]
            if item.get("operation_description") == "Foundation support bracket ZX-14 inspection"
        ]
        if batch_index == 1:
            assert not matching
            raise httpx.ReadTimeout("synthetic first-batch timeout")

        assert batch_index == 2
        assert len(matching) == 1
        target_alias = matching[0]["fact_id"]
        other_ids = [item["fact_id"] for item in payload["candidates"] if item["fact_id"] != target_alias]
        return CalculationPlan(
            target_id="target_001",
            method_description="Select the matching operation description.",
            included=[PlanInclusion(fact_id=target_alias, reason="Matches the target operation.")],
            excluded=[PlanExclusion(fact_id=fact_id, reason="Does not match the target operation.") for fact_id in other_ids],
            steps=[PlanStep(step_id="total", operation="sum", inputs=[target_alias])],
            result_step_id="total",
            currency="RUB",
            amount_basis="unspecified",
        )

    monkeypatch.setattr(planner, "_request_plan", review_batch)
    result = planner.plan(target, facts, source_groups, request.linking_result)

    assert [call["candidate_batch"]["index"] for call in calls] == [1, 2]
    assert target_alias is not None
    assert target_alias not in {item["fact_id"] for item in calls[0]["candidates"]}
    assert target_alias in {item["fact_id"] for item in calls[1]["candidates"]}
    assert result.included[0].fact_id == case["reference"]["expected_source_groups"][0][0]
    assert len(result.unprocessed_fact_ids) == 300
    assert result.requires_manual_review


def test_all_failed_candidate_batches_leave_every_candidate_unprocessed(monkeypatch):
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "10_hundreds_of_candidates")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    facts = extract_facts(request.extraction_results)
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="unit-test", llm_max_candidates=300))
    batch_indices = []

    def fail_batch(payload, sensitive_data):
        batch_indices.append(payload["candidate_batch"]["index"])
        raise PlannerUnavailable("synthetic provider failure")

    monkeypatch.setattr(planner, "_request_plan", fail_batch)
    result = planner.plan(target, facts, {}, request.linking_result)

    assert batch_indices == [1, 2]
    assert not result.included
    assert len(result.unprocessed_fact_ids) == 320
    assert result.currency == target.currency
    assert result.requires_manual_review


def test_unreviewed_link_for_another_row_does_not_block_confirmed_selected_row(monkeypatch):
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "08_actual_vs_planned")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    facts = extract_facts(request.extraction_results)
    selected_fact_id = case["reference"]["expected_source_groups"][0][0]
    candidates = [fact for fact in facts if fact.document_type != "kfz_report" and fact.document_id != target.kfz_document_id and numeric_value(fact) is not None]
    plan = CalculationPlan(
        target_id=target.target_id,
        method_description="Use the actual completed amount.",
        included=[PlanInclusion(fact_id=selected_fact_id, reason="This is the actual completed operation.")],
        excluded=[PlanExclusion(fact_id=fact.fact_id, reason="This fact is not the actual completed operation.") for fact in candidates if fact.fact_id != selected_fact_id],
        steps=[PlanStep(step_id="total", operation="sum", inputs=[selected_fact_id])],
        result_step_id="total",
        currency="RUB",
        amount_basis="unspecified",
    )
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="unit-test"))
    monkeypatch.setattr(planner, "plan", lambda *args, **kwargs: plan)

    calculation = reconcile(request, planner.settings, planner)["calculations"][0]

    assert calculation["status"] == "calculated"
    assert calculation["expected_value"] == "900.00"
    assert "link_marked_review_required" not in {item["code"] for item in calculation["diagnostics"]}


def test_live_evaluation_is_pinned_to_the_requested_gemma_model(monkeypatch):
    monkeypatch.setenv("POLZA_AI_API_KEY", "unit-test-placeholder")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-6.1-sol")

    assert REQUESTED_MODEL_ID == "google/gemma-4-26b-a4b-it"
    with pytest.raises(RuntimeError, match="pinned to google/gemma-4-26b-a4b-it"):
        _runtime_settings()


def test_current_planner_prompt_has_general_evidence_and_formula_integrity_rules():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "Prompt version: 1.0.3" in prompt
    assert "relationship for another" in prompt
    assert "Every included fact must appear exactly once" in prompt
    assert "Preserve each candidate's signed amount" in prompt


def test_live_evaluation_rejects_unverified_or_different_response_model():
    with pytest.raises(RuntimeError, match="Provider returned model 'google/other-model'"):
        _validate_response_models([{"assistant_content": "{}", "model_returned": "google/other-model"}])

    with pytest.raises(RuntimeError, match="Provider returned model None"):
        _validate_response_models([{"assistant_content": "{}", "model_returned": None}])

    _validate_response_models([{"assistant_content": "{}", "model_returned": REQUESTED_MODEL_ID}])


def test_offline_replay_accepts_pinned_provider_failures_without_a_model_response():
    _validate_recorded_model_identity({
        "model_requested": REQUESTED_MODEL_ID,
        "model_returned": None,
        "llm_calls": [{"model_requested": REQUESTED_MODEL_ID, "assistant_content": None, "http_status": 402}],
    }, "case", 1)


def test_offline_replay_rejects_a_response_from_a_different_model():
    with pytest.raises(RuntimeError, match="Refusing to replay a response"):
        _validate_recorded_model_identity({
            "model_requested": REQUESTED_MODEL_ID,
            "model_returned": "google/other-model",
            "llm_calls": [{"model_requested": REQUESTED_MODEL_ID, "model_returned": "google/other-model", "assistant_content": "{}"}],
        }, "case", 1)


def test_live_metrics_tolerate_timeouts_without_http_status():
    aggregate = _aggregate("case", [{"repeat": 1, "comparison": {}, "llm_calls": [{"http_status": None, "error_type": "ReadTimeout"}]}])
    assert aggregate["provider_error_calls"] == 0
    assert aggregate["llm_calls"] == 1


def test_planner_discards_exact_echo_of_request_metadata_but_rejects_altered_metadata():
    request = {"candidate_batch": {"index": 1, "total_batches": 2}}
    response = {"target_id": "target", "method_description": "review", "candidate_batch": request["candidate_batch"]}
    plan = _validated_plan(json.dumps(response), request)
    assert plan.target_id == "target"

    response["candidate_batch"] = {"index": 2, "total_batches": 2}
    with pytest.raises(ValueError):
        _validated_plan(json.dumps(response), request)


def test_duplicate_representation_metrics_allow_one_source_but_count_double_inclusion():
    reference = {"expected_source_groups": [["act-fact", "invoice-fact", "registry-fact"]]}

    one = _source_metrics({"included": [{"fact_id": "invoice-fact"}]}, reference)
    two = _source_metrics({"included": [{"fact_id": "act-fact"}, {"fact_id": "registry-fact"}]}, reference)

    assert (one["precision"], one["recall"], one["f1"], one["false_duplicate_inclusions"]) == (1.0, 1.0, 1.0, 0)
    assert two["false_duplicate_inclusions"] == 1


def test_explicit_same_document_gross_minus_vat_is_a_valid_net_conversion():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "06_vat_net")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    facts = extract_facts(request.extraction_results)
    gross = next(item for item in facts if item.key == "gross_total")
    vat = next(item for item in facts if item.key == "vat_amount")
    plan = CalculationPlan(
        target_id=target.target_id,
        method_description="Subtract explicitly identified VAT from the same-document gross amount.",
        included=[
            PlanInclusion(fact_id=gross.fact_id, reason="Gross amount."),
            PlanInclusion(fact_id=vat.fact_id, reason="VAT component included in gross amount."),
        ],
        steps=[
            PlanStep(step_id="net", operation="subtract", inputs=[gross.fact_id, vat.fact_id]),
            PlanStep(step_id="rounded", operation="round", inputs=["net"], scale=2),
        ],
        result_step_id="rounded",
        currency="RUB",
        amount_basis="net",
        rounding_scale=2,
    )

    diagnostics = validate_plan(plan, target, facts, request.linking_result, request.context.period_start, request.context.period_end)
    result, _ = execute_plan(plan, facts)

    assert not {item.code for item in diagnostics} & {"amount_basis_mismatch", "amount_basis_unknown"}
    assert result == Decimal("100.00")


def test_review_only_plan_may_leave_candidates_unprocessed_without_exclusion_reasons():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "02_independent_acts")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    facts = extract_facts(request.extraction_results)
    candidate_ids = [
        fact.fact_id for fact in facts
        if fact.document_type != "kfz_report"
        and fact.document_id != target.kfz_document_id
        and numeric_value(fact) is not None
    ]
    plan = CalculationPlan(
        target_id=target.target_id,
        method_description="The available evidence does not establish whether the source documents are independent.",
        unprocessed_fact_ids=candidate_ids,
        requires_manual_review=True,
        information_gaps=["Confirm that the two operations are independent before adding them."],
    )

    codes = {item.code for item in validate_plan(plan, target, facts, request.linking_result, request.context.period_start, request.context.period_end)}

    assert "missing_result_step" not in codes
    assert "excluded_source_reason_missing" not in codes


def test_formula_metric_accepts_target_rounding_around_a_single_source_sum():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "01_single_act")
    fact_id = case["reference"]["expected_source_groups"][0][0]
    plan = {
        "included": [{"fact_id": fact_id}],
        "steps": [{"step_id": "rounded", "operation": "round", "inputs": [fact_id], "scale": 2}],
        "result_step_id": "rounded",
        "rounding_scale": 2,
    }

    assert _formula_matches(plan, case["reference"])


def test_formula_metric_treats_add_as_equivalent_to_expected_sum():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "04_negative_adjustment")
    fact_ids = [fact_id for group in case["reference"]["expected_source_groups"] for fact_id in group]
    plan = {
        "included": [{"fact_id": fact_id} for fact_id in fact_ids],
        "steps": [{"step_id": "total", "operation": "add", "inputs": fact_ids}],
        "result_step_id": "total",
    }

    assert case["reference"]["expected_formula"]["operation"] == "sum"
    assert _formula_matches(plan, case["reference"])


def test_formula_metric_rejects_malformed_tree_even_when_leaf_count_matches():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "01_single_act")
    fact_id = case["reference"]["expected_source_groups"][0][0]
    plan = {"included": [{"fact_id": fact_id}], "steps": [
        {"step_id": "bad", "operation": "sum", "inputs": [fact_id], "unexpected": True}],
        "result_step_id": "bad", "rounding_scale": 2}
    assert not _formula_matches(plan, case["reference"])


@pytest.mark.parametrize("field, first, second", [
    ("currency", "RUB", "USD"), ("unit", "kg", "piece"), ("amount_basis", "gross", "net")])
def test_chunk_merge_rejects_incompatible_measurement_metadata(field, first, second):
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "01_single_act")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    baseline = CalculationPlan(target_id=target.target_id, method_description="test", **{field: first})
    incompatible = baseline.model_copy(update={field: second})
    with pytest.raises(IncompatibleChunkPlans, match="incompatible currency, unit, or amount basis"):
        LLMPlanner._merge_chunk_plans(target, [(0, baseline), (1, incompatible)], 320)


def test_chunk_merge_checks_included_fact_dimensions_not_only_plan_labels():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "01_single_act")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    real_act = json.loads((ROOT / "fixtures" / "upstream-structured-extraction-1.2.0" / "act-2026-0424.json").read_text(encoding="utf-8"))
    facts = extract_facts([real_act])
    amount = next(f for f in facts if f.key == "amount" and f.currency == "RUB")
    quantity = next(f for f in facts if f.key == "quantity" and f.unit)
    base = CalculationPlan(
        target_id=target.target_id, method_description="chunk", included=[PlanInclusion(fact_id=amount.fact_id, reason="amount")],
        steps=[PlanStep(step_id="sum_amount", operation="sum", inputs=[amount.fact_id])], result_step_id="sum_amount")
    other = CalculationPlan(
        target_id=target.target_id, method_description="chunk", included=[PlanInclusion(fact_id=quantity.fact_id, reason="quantity")],
        steps=[PlanStep(step_id="sum_quantity", operation="sum", inputs=[quantity.fact_id])], result_step_id="sum_quantity")
    with pytest.raises(IncompatibleChunkPlans, match="select facts with incompatible currency, unit, or amount basis"):
        LLMPlanner._merge_chunk_plans(target, [(0, base), (1, other)], 2, [amount, quantity])


def test_explicitly_incompatible_fact_dimensions_are_filtered_without_key_rules():
    case = next(item for item in build_cases() if item["reference"]["case_id"] == "01_single_act")
    request = ReconciliationRequest.model_validate(case["request"])
    target = request.context.targets[0]
    act = json.loads((ROOT / "fixtures" / "upstream-structured-extraction-1.2.0" / "act-2026-0424.json").read_text(encoding="utf-8"))
    facts = extract_facts([act])
    monetary_fact = next(f for f in facts if f.currency == target.currency and f.unit is None)
    dimensional_fact = next(f for f in facts if f.unit is not None)

    assert _dimension_mismatch(monetary_fact, target) == []
    assert _dimension_mismatch(dimensional_fact, target)
    unknown_dimension_target = target.model_copy(update={"currency": None, "unit": None})
    assert _dimension_mismatch(dimensional_fact, unknown_dimension_target) == []


def test_planner_does_not_send_explicitly_incompatible_candidates_to_llm(monkeypatch):
    request = ReconciliationRequest.model_validate(json.loads((ROOT / "examples" / "act-reconciliation-request.json").read_text(encoding="utf-8")))
    facts = extract_facts(request.extraction_results)
    target = request.context.targets[0]
    source_groups = {fact.document_id: f"source_{index}" for index, fact in enumerate(facts)}
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="unit-test"))
    sent_candidate_ids = []

    def review_compatible_candidates(payload, sensitive_data):
        sent_candidate_ids.extend(item["fact_id"] for item in payload["candidates"])
        return CalculationPlan(
            target_id="target_001",
            method_description="Review compatible candidates.",
            excluded=[PlanExclusion(fact_id=item["fact_id"], reason="Not selected in this deterministic test.") for item in payload["candidates"]],
        )

    monkeypatch.setattr(planner, "_request_plan", review_compatible_candidates)
    result = planner.plan(target, facts, source_groups, request.linking_result)
    incompatible_ids = {fact.fact_id for fact in facts if fact.document_type != "kfz_report" and fact.document_id != target.kfz_document_id and numeric_value(fact) is not None and _dimension_mismatch(fact, target)}
    sent_ids = {fact.fact_id for fact in facts if fact.fact_id not in incompatible_ids and fact.document_type != "kfz_report" and numeric_value(fact) is not None}

    assert len(sent_candidate_ids) == len(sent_ids)
    assert {item.fact_id for item in result.excluded} >= incompatible_ids
    assert not incompatible_ids.intersection({item.fact_id for item in result.included})


def test_source_identification_counts_candidates_the_model_explicitly_left_unprocessed():
    reference = {"expected_source_groups": [["act-north"], ["act-south"]]}
    plan = {"included": [], "unprocessed_fact_ids": ["act-north", "act-south"]}

    metrics = _source_metrics(plan, reference)

    assert metrics["source_selection_correct"] is False
    assert metrics["source_identification_correct"] is True
    assert metrics["source_identification_precision"] == 1.0
    assert metrics["source_identification_recall"] == 1.0
