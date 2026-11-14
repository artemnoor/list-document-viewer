from reconciliation_engine.facts import extract_facts
from reconciliation_engine.planner import LLMPlanner
from reconciliation_engine.config import Settings
from reconciliation_engine.models import TargetIndicator


def test_unmapped_table_amounts_remain_calculation_sources_with_row_meaning():
    extraction = {"document_id": "memo", "extraction_id": "ex-memo", "document_type": "unknown", "fields": {}, "tables": [{"id": "t", "rows": [{"row_id": "r", "source_cells": [
        {"header": "Вид начисления", "extracted": {"value": "Основная заработная плата", "status": "extracted", "source_value": "Основная заработная плата", "provenance": {"source_ref": "#/rows/0/0", "source_part_id": "description"}}},
        {"header": "Сумма, руб.", "extracted": {"value": {"amount": "123.45", "currency": "RUB"}, "status": "extracted", "source_value": "123,45", "provenance": {"source_ref": "#/rows/0/1", "source_part_id": "amount"}}}
    ]}]}]}
    facts = extract_facts([extraction])
    money = [f for f in facts if f.currency == "RUB"]
    assert len(money) == 1
    assert money[0].source_path == "#/tables/0/rows/0/source_cells/1/extracted"
    target = TargetIndicator(target_id="target", kfz_document_id="report", kfz_source_path="#/fields/total", label="Затраты на оплату труда", currency="RUB")
    payload = LLMPlanner(Settings()).build_payload(target, facts, {}, {"links": []})
    assert any("Основная заработная плата" in (c.get("operation_description") or "") for c in payload["candidates"])
    assert "123.45" not in str(payload)


def test_independent_targets_can_run_concurrently_without_reordering_results(monkeypatch):
    import threading
    from reconciliation_engine import service
    from conftest import make_request, load_upstream
    request = make_request([load_upstream("act-2026-0424.json")], None)
    first = request.context.targets[0]
    request = request.model_copy(update={"context": request.context.model_copy(update={"targets": [first, first.model_copy(update={"target_id": "second"})]})})
    barrier = threading.Barrier(2, timeout=1)
    def calculate(_request, target, *_args):
        barrier.wait()
        return {"target": {"target_id": target.target_id}, "errors": [], "concurrent": True}
    monkeypatch.setattr(service, "_calculate_target", calculate)
    result = service.reconcile(request, Settings(target_workers=2))
    assert [r["target"]["target_id"] for r in result["calculations"]] == [first.target_id, "second"]
    assert all(r.get("concurrent") for r in result["calculations"])



def test_act_date_supplies_document_period_without_using_contract_signing_date():
    extraction = {"document_id": "act", "extraction_id": "act-ex", "document_type": "act", "fields": {"act_date": {"value": "2026-02-27", "status": "extracted"}, "contract_date": {"value": "2024-03-15", "status": "extracted"}, "amount_due": {"value": {"amount": "123.45", "currency": "RUB"}, "status": "extracted"}}}
    amount = next(f for f in extract_facts([extraction]) if f.key == "amount_due")
    assert amount.period_start.isoformat() == "2026-02-27"
    assert amount.period_end == amount.period_start


def test_selected_source_from_another_explicit_agreement_is_rejected():
    from reconciliation_engine.engine import validate_plan
    from conftest import load_upstream, make_linking, make_target, plan_for
    report = load_upstream("kfz-2026-q1.json")
    act = load_upstream("act-2026-0424.json")
    report["fields"]["contract_reference"] = {"value": "AGREEMENT-A", "status": "extracted", "source_value": "AGREEMENT-A", "confidence": None, "provenance": None}
    act["fields"]["contract_reference"] = {"value": "AGREEMENT-B", "status": "extracted", "source_value": "AGREEMENT-B", "confidence": None, "provenance": None}
    facts = extract_facts([report, act])
    selected = next(f for f in facts if f.document_id == act["document_id"] and f.key == "amount_due" and f.currency == "RUB")
    target = make_target().model_copy(update={"kfz_document_id": report["document_id"]})
    diagnostics = validate_plan(plan_for([report, act], [selected]), target, facts, make_linking([report, act]))
    assert any(item.code == "agreement_mismatch" for item in diagnostics)
