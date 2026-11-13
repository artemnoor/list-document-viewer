"""Prepare deterministic synthetic live-LLM scenarios and independent references."""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reconciliation_engine.facts import Fact, extract_facts
from reconciliation_engine.models import ReconciliationContext, ReconciliationRequest, TargetIndicator
from reconciliation_engine.service import input_snapshot_identity

FIXTURES = ROOT / "fixtures" / "upstream-structured-extraction-1.2.0"
RESULTS = ROOT / "tests" / "results" / "live_e2e"
PERIOD = {"start": "2026-04-01", "end": "2026-04-30"}
CREATED_AT = "2026-11-13T00:00:00Z"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _wrapper(doc_id: str, path: str, value: Any, text: str, *, label: str, measure: str | None = None, basis: str | None = None) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "source_value": text,
        "status": "extracted",
        "confidence": 1.0,
        "provenance": {"document_id": doc_id, "source_ref": path, "source_text": text, "source_available": True},
        "normalization_note": None,
        **({"economic_measure": measure} if measure else {}),
        **({"amount_basis": basis} if basis else {}),
    }


def _missing() -> dict[str, Any]:
    return {"value": None, "source_value": None, "status": "missing", "confidence": None, "provenance": None, "normalization_note": None}


def _document(template: dict[str, Any], doc_id: str, rows: list[dict[str, Any]], period: dict[str, str], source_fields: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    doc = copy.deepcopy(template)
    ext_id = f"live-synthetic-extraction-{doc_id}-v1"
    execution_period = _wrapper(doc_id, "#/fields/execution_period", period, "Synthetic operation period", label="Synthetic operation period")
    doc.update({
        "document_id": doc_id,
        "extraction_id": ext_id,
        "extracted_at": CREATED_AT,
        "classification": {"type": template["document_type"], "label": f"Synthetic {template['document_type']}", "confidence": 1.0, "status": "classified"},
        "fields": {"execution_period": execution_period, **(source_fields or {})},
        "tables": [],
        "indicators": [],
        "missing_fields": [],
        "review_required": [],
        "line_items": [],
        "synthetic": True,
    })
    doc.pop("input_hash", None)
    doc.pop("input_version", None)
    row_template = template["line_items"][0]
    for index, spec in enumerate(rows):
        path = f"#/line_items/{index}/amount"
        row_id = f"{doc_id}-row-{index + 1:04d}"
        row = {key: _missing() for key, value in row_template.items() if isinstance(value, dict)}
        row.update({"row_id": row_id, "source_cells": [], "row_status": "extracted"})
        description = spec.get("description", f"Synthetic operation {index + 1}")
        row["description"] = _wrapper(doc_id, f"#/line_items/{index}/description", description, description, label="Operation description")
        amount = spec.get("amount")
        if amount is None:
            row["amount"] = _missing()
        else:
            amount_text = str(amount)
            row["amount"] = _wrapper(
                doc_id, path,
                {"amount": amount_text, "currency": spec.get("currency", "RUB")},
                amount_text,
                label=f"Amount for {description}",
                measure=spec.get("measure", "actual"),
                basis=spec.get("basis"),
            )
        doc["line_items"].append(row)
    return doc


def _kfz(template: dict[str, Any], doc_id: str, target_amount: str, period: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    report = copy.deepcopy(template)
    ext_id = f"live-synthetic-extraction-{doc_id}-v1"
    indicator_value = {"amount": target_amount, "currency": "RUB"}
    report.update({
        "document_id": doc_id,
        "extraction_id": ext_id,
        "extracted_at": CREATED_AT,
        "classification": {"type": "kfz_report", "label": "Synthetic KФЗ report", "confidence": 1.0, "status": "classified"},
        "fields": {}, "tables": [], "line_items": [], "missing_fields": [], "review_required": [],
        "indicators": [
            {"key": "reported_total", "label": "Synthetic target indicator", "extracted": _wrapper(doc_id, "#/indicators/0/extracted", indicator_value, target_amount, label="Synthetic target indicator")},
            {"key": "reporting_period", "label": "Synthetic reporting period", "extracted": _wrapper(doc_id, "#/indicators/1/extracted", period, "Synthetic reporting period", label="Synthetic reporting period")},
        ],
        "synthetic": True,
    })
    report.pop("input_hash", None)
    report.pop("input_version", None)
    return report, {"document_id": doc_id, "extraction_id": ext_id, "document_type": "kfz_report", "version": report["version"], "schema_version": report["schema_version"], "input_version": report["version"]}


def _evidence(source: Fact, target: Fact) -> dict[str, Any]:
    return {
        "source": {"document_id": source.document_id, "path": source.source_path, "raw_value": "synthetic-private-value", "normalized_value": "synthetic-source", "provenance": source.provenance},
        "target": {"document_id": target.document_id, "path": target.source_path, "raw_value": "synthetic-target-value", "normalized_value": "synthetic-target", "provenance": target.provenance},
        "signal": "synthetic_operation_support",
        "explanation": "Synthetic evidence edge for evaluator-controlled test records.",
    }


def _support_link(source: Fact, target: Fact, link_id: str, *, confirmed: bool = True) -> dict[str, Any]:
    result = {
        "link_id": link_id,
        "relationship_type": "supports_indicator",
        "source_document_id": source.document_id,
        "target_document_id": target.document_id,
        "evidence": [_evidence(source, target)],
        "explanation": "Synthetic source-to-target relation.",
        "confidence": 1.0 if confirmed else 0.7,
        "status": "confirmed" if confirmed else "review",
        "verification_status": "human_confirmed" if confirmed else "not_reviewed",
        "detection_method": "llm",
        "conflicts": [],
    }
    if source.row_id:
        result["source_row_id"] = source.row_id
    return result


def _correspondence_link(left: Fact, right: Fact, link_id: str) -> dict[str, Any]:
    return {
        "link_id": link_id,
        "relationship_type": "line_item_correspondence",
        "source_document_id": left.document_id,
        "target_document_id": right.document_id,
        "source_row_id": left.row_id,
        "target_row_id": right.row_id,
        "evidence": [_evidence(left, right)],
        "explanation": "Synthetic duplicate-operation correspondence.",
        "confidence": 1.0,
        "status": "confirmed",
        "verification_status": "human_confirmed",
        "detection_method": "llm",
        "conflicts": [],
    }


def _linking(extractions: list[dict[str, Any]], links: list[dict[str, Any]], unlinked: list[str] | None = None) -> dict[str, Any]:
    return {
        "linking_run_id": "live-synthetic-linking-v1",
        "contract_version": "1.2.0",
        "created_at": CREATED_AT,
        "input_documents": [{"document_id": doc["document_id"], "extraction_id": doc["extraction_id"], "document_type": doc["document_type"], "version": doc["version"], "schema_version": doc["schema_version"], "input_version": doc["version"]} for doc in extractions],
        "links": links,
        "review_required": [{"link_id": link["link_id"], "reason": "Synthetic unreviewed relation.", "candidate_document_ids": [link["source_document_id"], link["target_document_id"]]} for link in links if link["verification_status"] != "human_confirmed"],
        "unlinked_documents": [{"document_id": doc_id, "reason": "Synthetic source has no confirmed target link."} for doc_id in (unlinked or [])],
        "warnings": ["Synthetic evaluation data; no production documents or values."],
        "link_validation_diagnostics": [],
        "analysis_summary": "Synthetic evaluation graph.",
        "processing_metadata": {"engine_version": "live-e2e-test", "llm": {"enabled": False, "provider": "not_called", "model": "not_called", "strategy": "full_set", "estimated_input_tokens": 0, "calls": 0, "errors": 0, "duration_ms": 0}, "duration_ms": 0},
    }


def _make_case(
    case_id: str,
    title: str,
    target_label: str,
    target_amount: str,
    document_specs: list[dict[str, Any]],
    expected_groups: list[list[Fact]],
    *,
    expected_formula: dict[str, Any],
    period: dict[str, str] = PERIOD,
    amount_basis: str = "unspecified",
    economic_measure: str = "actual",
    required_document_types: list[str] | None = None,
    support: bool = True,
    unlinked_doc_ids: list[str] | None = None,
    extra_correspondences: list[tuple[Fact, Fact]] | None = None,
    scenario_note: str = "",
) -> dict[str, Any]:
    extractions = [
        _document(_fixture(spec["template"]), spec["document_id"], spec["rows"], spec.get("period", period), spec.get("source_fields"))
        for spec in document_specs
    ]
    kfz, _ = _kfz(_fixture("kfz-2026-q1.json"), f"live-synthetic-kfz-{case_id}", target_amount, period)
    extractions.append(kfz)
    all_facts = extract_facts(extractions)
    target_fact = next(fact for fact in all_facts if fact.document_id == kfz["document_id"] and fact.key == "reported_total")
    target = TargetIndicator(
        target_id=f"live-{case_id}", target_fact_id=target_fact.fact_id,
        kfz_document_id=kfz["document_id"], kfz_source_path=target_fact.source_path,
        label=target_label, description=f"Synthetic evaluation case: {title}. {scenario_note}".strip(),
        currency="RUB", amount_basis=amount_basis, economic_measure=economic_measure,
        period_basis="document_period", required_document_types=required_document_types or [],
    )
    links: list[dict[str, Any]] = []
    link_index = 0
    source_facts = [fact for fact in all_facts if fact.document_id != kfz["document_id"] and fact.status == "extracted" and fact.currency]
    if support:
        for source in source_facts:
            link_index += 1
            # Linking is a discovery hint; synthetic fixtures should not imply
            # that every machine-proposed relation was reviewed by a person.
            links.append(_support_link(source, target_fact, f"synthetic-support-{case_id}-{link_index:04d}", confirmed=source.fact_id in {fact.fact_id for group in expected_groups for fact in group}))
    for index, (left, right) in enumerate(extra_correspondences or [], start=1):
        links.append(_correspondence_link(left, right, f"synthetic-correspondence-{case_id}-{index:04d}"))
    linking = _linking(extractions, links, unlinked_doc_ids)
    request = ReconciliationRequest(
        contract_version="1.0.0",
        extraction_results=extractions,
        linking_result=linking,
        context=ReconciliationContext(period_start=period["start"], period_end=period["end"], targets=[target], data_classification="open", external_llm_allowed=True),
    )
    source_groups = [[fact.fact_id for fact in group] for group in expected_groups]
    reference = {
        "case_id": case_id,
        "synthetic": True,
        "title": title,
        "scenario_note": scenario_note,
        "expected_source_groups": source_groups,
        "expected_excluded_fact_ids": sorted(fact.fact_id for fact in source_facts if all(fact.fact_id not in group for group in source_groups)),
        "expected_formula": expected_formula,
        "expected_value": target_amount,
        "expected_publication_gate": "independence_not_established" if len({fact.document_id for group in expected_groups for fact in group}) > 1 else ("required_document_missing" if required_document_types else None),
        "truth_source": "deterministic synthetic input specification; independent of all LLM outputs",
    }
    return {
        "request": request.model_dump(mode="json"),
        "reference": reference,
        "metadata": {"case_id": case_id, "title": title, "synthetic": True, "candidate_count": sum(1 for fact in source_facts if isinstance(fact.value, (int, float)) or fact.currency and fact.value is not None)},
    }


def build_cases() -> list[dict[str, Any]]:
    act_template = _fixture("act-2026-0424.json")
    invoice_template = _fixture("invoice-2026-0408.json")
    registry_template = _fixture("registry-2026-04.json")
    cases: list[dict[str, Any]] = []

    def create(case_id: str, title: str, label: str, amount: str, specs: list[dict[str, Any]], expected: list[tuple[str, str, str | None]], formula: dict[str, Any], **kwargs: Any) -> None:
        prelim_docs = [_document(_fixture(spec["template"]), spec["document_id"], spec["rows"], spec.get("period", PERIOD), spec.get("source_fields")) for spec in specs]
        prelim_kfz, _ = _kfz(_fixture("kfz-2026-q1.json"), f"live-synthetic-kfz-{case_id}", amount, PERIOD)
        facts = extract_facts(prelim_docs + [prelim_kfz])
        grouped: list[list[Fact]] = []
        for doc_id, key, row_id in expected:
            fact = next(fact for fact in facts if fact.document_id == doc_id and fact.key == key and (row_id is None or fact.row_id == row_id))
            grouped.append([fact])
        correspondence_specs = kwargs.pop("correspondence", [])
        correspondences = []
        for left_ref, right_ref in correspondence_specs:
            left = next(fact for fact in facts if fact.document_id == left_ref[0] and fact.row_id == left_ref[1] and fact.key == "amount")
            right = next(fact for fact in facts if fact.document_id == right_ref[0] and fact.row_id == right_ref[1] and fact.key == "amount")
            correspondences.append((left, right))
        cases.append(_make_case(case_id, title, label, amount, specs, grouped, expected_formula=formula, extra_correspondences=correspondences, **kwargs))

    create(
        "01_single_act", "Один акт", "Total for one completed site inspection", "550.00",
        [{"template": "act-2026-0424.json", "document_id": "live-one-act", "rows": [{"amount": "550.00", "description": "Completed site inspection"}]}],
        [("live-one-act", "amount", "live-one-act-row-0001")], {"operation": "sum", "input_count": 1},
        scenario_note="Select the sole completed financial row.",
    )

    create(
        "02_independent_acts", "Сумма независимых актов", "Total for independent completed services", "150.00",
        [
            {"template": "act-2026-0424.json", "document_id": "live-independent-north", "rows": [{"amount": "100.00", "description": "North terminal inspection"}]},
            {"template": "act-2026-0424.json", "document_id": "live-independent-south", "rows": [{"amount": "50.00", "description": "South terminal inspection"}]},
        ],
        [("live-independent-north", "amount", "live-independent-north-row-0001"), ("live-independent-south", "amount", "live-independent-south-row-0001")],
        {"operation": "sum", "input_count": 2}, scenario_note="Two separately described operations in distinct acts; the engine still requires explicit cross-document independence confirmation.",
    )

    dup_ids = ["live-duplicate-act", "live-duplicate-invoice", "live-duplicate-registry"]
    dup_templates = ["act-2026-0424.json", "invoice-2026-0408.json", "registry-2026-04.json"]
    create(
        "03_duplicate_representations", "Акт, счёт и реестр одной операции", "Total for operation WO-018", "125.00",
        [{"template": template, "document_id": doc_id, "rows": [{"amount": "125.00", "description": "Work order WO-018 equipment inspection"}]} for template, doc_id in zip(dup_templates, dup_ids)],
        [(dup_ids[0], "amount", f"{dup_ids[0]}-row-0001")], {"operation": "sum", "input_count": 1},
        correspondence=[((dup_ids[0], f"{dup_ids[0]}-row-0001"), (dup_ids[1], f"{dup_ids[1]}-row-0001")), ((dup_ids[0], f"{dup_ids[0]}-row-0001"), (dup_ids[2], f"{dup_ids[2]}-row-0001"))],
        scenario_note="The act, invoice, and registry describe the same operation; any single representation may be selected, but none may be added to another.",
    )
    # Permit any one of the three known representations as the independent truth for this operation.
    duplicate_facts = []
    for doc_id in dup_ids:
        duplicate_facts.append((doc_id, "amount", f"{doc_id}-row-0001"))
    cases[-1]["reference"]["expected_source_groups"] = [[next(fact.fact_id for fact in extract_facts(cases[-1]["request"]["extraction_results"]) if fact.document_id == doc_id and fact.key == "amount") for doc_id in dup_ids]]

    create(
        "04_negative_adjustment", "Отрицательная корректировка", "Net total after the correction", "100.00",
        [{"template": "act-2026-0424.json", "document_id": "live-correction", "rows": [{"amount": "120.00", "description": "Original service charge"}, {"amount": "-20.00", "description": "Credit adjustment for the original service"}]}],
        [("live-correction", "amount", "live-correction-row-0001"), ("live-correction", "amount", "live-correction-row-0002")],
        {"operation": "sum", "input_count": 2}, scenario_note="The correction keeps its source sign and is included once.",
    )

    march = {"start": "2026-03-01", "end": "2026-03-31"}
    create(
        "05_period_filter", "Фильтр периода", "Total for April operations", "500.00",
        [
            {"template": "act-2026-0424.json", "document_id": "live-april-operation", "rows": [{"amount": "500.00", "description": "April equipment service"}], "period": PERIOD},
            {"template": "act-2026-0424.json", "document_id": "live-march-operation", "rows": [{"amount": "500.00", "description": "March equipment service"}], "period": march},
        ],
        [("live-april-operation", "amount", "live-april-operation-row-0001")],
        {"operation": "sum", "input_count": 1}, scenario_note="The March amount is deliberately equal to April but outside the requested period.",
    )

    gross = _wrapper("live-vat-case", "#/fields/gross_total", {"amount": "120.00", "currency": "RUB"}, "120.00", label="Gross amount including VAT", measure="actual", basis="gross")
    vat = _wrapper("live-vat-case", "#/fields/vat_amount", {"amount": "20.00", "currency": "RUB"}, "20.00", label="VAT amount included in gross amount", measure="actual", basis="gross")
    create(
        "06_vat_net", "НДС из gross-суммы", "Net amount after VAT is removed", "100.00",
        [{"template": "act-2026-0424.json", "document_id": "live-vat-case", "rows": [], "source_fields": {"gross_total": gross, "vat_amount": vat}}],
        [("live-vat-case", "gross_total", None), ("live-vat-case", "vat_amount", None)],
        {"operation": "subtract", "ordered_keys": ["gross_total", "vat_amount"]}, amount_basis="net",
        scenario_note="Subtract the explicitly identified VAT amount from a same-document gross total.",
    )

    create(
        "07_missing_document_link", "Нет обязательного счёта и подтверждённой связи", "Total supported by an invoice", "500.00",
        [{"template": "act-2026-0424.json", "document_id": "live-unlinked-act", "rows": [{"amount": "500.00", "description": "Completed equipment inspection"}]}],
        [("live-unlinked-act", "amount", "live-unlinked-act-row-0001")],
        {"operation": "sum", "input_count": 1}, required_document_types=["invoice"], support=False,
        unlinked_doc_ids=["live-unlinked-act"], scenario_note="Even a numerically complete plan must not be published without the required invoice and a confirmed evidence path.",
    )

    create(
        "08_actual_vs_planned", "Факт против плана", "Actual completed service amount", "900.00",
        [{"template": "act-2026-0424.json", "document_id": "live-measures", "rows": [{"amount": "1000.00", "description": "Planned service amount", "measure": "planned"}, {"amount": "900.00", "description": "Actual completed service amount", "measure": "actual"}]}],
        [("live-measures", "amount", "live-measures-row-0002")], {"operation": "sum", "input_count": 1},
        scenario_note="The larger planned value is not interchangeable with the actual completed amount.",
    )

    create(
        "09_similar_equal_amounts", "Похожие операции с одинаковыми суммами", "North room window repair total", "125.00",
        [{"template": "act-2026-0424.json", "document_id": "live-similar-ops", "rows": [
            {"amount": "125.00", "description": "Window repair Building 14 room North"},
            {"amount": "125.00", "description": "Window repair Building 14 room South"},
            {"amount": "125.00", "description": "Door repair Building 14 room North"},
        ]}],
        [("live-similar-ops", "amount", "live-similar-ops-row-0001")], {"operation": "sum", "input_count": 1},
        scenario_note="All amounts are equal; selection must use operation semantics and location, not numeric coincidence.",
    )

    # Put the sole relevant candidate beyond the first 300-item planner batch.
    many_rows = [{"amount": f"{50 + index:.2f}", "description": ("Foundation support bracket ZX-14 inspection" if index == 307 else f"Routine documentation item {index:03d}")} for index in range(320)]
    create(
        "10_hundreds_of_candidates", "320 числовых кандидатов", "Foundation support bracket ZX-14 inspection amount", f"{50 + 307:.2f}",
        [{"template": "act-2026-0424.json", "document_id": "live-many-candidates", "rows": many_rows}],
        [("live-many-candidates", "amount", "live-many-candidates-row-0308")], {"operation": "sum", "input_count": 1},
        scenario_note="Many numeric candidates require chunked review; identify sources from operation semantics and account for every candidate across batches.",
    )

    return cases


def prepare() -> list[dict[str, Any]]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    for case in cases:
        directory = RESULTS / case["reference"]["case_id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "input.json").write_text(json.dumps(case["request"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (directory / "golden-reference.json").write_text(json.dumps(case["reference"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"prepared_at": datetime.now(timezone.utc).isoformat(), "live_llm_calls": 0, "status": "prepared_not_run", "scenario_count": len(cases), "repeat_count": 3, "note": "Synthetic inputs and independent references only; no LLM response is fabricated."}
    (RESULTS / "preparation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases


if __name__ == "__main__":
    prepared = prepare()
    print(f"Prepared {len(prepared)} synthetic scenarios under {RESULTS}")
