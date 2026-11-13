#!/usr/bin/env python3
"""Recheck a completed synthetic project and evidence without calling an LLM."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from run_e2e import resolve_json_path


TRACE_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_RELATIONS = {
    "report_summarizes_registry", "act_validates_registry", "act_contains_line_item",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def has_pair(link: dict[str, Any], source_path: str, target_path: str) -> bool:
    return any(
        evidence.get("source", {}).get("path") == source_path
        and evidence.get("target", {}).get("path") == target_path
        and evidence.get("source", {}).get("raw_value") == evidence.get("target", {}).get("raw_value")
        for evidence in link.get("evidence", [])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with httpx.Client(timeout=httpx.Timeout(30, connect=8)) as client:
        response = client.get(f"{base}/api/projects/{args.project_id}")
        require(response.status_code == 200, f"Project read failed: HTTP {response.status_code}")
        project = response.json()
        require(project.get("status") == "completed", "Project is not completed")
        require(all(project.get("stages", {}).get(stage, {}).get("status") == "completed" for stage in ("parser", "extraction", "linking")), "One or more project stages are incomplete")

        result = project.get("linking_result") or {}
        llm = result.get("processing_metadata", {}).get("llm", {})
        require(llm.get("provider") == "Polza AI" and llm.get("calls", 0) > 0, "Saved output lacks live Polza model metadata")
        links = result.get("links", [])
        by_type = {link.get("relationship_type"): link for link in links}
        require(EXPECTED_RELATIONS <= by_type.keys(), "Saved Linking output lacks expected synthetic relationships")
        require(has_pair(by_type["report_summarizes_registry"], "fields.reported_total.value.amount", "fields.registry_total.value.amount"), "Report total does not match registry total evidence")
        require(has_pair(by_type["act_validates_registry"], "fields.amount_due.value.amount", "fields.registry_total.value.amount"), "Act total does not match registry total evidence")
        line_link = by_type["act_contains_line_item"]
        require(has_pair(line_link, "line_items[0].description.value", "tables[0].rows[0].description.value"), "Known line item description does not match")
        require(has_pair(line_link, "line_items[0].quantity.value", "tables[0].rows[0].quantity.value"), "Known line item quantity does not match")
        require(has_pair(line_link, "line_items[0].amount.value.amount", "tables[0].rows[0].amount.value.amount"), "Known line item amount does not match")

        extractions: dict[str, dict[str, Any]] = {}
        source_documents = 0
        for doc in project.get("documents", []):
            saved = client.get(f"{base}/api/projects/{args.project_id}/documents/{doc['id']}/result")
            require(saved.status_code == 200, f"Saved Extraction unavailable for {doc['file_name']}")
            extraction = saved.json().get("extraction")
            require(isinstance(extraction, dict) and extraction.get("document_id") == doc.get("document_id"), "Extraction document identity changed")
            extractions[doc["document_id"]] = extraction
            original = client.get(f"{base}/api/projects/{args.project_id}/sources/{doc['document_id']}")
            require(original.status_code == 200 and original.content, f"Original source unavailable for {doc['file_name']}")
            source_documents += 1

        evidence_sides = 0
        for link in links:
            for evidence in link.get("evidence", []):
                for side, expected_doc_id in (("source", link["source_document_id"]), ("target", link["target_document_id"])):
                    citation = evidence.get(side) or {}
                    doc_id, path = citation.get("document_id"), citation.get("path")
                    require(doc_id == expected_doc_id and doc_id in extractions and isinstance(path, str), "Evidence points to an unknown document or path")
                    require(resolve_json_path(extractions[doc_id], path) == citation.get("raw_value"), "Evidence path no longer resolves to its reported value")
                    provenance = citation.get("provenance")
                    require(isinstance(provenance, dict) and provenance.get("document_id") == doc_id, "Evidence provenance is missing or mismatched")
                    evidence_sides += 1

        pdf_doc = next(doc for doc in project["documents"] if doc["file_name"].lower().endswith(".pdf"))
        page = client.get(f"{base}/api/projects/{args.project_id}/sources/{pdf_doc['document_id']}/pages/1")
        require(page.status_code == 200 and page.headers.get("content-type", "").startswith("image/png"), "Saved PDF page preview is unavailable")

    report = {
        "status": "saved-project-verified", "project_id": args.project_id,
        "model_provider": llm.get("provider"), "model": llm.get("model"),
        "model_calls": llm.get("calls"), "known_relations": sorted(EXPECTED_RELATIONS),
        "evidence_sides_resolved": evidence_sides, "source_documents_resolved": source_documents,
        "pdf_page_preview": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    results = TRACE_ROOT / "tests" / "e2e" / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "saved-project-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_path = results / "latest-run.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest.get("project_id") == args.project_id:
            latest.setdefault("linking", {})["known_relations"] = sorted(EXPECTED_RELATIONS)
            check = "Saved live relationships, known amounts/row values, source files, PDF page and evidence provenance revalidated"
            if check not in latest.setdefault("checks", []):
                latest["checks"].append(check)
            latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
