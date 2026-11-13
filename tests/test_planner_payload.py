import json

from reconciliation_engine.config import Settings
from reconciliation_engine.facts import extract_facts
from reconciliation_engine.models import TargetIndicator
from reconciliation_engine.planner import LLMPlanner

from conftest import correspondence_link, load_upstream, make_linking


def test_planner_payload_contains_pseudonymized_link_graph_without_raw_locators_or_source_values():
    act = load_upstream("act-2026-0424.json")
    invoice = load_upstream("invoice-2026-0408.json")
    facts = extract_facts([act, invoice])
    link = correspondence_link(act, act["line_items"][0]["row_id"], invoice, invoice["line_items"][0]["row_id"])
    linking = make_linking([act, invoice], links=[link], review=[{"link_id": link["link_id"], "reason": "review rationale is omitted", "candidate_document_ids": [act["document_id"], invoice["document_id"]]}])
    linking["unlinked_documents"] = [{"document_id": invoice["document_id"], "reason": "private reason is omitted"}]
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
    assert payload["linking_graph"]["relationships"][0]["relationship_type"] == "line_item_correspondence"
    assert payload["linking_graph"]["relationships"][0]["verification_status"] == "not_reviewed"
    assert payload["linking_graph"]["review_required"][0]["link_ref"] == "link_001"
    assert payload["linking_graph"]["unlinked_source_groups"] == [{"source_group_id": "source_002"}]
    assert payload["document_date_facts"]
    assert all("source_value" not in candidate and "provenance" not in candidate for candidate in payload["candidates"])
