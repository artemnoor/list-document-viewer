import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "live_e2e"))

from prepare_cases import build_cases
from run_live_evaluation import REQUESTED_MODEL_ID, _formula_matches, _runtime_settings, _source_metrics, _validate_response_models

from reconciliation_engine.contracts import validate_upstream_inputs
from reconciliation_engine.engine import execute_plan, validate_plan
from reconciliation_engine.facts import extract_facts, numeric_value
from reconciliation_engine.models import ReconciliationRequest
from reconciliation_engine.plans import CalculationPlan, PlanInclusion, PlanStep


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


def test_live_evaluation_is_pinned_to_the_requested_gemma_model(monkeypatch):
    monkeypatch.setenv("POLZA_AI_API_KEY", "unit-test-placeholder")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-6.1-sol")

    assert REQUESTED_MODEL_ID == "google/gemma-4-26b-a4b-it"
    with pytest.raises(RuntimeError, match="pinned to google/gemma-4-26b-a4b-it"):
        _runtime_settings()


def test_live_evaluation_rejects_unverified_or_different_response_model():
    with pytest.raises(RuntimeError, match="Provider returned model 'google/other-model'"):
        _validate_response_models([{"assistant_content": "{}", "model_returned": "google/other-model"}])

    with pytest.raises(RuntimeError, match="Provider returned model None"):
        _validate_response_models([{"assistant_content": "{}", "model_returned": None}])

    _validate_response_models([{"assistant_content": "{}", "model_returned": REQUESTED_MODEL_ID}])


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


def test_source_identification_counts_candidates_the_model_explicitly_left_unprocessed():
    reference = {"expected_source_groups": [["act-north"], ["act-south"]]}
    plan = {"included": [], "unprocessed_fact_ids": ["act-north", "act-south"]}

    metrics = _source_metrics(plan, reference)

    assert metrics["source_selection_correct"] is False
    assert metrics["source_identification_correct"] is True
    assert metrics["source_identification_precision"] == 1.0
    assert metrics["source_identification_recall"] == 1.0
