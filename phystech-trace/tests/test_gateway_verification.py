import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from gateway import main

ROOT = Path(__file__).resolve().parents[1]


def test_contracts_match_published_native_schemas():
    pairs = [
        ("extraction", "verification-engine/contracts/upstream/structured-extraction-1.2.0.schema.json"),
        ("linking", "verification-engine/contracts/upstream/document-linking-1.2.0.schema.json"),
        ("reconciliation", "verification-engine/contracts/reconciliation-engine/reconciliation-result-1.0.0.schema.json"),
        ("verification", "verification-engine/contracts/verification-result-1.2.0.schema.json"),
    ]
    for name, path in pairs:
        assert main.CONTRACTS[name] == json.loads((ROOT / "services" / path).read_text(encoding="utf-8"))


def test_indicator_only_monetary_target_is_not_lost():
    result = main.reconciliation_targets({"document_id": "kfz", "fields": {}, "indicators": [{
        "key": "total", "extracted": {"value": {"amount": "10.00", "currency": "RUB"}}
    }]})
    assert len(result) == 1
    assert result[0]["kfz_source_path"] == "#/indicators/0/extracted"


def test_link_edit_invalidates_both_downstream_stages():
    states = main.mark_reconciliation_pending({"verification": {"status": "completed"}})
    assert states["reconciliation"]["status"] == "pending"
    assert states["verification"]["status"] == "pending"


def test_verification_retry_uses_saved_calculation_and_preserves_failure_boundary(monkeypatch):
    updates, statuses = [], []
    monkeypatch.setattr(main, "update_stage", lambda *args, **kw: updates.append((args, kw)))
    monkeypatch.setattr(main, "set_project_status", lambda *args, **kw: statuses.append((args, kw)))
    monkeypatch.setattr(main, "contract_errors", lambda *args: [])
    reconcile = AsyncMock()
    verify = AsyncMock(side_effect=RuntimeError("invalid calculation proof"))
    monkeypatch.setattr(main, "reconcile_saved_project", reconcile)
    monkeypatch.setattr(main, "verify_saved_project", verify)
    project = {"id": "project", "reconciliation_result": {"reconciliation_id": "saved"}}
    asyncio.run(main.finish_pipeline(None, project, [], {}, "verification"))
    reconcile.assert_not_awaited()
    assert verify.await_args.args[-1] is project["reconciliation_result"]
    assert updates[-1][0][1] == "verification"
    assert updates[-1][1]["status"] == "failed"
    assert statuses[-1][0][1] == "partial"


def test_verifier_receives_saved_inputs_and_rereads_in_project_scope(monkeypatch):
    result = {"verification_id": "ver-saved", "project_id": "project"}
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=result)
    monkeypatch.setattr(main, "contract_errors", lambda *args: [])
    docs = [{"role": "kfz", "extraction_result": {"document_id": "kfz"}}, {"role": "primary", "extraction_result": {"document_id": "act"}}]
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await main.verify_saved_project(client, {"id": "project"}, docs, {"links": []}, {"calculations": []})
    assert asyncio.run(run()) == result
    payload = json.loads(captured[0].content)
    assert payload["extraction"] == docs[0]["extraction_result"]
    assert payload["supporting_extractions"] == [docs[1]["extraction_result"]]
    assert payload["reconciliation_result"] == {"calculations": []}
    assert captured[1].url.params["project_id"] == "project"
