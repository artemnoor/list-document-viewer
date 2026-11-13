import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import Fact, extract_facts, numeric_value
from reconciliation_engine.models import ConfirmedDecision, ReconciliationContext, ReconciliationRequest, TargetIndicator
from reconciliation_engine.plans import CalculationPlan, PlanExclusion, PlanInclusion, PlanStep

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_FIXTURES = ROOT / "fixtures" / "upstream-structured-extraction-1.2.0"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(result_store_dir=str(tmp_path / "results"), llm_enabled=False)


def load_upstream(name: str) -> dict[str, Any]:
    return json.loads((UPSTREAM_FIXTURES / name).read_text(encoding="utf-8"))


def clone_extraction(source: dict[str, Any], document_id: str) -> dict[str, Any]:
    result = copy.deepcopy(source)
    old_document_id = result["document_id"]
    old_extraction_id = result["extraction_id"]

    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            rewritten = {}
            for key, item in value.items():
                if key == "document_id" and item == old_document_id:
                    rewritten[key] = document_id
                elif key == "extraction_id" and item == old_extraction_id:
                    rewritten[key] = f"ext-{document_id}-v1"
                elif key == "row_id" and isinstance(item, str):
                    rewritten[key] = item.replace(old_document_id, document_id).replace("act-lines", f"{document_id}-lines")
                else:
                    rewritten[key] = rewrite(item)
            return rewritten
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str) and value == old_document_id:
            return document_id
        if isinstance(value, str) and value == old_extraction_id:
            return f"ext-{document_id}-v1"
        return value

    result = rewrite(result)
    result["document_id"] = document_id
    result["extraction_id"] = f"ext-{document_id}-v1"
    return result


def set_amount(extraction: dict[str, Any], row_index: int, amount: str | None, currency: str | None = "RUB", status: str = "extracted") -> None:
    wrapper = extraction["line_items"][row_index]["amount"]
    wrapper["value"] = {"amount": amount, "currency": currency} if amount is not None else None
    wrapper["source_value"] = amount
    wrapper["status"] = status if amount is not None else "missing"
    wrapper["confidence"] = 1 if amount is not None else None
    wrapper["normalization_note"] = None
    if wrapper.get("provenance"):
        wrapper["provenance"]["source_text"] = amount or ""


def _link_input(extraction: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": extraction["document_id"],
        "extraction_id": extraction["extraction_id"],
        "document_type": extraction["document_type"],
        "version": extraction["version"],
        "schema_version": extraction["schema_version"],
        "input_version": extraction["version"],
        "input_hash": "a" * 64,
    }


def make_linking(extractions: list[dict[str, Any]], links: list[dict[str, Any]] | None = None, review: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "linking_run_id": "test-linking-run",
        "contract_version": "1.2.0",
        "created_at": "2026-11-13T00:00:00Z",
        "input_documents": [_link_input(item) for item in extractions],
        "links": links or [],
        "review_required": review or [],
        "unlinked_documents": [],
        "warnings": [],
        "link_validation_diagnostics": [],
        "analysis_summary": "Contract-valid test graph.",
        "processing_metadata": {
            "engine_version": "test",
            "llm": {
                "enabled": False,
                "provider": "not_called",
                "model": "not_called",
                "strategy": "full_set",
                "estimated_input_tokens": 0,
                "calls": 0,
                "errors": 0,
                "duration_ms": 0,
            },
            "duration_ms": 0,
        },
    }


def correspondence_link(left: dict[str, Any], left_row: str, right: dict[str, Any], right_row: str, status: str = "review") -> dict[str, Any]:
    def endpoint(doc: dict[str, Any], row: str) -> dict[str, Any]:
        return {"document_id": doc["document_id"], "path": f"line_items[{row}].amount", "raw_value": "100", "normalized_value": "100", "provenance": {"document_id": doc["document_id"], "source_text": "100", "row_id": row}}

    return {
        "link_id": "test-correspondence",
        "relationship_type": "line_item_correspondence",
        "source_document_id": left["document_id"],
        "target_document_id": right["document_id"],
        "source_row_id": left_row,
        "target_row_id": right_row,
        "evidence": [{"source": endpoint(left, left_row), "target": endpoint(right, right_row), "signal": "test", "explanation": "Synthetic contract-valid relationship."}],
        "explanation": "Rows are candidate correspondences.",
        "confidence": 0.9,
        "status": status,
        "verification_status": "not_reviewed",
        "detection_method": "llm",
        "conflicts": [],
    }


def make_target(
    target_id: str = "expected-total",
    *,
    currency: str | None = "RUB",
    unit: str | None = None,
    amount_basis: str = "unspecified",
    period_basis: str = "none",
    required_document_types: list[str] | None = None,
    target_fact_id: str | None = None,
    kfz_document_id: str = "test-kfz",
    kfz_source_path: str = "#/indicators/0/extracted",
    kfz_row_id: str | None = None,
) -> TargetIndicator:
    return TargetIndicator(
        target_id=target_id,
        target_fact_id=target_fact_id,
        kfz_document_id=kfz_document_id,
        kfz_source_path=kfz_source_path,
        kfz_row_id=kfz_row_id,
        label="Expected total",
        description="Test target",
        unit=unit,
        currency=currency,
        amount_basis=amount_basis,
        period_basis=period_basis,
        required_document_types=required_document_types or [],
    )


def plan_for(extractions: list[dict[str, Any]], selected: list[Fact], target_id: str = "expected-total", *, operation: str = "sum", steps: list[PlanStep] | None = None, amount_basis: str = "unspecified", requires_manual_review: bool = False, information_gaps: list[str] | None = None, exclusions: list[PlanExclusion] | None = None) -> CalculationPlan:
    facts = extract_facts(extractions)
    selected_ids = {fact.fact_id for fact in selected}
    if exclusions is None:
        exclusions = [PlanExclusion(fact_id=fact.fact_id, reason="Not part of the selected operation set.") for fact in facts if fact.fact_id not in selected_ids and numeric_value(fact) is not None]
    if steps is None:
        steps = [PlanStep(step_id="result", operation=operation, inputs=[fact.fact_id for fact in selected])]
    return CalculationPlan(
        target_id=target_id,
        method_description="Sum explicitly selected independent extracted amounts.",
        included=[PlanInclusion(fact_id=fact.fact_id, reason="Amount belongs to the requested operation set.") for fact in selected],
        excluded=exclusions,
        steps=steps,
        result_step_id=steps[-1].step_id,
        currency="RUB",
        amount_basis=amount_basis,
        assumptions=[],
        information_gaps=information_gaps or [],
        requires_manual_review=requires_manual_review,
    )


def make_request(extractions: list[dict[str, Any]], plan: CalculationPlan | None, target: TargetIndicator | None = None, *, period_start: str | None = None, period_end: str | None = None, links: list[dict[str, Any]] | None = None, review: list[dict[str, Any]] | None = None, accepted_fact_ids: list[str] | None = None, accepted_link_ids: list[str] | None = None) -> ReconciliationRequest:
    target = target or make_target()
    facts = extract_facts(extractions)
    target_fact = next((fact for fact in facts if fact.fact_id == target.target_fact_id), None)
    if target_fact is None and target.kfz_row_id is not None:
        target_fact = next((fact for fact in facts if fact.document_id == target.kfz_document_id and fact.row_id == target.kfz_row_id), None)
    if target_fact is None:
        target_fact = next((fact for fact in facts if fact.document_id == target.kfz_document_id and fact.source_path == target.kfz_source_path), None)
    if target_fact is None and facts:
        target_fact = next((fact for fact in facts if fact.role == "indicator" and fact.key == "amount_due"), facts[0])
    if target_fact is not None:
        target = target.model_copy(update={
            "target_fact_id": target_fact.fact_id,
            "kfz_document_id": target_fact.document_id,
            "kfz_source_path": target_fact.source_path,
            "kfz_row_id": target_fact.row_id,
        })
    decisions = []
    if plan is not None:
        decisions = [ConfirmedDecision(decision_id="decision-1", target_id=target.target_id, reviewer_id="test-reviewer", confirmed_at=datetime(2026, 11, 13, tzinfo=timezone.utc), plan=plan.as_dict(), accepted_fact_ids=accepted_fact_ids or [], accepted_link_ids=accepted_link_ids or [])]
    return ReconciliationRequest(
        contract_version="1.0.0",
        extraction_results=extractions,
        linking_result=make_linking(extractions, links=links, review=review),
        context=ReconciliationContext(period_start=period_start, period_end=period_end, targets=[target]),
        prior_decisions=decisions,
    )

