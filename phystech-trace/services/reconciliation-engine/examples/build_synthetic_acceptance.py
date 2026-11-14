"""Build a clearly synthetic, snapshot-bound acceptance example."""

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import extract_facts, numeric_value
from reconciliation_engine.models import ConfirmedDecision, ReconciliationContext, ReconciliationRequest, TargetIndicator
from reconciliation_engine.plans import CalculationPlan, PlanExclusion, PlanInclusion, PlanStep
from reconciliation_engine.service import bind_decision_to_request, reconcile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "synthetic"
AMOUNTS = ["102.00", "103.00", "105.00", "110.00", "130.00"]
PERIOD = {"start": "2026-04-01", "end": "2026-04-06"}


def _read_fixture(name: str) -> dict[str, Any]:
    path = ROOT / "fixtures" / "upstream-structured-extraction-1.2.0" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _wrapper(document_id: str, path: str, value: Any, source_text: str, **extra: Any) -> dict[str, Any]:
    return {
        "value": value,
        "source_value": source_text,
        "status": "extracted",
        "confidence": 1.0,
        "provenance": {
            "document_id": document_id,
            "source_ref": path,
            "source_text": source_text,
            "source_available": True,
        },
        "normalization_note": None,
        **extra,
    }


def _empty_wrapper() -> dict[str, Any]:
    return {"value": None, "source_value": None, "status": "missing", "confidence": None, "provenance": None, "normalization_note": None}


def _period_wrapper(document_id: str, field: str) -> dict[str, Any]:
    return _wrapper(document_id, f"#/fields/{field}", PERIOD, "Synthetic test period")


def build_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    act = copy.deepcopy(_read_fixture("act-2026-0424.json"))
    act_id, extraction_id = "synthetic-act-april", "synthetic-extraction-act-v1"
    act.update({
        "document_id": act_id,
        "extraction_id": extraction_id,
        "extracted_at": "2026-11-13T00:00:00Z",
        "classification": {"type": "act", "label": "Synthetic act", "confidence": 1.0, "status": "classified"},
        "fields": {"execution_period": _period_wrapper(act_id, "execution_period")},
        "tables": [],
        "indicators": [],
        "missing_fields": [],
        "review_required": [],
        "synthetic": True,
    })
    act.pop("input_hash", None)
    act.pop("input_version", None)
    synthetic_rows = []
    for index, amount in enumerate(AMOUNTS, start=1):
        row_id = f"synthetic-service-row-{index:02d}"
        row = {
            key: copy.deepcopy(value)
            for key, value in act["line_items"][index - 1].items()
            if isinstance(value, dict)
        }
        for key in row:
            row[key] = _empty_wrapper()
        row.update({
            "row_id": row_id,
            "description": _wrapper(act_id, f"#/line_items/{index - 1}/description", f"Synthetic service {index}", f"Synthetic service {index}"),
            "amount": _wrapper(
                act_id,
                f"#/line_items/{index - 1}/amount",
                {"amount": amount, "currency": "RUB"},
                amount,
                economic_measure="actual",
            ),
            "source_cells": [],
            "row_status": "extracted",
        })
        synthetic_rows.append(row)
    act["line_items"] = synthetic_rows

    kfz = copy.deepcopy(_read_fixture("kfz-2026-q1.json"))
    kfz_id, kfz_extraction_id = "synthetic-kfz-report", "synthetic-extraction-kfz-v1"
    target_value = sum((Decimal(value) for value in AMOUNTS), Decimal(0))
    target_amount = f"{target_value:.2f}"
    kfz.update({
        "document_id": kfz_id,
        "extraction_id": kfz_extraction_id,
        "extracted_at": "2026-11-13T00:00:00Z",
        "classification": {"type": "kfz_report", "label": "Synthetic KФЗ report", "confidence": 1.0, "status": "classified"},
        "fields": {},
        "tables": [],
        "line_items": [],
        "missing_fields": [],
        "review_required": [],
        "indicators": [
            {
                "key": "reported_total",
                "label": "Synthetic reported total",
                "extracted": _wrapper(
                    kfz_id,
                    "#/indicators/0/extracted",
                    {"amount": target_amount, "currency": "RUB"},
                    target_amount,
                ),
            },
            {
                "key": "reporting_period",
                "label": "Synthetic reporting period",
                "extracted": _wrapper(kfz_id, "#/indicators/1/extracted", PERIOD, "Synthetic test period"),
            },
        ],
        "synthetic": True,
    })
    kfz.pop("input_hash", None)
    kfz.pop("input_version", None)
    return act, kfz


def main() -> None:
    act, kfz = build_inputs()
    extractions = [act, kfz]
    facts = extract_facts(extractions)
    selected = [fact for fact in facts if fact.document_id == act["document_id"] and fact.key == "amount"]
    target_fact = next(fact for fact in facts if fact.document_id == kfz["document_id"] and fact.key == "reported_total")
    assert len(selected) == len(AMOUNTS)
    plan = CalculationPlan(
        target_id="synthetic-april-total",
        method_description="Sum the five independently generated synthetic service-line values.",
        included=[PlanInclusion(fact_id=fact.fact_id, reason="Synthetic source amount for a distinct test operation row.") for fact in selected],
        excluded=[PlanExclusion(fact_id=fact.fact_id, reason="Not a source amount for the requested synthetic total.") for fact in facts if fact.fact_id not in {item.fact_id for item in selected} and numeric_value(fact) is not None],
        steps=[PlanStep(step_id="synthetic_sum", operation="sum", inputs=[fact.fact_id for fact in selected])],
        result_step_id="synthetic_sum",
        currency="RUB",
        rounding_scale=2,
        assumptions=[],
    )
    target = TargetIndicator(
        target_id=plan.target_id,
        target_fact_id=target_fact.fact_id,
        kfz_document_id=kfz["document_id"],
        kfz_source_path=target_fact.source_path,
        label="Synthetic April operation total",
        description="Test-only indicator; the inputs are generated synthetic records.",
        currency="RUB",
        economic_measure="actual",
        period_basis="document_period",
    )
    linking = {
        "linking_run_id": "synthetic-linking-snapshot-v1",
        "contract_version": "1.2.0",
        "created_at": "2026-11-13T00:00:00Z",
        "input_documents": [
            {key: document[key] for key in ("document_id", "extraction_id", "document_type", "version", "schema_version")} | {"input_version": document["version"]}
            for document in extractions
        ],
        "links": [],
        "review_required": [],
        "unlinked_documents": [],
        "warnings": ["Synthetic test graph; no real upstream relationship evidence."],
        "link_validation_diagnostics": [],
        "analysis_summary": "Synthetic empty graph; human-reviewed calculation plan is bound to this exact snapshot.",
        "processing_metadata": {"engine_version": "synthetic-test", "llm": {"enabled": False, "provider": "not_called", "model": "not_called", "strategy": "full_set", "estimated_input_tokens": 0, "calls": 0, "errors": 0, "duration_ms": 0}, "duration_ms": 0},
    }
    request = ReconciliationRequest(
        contract_version="1.0.0",
        extraction_results=extractions,
        linking_result=linking,
        context=ReconciliationContext(
            period_start=PERIOD["start"], period_end=PERIOD["end"], targets=[target],
            data_classification="open", external_llm_allowed=False,
        ),
    )
    decision = ConfirmedDecision(
        decision_id="synthetic-review-decision-v1",
        target_id=target.target_id,
        reviewer_id="synthetic-acceptance-runner",
        confirmed_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        plan=plan.as_dict(),
    )
    request = request.model_copy(update={"prior_decisions": [bind_decision_to_request(request, decision, plan)]})
    result = reconcile(request, Settings(llm_enabled=False))
    calculation = result["calculations"][0]
    expected = f"{sum((Decimal(value) for value in AMOUNTS), Decimal(0)):.2f}"
    if calculation["status"] != "calculated" or calculation["expected_value"] != expected:
        raise RuntimeError(f"Synthetic acceptance scenario failed: {calculation['diagnostics']}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = {
        "acceptance-request.json": request.model_dump(mode="json"),
        "acceptance-plan.json": plan.as_dict(),
        "acceptance-result.json": result,
        "golden-reference.json": {
            "synthetic": True,
            "formula": " + ".join(AMOUNTS),
            "source_amounts_rub": AMOUNTS,
            "expected_value": expected,
            "target_value_is_not_used_as_a_source": True,
            "upstream_success_claim": False,
        },
    }
    for name, data in files.items():
        (OUTPUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote synthetic acceptance artifacts; status={calculation['status']}; expected_value={expected} RUB")


if __name__ == "__main__":
    main()
