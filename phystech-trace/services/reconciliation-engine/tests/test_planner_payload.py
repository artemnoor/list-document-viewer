import json

import httpx

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import extract_facts
from reconciliation_engine.models import TargetIndicator
from reconciliation_engine.planner import LLMPlanner
from reconciliation_engine.facts import numeric_value

from conftest import correspondence_link, load_upstream, make_linking


def test_planner_payload_contains_pseudonymized_link_graph_without_raw_locators_or_source_values():
    act = load_upstream("act-2026-0424.json")
    invoice = load_upstream("invoice-2026-0408.json")
    facts = extract_facts([act, invoice])
    link = correspondence_link(act, act["line_items"][0]["row_id"], invoice, invoice["line_items"][0]["row_id"])
    linking = make_linking([act, invoice], links=[link], review=[{"link_id": link["link_id"], "reason": "review rationale is omitted", "candidate_document_ids": [act["document_id"], invoice["document_id"]]}])
    linking["unlinked_documents"] = [{"document_id": invoice["document_id"], "reason": "private reason is omitted"}]
    linking["warnings"] = ["Unstructured warning text is deliberately not sent to the planner."]
    groups = {"opaque-a": act["document_id"], "opaque-b": invoice["document_id"]}
    target_fact = facts[0]
    target = TargetIndicator(target_id="target", label="Open target", kfz_document_id=act["document_id"], kfz_source_path=target_fact.source_path, target_fact_id=target_fact.fact_id)

    payload = LLMPlanner(Settings(llm_enabled=True, llm_api_key="configured")).build_payload(target, facts, groups, linking)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert act["document_id"] not in serialized
    assert invoice["document_id"] not in serialized
    assert act["line_items"][0]["row_id"] not in serialized
    assert invoice["line_items"][0]["row_id"] not in serialized
    assert link["link_id"] not in serialized
    assert "linking_graph" in payload
    assert "warning_count" not in payload["linking_graph"]
    assert payload["linking_graph"]["relationships"][0]["relationship_type"] == "line_item_correspondence"
    assert payload["linking_graph"]["relationships"][0]["verification_status"] == "not_reviewed"
    assert payload["linking_graph"]["review_required"][0]["link_ref"] == "link_00001"
    assert payload["linking_graph"]["unlinked_source_groups"][0]["source_group_id"] in payload["source_groups"]
    assert payload["document_date_facts"]
    assert all("source_value" not in candidate and "provenance" not in candidate for candidate in payload["candidates"])
    assert "source_unknown" not in serialized
    assert all(fact.fact_id not in serialized for fact in facts)
    assert all("value" not in candidate for candidate in payload["candidates"])


def test_planner_payload_omits_corrected_and_withdrawn_link_diagnostics():
    act = load_upstream("act-2026-0424.json")
    invoice = load_upstream("invoice-2026-0408.json")
    facts = extract_facts([act, invoice])
    target_fact = next(fact for fact in facts if fact.document_id == act["document_id"])
    target = TargetIndicator(target_id="target", label="Open target", kfz_document_id=act["document_id"], kfz_source_path=target_fact.source_path, target_fact_id=target_fact.fact_id)
    linking = make_linking([act, invoice])
    diagnostic = {
        "relationship_type": "line_item_correspondence",
        "source_document_id": invoice["document_id"],
        "target_document_id": act["document_id"],
        "reason_codes": ["raw_value_mismatch"],
        "candidate_status": "review",
    }
    linking["link_validation_diagnostics"] = [
        {**diagnostic, "resolution": "corrected"},
        {**diagnostic, "resolution": "unresolved"},
        {**diagnostic, "resolution": "withdrawn"},
    ]

    payload = LLMPlanner(Settings(llm_enabled=True, llm_api_key="configured")).build_payload(
        target, facts, {"opaque-a": act["document_id"], "opaque-b": invoice["document_id"]}, linking,
    )

    assert len(payload["linking_graph"]["validation_diagnostics"]) == 1
    assert payload["linking_graph"]["validation_diagnostics"][0]["reason_codes"] == ["raw_value_mismatch"]


def test_planner_omits_missing_nonnumeric_placeholders_from_candidate_batches():
    act = load_upstream("act-2026-0424.json")
    kfz = load_upstream("kfz-2026-q1.json")
    facts = extract_facts([act, kfz])
    target_fact = next(fact for fact in facts if fact.document_id == kfz["document_id"] and fact.key == "reported_total")
    target = TargetIndicator(target_id="target", label="Synthetic total", target_fact_id=target_fact.fact_id, kfz_document_id=kfz["document_id"], kfz_source_path=target_fact.source_path)
    linking = make_linking([act, kfz])
    payload = LLMPlanner(Settings(llm_enabled=True, llm_api_key="configured")).build_payload(target, facts, {doc["document_id"]: doc["document_id"] for doc in (act, kfz)}, linking)

    assert payload["candidate_count"] == sum(1 for fact in facts if fact.document_id != kfz["document_id"] and numeric_value(fact) is not None)
    assert payload["candidate_count"] < sum(1 for fact in facts if fact.document_id != kfz["document_id"])
    assert all(candidate["value_available"] for candidate in payload["candidates"])


def test_planner_records_actual_response_content_and_provider_usage(monkeypatch):
    plan_content = json.dumps({
        "target_id": "target_001",
        "method_description": "No applicable numeric source was selected.",
        "included": [],
        "excluded": [],
        "steps": [],
        "result_step_id": None,
        "requires_manual_review": True,
    })
    provider_response = {
        "id": "unit-test-response",
        "model": "openai/gpt-6.1-sol",
        "choices": [{"message": {"content": plan_content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168, "cost": 0.001, "cost_rub": 0.001},
    }
    posted_requests = []
    def provider_post(*args, **kwargs):
        posted_requests.append(kwargs["json"])
        return httpx.Response(200, json=provider_response, request=httpx.Request("POST", "https://polza.ai/api/v1/chat/completions"))
    monkeypatch.setattr(httpx.Client, "post", provider_post)
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="unit-test-only", llm_base_url="https://polza.ai/api/v1", llm_model="openai/gpt-6.1-sol"))

    plan = planner._request_plan({"candidates": []}, sensitive_data=False)

    assert plan.requires_manual_review
    assert len(planner.call_records) == 1
    assert planner.call_records[0]["assistant_content"] == plan_content
    assert planner.call_records[0]["usage"]["total_tokens"] == 168
    assert planner.call_records[0]["provider_cost"] == 0.001
    assert planner.call_records[0]["provider_cost_currency"] == "RUB"
    assert len(planner.call_records[0]["prompt_sha256"]) == 64
    assert len(planner.call_records[0]["payload_sha256"]) == 64
    assert posted_requests[0]["max_tokens"] == 2048


def test_planner_output_token_limit_scales_with_the_active_candidate_batch(monkeypatch):
    plan_content = json.dumps({"target_id": "target_001", "method_description": "No plan for this transport test.", "requires_manual_review": True})
    provider_response = {"choices": [{"message": {"content": plan_content}}]}
    posted_requests = []

    def provider_post(*args, **kwargs):
        posted_requests.append(kwargs["json"])
        return httpx.Response(200, json=provider_response, request=httpx.Request("POST", "https://polza.ai/api/v1/chat/completions"))

    monkeypatch.setattr(httpx.Client, "post", provider_post)
    planner = LLMPlanner(Settings(llm_enabled=True, llm_api_key="unit-test-only"))
    planner._request_plan({"candidates": [{}] * 120, "candidate_batch": {"batch_candidate_count": 120}}, sensitive_data=False)

    assert posted_requests[0]["max_tokens"] == 5_888
