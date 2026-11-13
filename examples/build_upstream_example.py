"""Rebuild the accepted Extraction-based example and its recorded output."""

import json
from datetime import datetime, timezone
from pathlib import Path

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import extract_facts, numeric_value
from reconciliation_engine.models import ConfirmedDecision, ReconciliationContext, ReconciliationRequest, TargetIndicator
from reconciliation_engine.plans import CalculationPlan, PlanExclusion, PlanInclusion, PlanStep
from reconciliation_engine.service import reconcile

ROOT = Path(__file__).resolve().parents[1]
EXTRACTION = json.loads((ROOT / "fixtures/upstream-structured-extraction-1.2.0/act-2026-0424.json").read_text(encoding="utf-8"))
KFZ = json.loads((ROOT / "fixtures/upstream-structured-extraction-1.2.0/kfz-2026-q1.json").read_text(encoding="utf-8"))
FACTS = extract_facts([EXTRACTION])
SELECTED = [fact for fact in FACTS if fact.role == "line_item" and fact.key == "amount" and fact.status == "extracted"]
assert [fact.row_id for fact in SELECTED] == [f"act-lines-r{i:03d}" for i in range(1, 6)]
KFZ_TARGET = next(fact for fact in extract_facts([KFZ]) if fact.role == "indicator" and fact.key == "reported_total")

PLAN = CalculationPlan(
    target_id="act-april-execution-total",
    method_description="Sum the five extracted amount values for the five separate service lines in the act.",
    included=[PlanInclusion(fact_id=fact.fact_id, reason="One completed service line in the act; each row has its own source locator.") for fact in SELECTED],
    excluded=[PlanExclusion(fact_id=fact.fact_id, reason="Quantity, unit price, VAT, and document totals are not additional service-line amount values.") for fact in FACTS if fact.fact_id not in {item.fact_id for item in SELECTED} and numeric_value(fact) is not None],
    steps=[PlanStep(step_id="act_total", operation="sum", inputs=[fact.fact_id for fact in SELECTED])],
    result_step_id="act_total",
    currency="RUB",
    amount_basis="unspecified",
    rounding_scale=2,
    assumptions=[],
)

TARGET = TargetIndicator(
    target_id=PLAN.target_id,
    label="Total amount across the five service lines in the April act",
    description="Contract example: the April source period does not match the referenced Q1 KФЗ indicator.",
    target_fact_id=KFZ_TARGET.fact_id,
    kfz_document_id=KFZ_TARGET.document_id,
    kfz_source_path=KFZ_TARGET.source_path,
    currency="RUB",
    amount_basis="unspecified",
    period_basis="document_period",
)
LINKING = {
    "linking_run_id": "example-contract-valid-linking-snapshot",
    "contract_version": "1.2.0",
    "created_at": "2026-11-13T10:00:00Z",
    "input_documents": [{
        "document_id": EXTRACTION["document_id"],
        "extraction_id": EXTRACTION["extraction_id"],
        "document_type": EXTRACTION["document_type"],
        "version": EXTRACTION["version"],
        "schema_version": EXTRACTION["schema_version"],
        "input_version": EXTRACTION["version"],
    }, {
        "document_id": KFZ["document_id"],
        "extraction_id": KFZ["extraction_id"],
        "document_type": KFZ["document_type"],
        "version": KFZ["version"],
        "schema_version": KFZ["schema_version"],
        "input_version": KFZ["version"],
    }],
    "links": [],
    "review_required": [],
    "unlinked_documents": [],
    "warnings": ["Example uses an empty contract-valid Link 1.2.0 snapshot because the published upstream example is legacy 1.0.0."],
    "link_validation_diagnostics": [],
    "analysis_summary": "Empty graph for the local example.",
    "processing_metadata": {
        "engine_version": "example",
        "llm": {"enabled": False, "provider": "not_called", "model": "not_called", "strategy": "full_set", "estimated_input_tokens": 0, "calls": 0, "errors": 0, "duration_ms": 0},
        "duration_ms": 0,
    },
}
REQUEST = ReconciliationRequest(
    contract_version="1.0.0",
    extraction_results=[EXTRACTION, KFZ],
    linking_result=LINKING,
    context=ReconciliationContext(period_start="2026-04-01", period_end="2026-04-06", targets=[TARGET], data_classification="open"),
    prior_decisions=[ConfirmedDecision(decision_id="example-human-decision", target_id=PLAN.target_id, reviewer_id="example-reviewer", confirmed_at=datetime(2026, 11, 13, 10, tzinfo=timezone.utc), plan=PLAN.as_dict())],
)
RESULT = reconcile(REQUEST, Settings(llm_enabled=False))
assert RESULT["calculations"][0]["expected_value"] is None
assert RESULT["calculations"][0]["status"] == "manual_review"
assert any(error["code"] == "target_period_mismatch" for error in RESULT["calculations"][0]["errors"])

(ROOT / "examples/act-reconciliation-request.json").write_text(json.dumps(REQUEST.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "examples/act-reconciliation-result.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
print("Wrote contract example; target_period_mismatch returns manual_review with expected_value=null")
