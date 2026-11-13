import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from reconciliation_engine.config import Settings
from reconciliation_engine.models import ReconciliationRequest
from reconciliation_engine.service import reconcile

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "examples" / "synthetic"


def _load(name: str):
    return json.loads((SYNTHETIC / name).read_text(encoding="utf-8"))


def test_synthetic_acceptance_artifacts_reconcile_and_match_golden_reference():
    request_data = _load("acceptance-request.json")
    saved_result = _load("acceptance-result.json")
    golden = _load("golden-reference.json")
    result_schema = json.loads((ROOT / "schemas" / "reconciliation-result-1.0.0.schema.json").read_text(encoding="utf-8"))

    assert all(item.get("synthetic") is True for item in request_data["extraction_results"])
    assert golden["synthetic"] is True
    assert golden["upstream_success_claim"] is False
    assert saved_result["calculations"][0]["status"] == "calculated"
    assert saved_result["calculations"][0]["expected_value"] == golden["expected_value"]
    errors = list(Draft202012Validator(result_schema, format_checker=FormatChecker()).iter_errors(saved_result))
    assert not errors, [item.message for item in errors]

    request = ReconciliationRequest.model_validate(request_data)
    current = reconcile(request, Settings(llm_enabled=False))
    calculation = current["calculations"][0]
    assert calculation["status"] == "calculated"
    assert calculation["expected_value"] == golden["expected_value"]
    assert len(calculation["used_sources"]) == len(golden["source_amounts_rub"])
    assert sum(float(source["numeric_value"]) for source in calculation["used_sources"]) == float(golden["expected_value"])
    assert all(source["document_id"] != calculation["target"]["kfz_origin"]["document_id"] for source in calculation["used_sources"])
    source_documents = {item["document_id"]: item for item in request_data["extraction_results"]}
    for source in calculation["used_sources"]:
        document = source_documents[source["document_id"]]
        row = next(item for item in document["line_items"] if item["row_id"] == source["row_id"])
        assert source["extraction_id"] == document["extraction_id"]
        assert source["input_hash"]
        assert source["provenance"]["document_id"] == document["document_id"]
        assert row["amount"]["value"]["amount"] == source["numeric_value"]


def test_synthetic_plan_is_saved_separately_and_uses_only_source_facts():
    request = _load("acceptance-request.json")
    plan = _load("acceptance-plan.json")
    confirmed = request["prior_decisions"][0]["plan"]
    assert plan == confirmed
    assert plan["included"]
    assert all("fact_id" in item for item in plan["included"])
    assert plan["result_step_id"] == "synthetic_sum"
