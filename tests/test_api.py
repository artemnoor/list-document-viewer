import json
import asyncio
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from reconciliation_engine.api import app
from reconciliation_engine.storage import ResultStore
from reconciliation_engine.facts import extract_facts

from conftest import UPSTREAM_FIXTURES, load_upstream, make_request, plan_for


def _request(method: str, path: str, payload=None, headers=None):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=payload, headers=headers)

    return asyncio.run(run())


def test_health_docs_and_openapi(tmp_path):
    app.state.result_store = ResultStore(str(tmp_path / "store"))
    assert _request("GET", "/health").json()["status"] == "ok"
    assert _request("GET", "/docs").status_code == 200
    openapi = _request("GET", "/openapi.json").json()
    assert "/api/v1/reconciliations" in openapi["paths"]
    assert "/api/v1/reconciliations/{reconciliation_id}" in openapi["paths"]
    assert "ReconciliationResult" in openapi["components"]["schemas"]


def test_post_and_get_result_round_trip_and_output_schema(tmp_path):
    app.state.result_store = ResultStore(str(tmp_path / "store"))
    act = load_upstream("act-2026-0424.json")
    source = next(fact for fact in extract_facts([act]) if fact.role == "indicator" and fact.key == "amount_due")
    request = make_request([act], plan_for([act], [source]))

    response = _request("POST", "/api/v1/reconciliations", request.model_dump(mode="json"))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["calculations"][0]["expected_value"] == "1180300.00"
    duplicate = _request("POST", "/api/v1/reconciliations", request.model_dump(mode="json"))
    assert duplicate.status_code == 200
    assert duplicate.json()["created_at"] == result["created_at"]
    fetched = _request("GET", f"/api/v1/reconciliations/{result['reconciliation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["reconciliation_id"] == result["reconciliation_id"]


def test_project_authentication_and_result_isolation(tmp_path, monkeypatch):
    from reconciliation_engine import api
    from reconciliation_engine.config import Settings

    api_settings = Settings(api_auth_enabled=True, api_project_tokens={"project-secret": "project-a"}, result_store_dir=str(tmp_path / "store"))
    monkeypatch.setattr(api, "settings", api_settings)
    app.state.result_store = ResultStore(str(tmp_path / "store"))
    act = load_upstream("act-2026-0424.json")
    source = next(fact for fact in extract_facts([act]) if fact.role == "indicator" and fact.key == "amount_due")
    payload = make_request([act], plan_for([act], [source])).model_dump(mode="json")
    unauthorized = _request("POST", "/api/v1/reconciliations", payload)
    assert unauthorized.status_code == 401

    headers = {"Authorization": "Bearer project-secret", "X-Project-ID": "project-a"}
    created = _request("POST", "/api/v1/reconciliations", payload, headers=headers)
    assert created.status_code == 201, created.text
    result_id = created.json()["reconciliation_id"]
    wrong_scope = _request("GET", f"/api/v1/reconciliations/{result_id}", headers={"Authorization": "Bearer project-secret", "X-Project-ID": "project-b"})
    assert wrong_scope.status_code == 403
    fetched = _request("GET", f"/api/v1/reconciliations/{result_id}", headers=headers)
    assert fetched.status_code == 200
    result = fetched.json()

    schema_path = Path(__file__).resolve().parents[1] / "schemas/reconciliation-result-1.0.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(result))
    assert not errors, [item.message for item in errors]


def test_post_returns_exact_contract_diagnostic_for_stale_link_version(tmp_path):
    app.state.result_store = ResultStore(str(tmp_path / "store"))
    extractions = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(UPSTREAM_FIXTURES.glob("*.json"))]
    linking = json.loads((Path(__file__).resolve().parents[1] / "fixtures/upstream-linking/linking-result-legacy-1.0.0.json").read_text(encoding="utf-8"))
    payload = {
        "contract_version": "1.0.0",
        "extraction_results": extractions,
        "linking_result": linking,
        "context": {"targets": [{"target_id": "test", "label": "Test", "kfz_document_id": "act-2026-0424", "kfz_source_path": "#/indicators/0/extracted"}]},
    }

    response = _request("POST", "/api/v1/reconciliations", payload)
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["code"] == "input_contract_error"
    assert any(item["code"] == "unsupported_linking_contract_version" and item["path"] == "$.linking_result.contract_version" for item in body["diagnostics"])


def test_confidential_context_skips_external_model_calls(tmp_path, monkeypatch):
    from reconciliation_engine.config import Settings
    from reconciliation_engine.models import ReconciliationContext, ReconciliationRequest
    from reconciliation_engine.service import reconcile
    from reconciliation_engine.planner import LLMPlanner

    monkeypatch.setattr(LLMPlanner, "plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    act = load_upstream("act-2026-0424.json")
    target_fact = next(fact for fact in extract_facts([act]) if fact.role == "indicator")
    request = ReconciliationRequest(
        contract_version="1.0.0",
        extraction_results=[act],
        linking_result=__import__("conftest").make_linking([act]),
        context=ReconciliationContext(targets=[{"target_id": "private", "label": "Private", "kfz_document_id": target_fact.document_id, "kfz_source_path": target_fact.source_path, "target_fact_id": target_fact.fact_id}], data_classification="confidential", external_llm_allowed=False),
    )
    result = reconcile(request, Settings(llm_enabled=True, llm_api_key="present", result_store_dir=str(tmp_path)))
    assert any(item["code"] == "external_llm_not_authorized" for item in result["calculations"][0]["diagnostics"])


def test_trusted_local_flag_never_sends_confidential_data_to_an_external_api(tmp_path, monkeypatch):
    from reconciliation_engine.config import Settings
    from reconciliation_engine.service import reconcile
    import httpx
    from conftest import make_request

    calls = []
    monkeypatch.setattr(httpx.Client, "post", lambda *args, **kwargs: calls.append((args, kwargs)))
    act = load_upstream("act-2026-0424.json")
    request = make_request([act], None)
    result = reconcile(request, Settings(llm_enabled=True, llm_trusted_local=True, llm_api_key="configured", llm_base_url="https://api.openai.com/v1", result_store_dir=str(tmp_path)))
    assert calls == []
    assert any(item["code"] == "trusted_llm_endpoint_not_local" for item in result["calculations"][0]["diagnostics"])


def test_recorded_upstream_example_remains_reproducible():
    root = Path(__file__).resolve().parents[1]
    request_schema = json.loads((root / "schemas/reconciliation-request-1.0.0.schema.json").read_text(encoding="utf-8"))
    request = json.loads((root / "examples/act-reconciliation-request.json").read_text(encoding="utf-8"))
    result = json.loads((root / "examples/act-reconciliation-result.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(request_schema, format_checker=FormatChecker()).iter_errors(request))
    assert not errors, [item.message for item in errors]
    assert result["calculations"][0]["expected_value"] is None
    assert result["calculations"][0]["status"] == "manual_review"
    assert any(error["code"] == "target_period_mismatch" for error in result["calculations"][0]["errors"])
    assert result["calculations"][0]["used_sources"] == []
    assert result["calculations"][0]["comparison_performed"] is False
