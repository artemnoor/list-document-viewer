#!/usr/bin/env python3
"""Resume the real Linking API for an already parsed synthetic project."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from run_e2e import resolve_json_path


TRACE_ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def get_project(client: httpx.Client, base: str, project_id: str) -> dict[str, Any]:
    response = client.get(f"{base}/api/projects/{project_id}")
    require(response.status_code == 200, f"Project read failed: HTTP {response.status_code}")
    return response.json()


def wait_for_project(client: httpx.Client, base: str, project_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        project = get_project(client, base, project_id)
        if project.get("stages", {}).get("linking", {}).get("status") in {"completed", "failed", "blocked"}:
            return project
        time.sleep(2)
    raise TimeoutError("Gateway did not finish the resumed Linking stage")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "synthetic-only",
        "external_llm_consent": True,
        "reused_project": True,
        "project_id": args.project_id,
        "checks": [],
    }

    with httpx.Client(timeout=httpx.Timeout(30, connect=8)) as client:
        health = client.get(f"{base}/health")
        require(health.status_code == 200, f"Gateway health returned HTTP {health.status_code}")
        linking_health = client.get("http://127.0.0.1:8083/health")
        require(linking_health.status_code == 200 and linking_health.json().get("llm", {}).get("configured") is True, "Real Linking model is not configured")

        before = get_project(client, base, args.project_id)
        require(before["stages"]["parser"]["status"] == "completed", "Parser output is not completed")
        require(before["stages"]["extraction"]["status"] == "completed", "Extraction output is not completed")
        saved_ids = {item["document_id"]: item.get("extraction_id") for item in before["documents"]}
        require(len(saved_ids) >= 2 and all(saved_ids.values()), "Saved extraction IDs are missing")

        if before["stages"]["linking"]["status"] != "completed":
            retry = client.post(f"{base}/api/projects/{args.project_id}/retry", params={"stage": "linking"})
            require(retry.status_code == 202, f"Gateway Linking retry returned HTTP {retry.status_code}: {retry.text[:500]}")
            report["checks"].append("Linking retried through Gateway while saved Parser/Extraction stages were reused")
            project = wait_for_project(client, base, args.project_id, args.timeout)
        else:
            project = before

        require(project["stages"]["parser"]["status"] == "completed", "Parser was not retained after the Linking retry")
        require(project["stages"]["extraction"]["status"] == "completed", "Extraction was not retained after the Linking retry")
        final_ids = {item["document_id"]: item.get("extraction_id") for item in project["documents"]}
        require(saved_ids == final_ids, "Linking retry changed previously completed Extraction IDs")

        if project["stages"]["linking"]["status"] != "completed":
            report["status"] = "linking-retry-failed"
            report["linking"] = {
                "status": project["stages"]["linking"]["status"],
                "error": project["stages"]["linking"].get("error"),
                "parser_extraction_retained": True,
            }
            report["checks"].append("Linking retry failure was persisted while completed Parser/Extraction results and IDs remained unchanged")
            exit_code = 2
        else:
            exit_code = None

        extractions: dict[str, dict[str, Any]] = {}
        source_checks = 0
        for doc in (project["documents"] if exit_code is None else []):
            result = client.get(f"{base}/api/projects/{args.project_id}/documents/{doc['id']}/result")
            require(result.status_code == 200, f"Saved result is unavailable for {doc['file_name']}")
            body = result.json()
            extraction = body.get("extraction")
            require(extraction and extraction.get("document_id") == doc["document_id"], f"Extraction identity changed for {doc['file_name']}")
            extractions[doc["document_id"]] = extraction

            source = client.get(f"{base}/api/projects/{args.project_id}/sources/{doc['document_id']}")
            require(source.status_code == 200 and source.content, f"Original source is unavailable for {doc['file_name']}")
            source_checks += 1

        linking_result = project.get("linking_result") if exit_code is None else None
        if exit_code is None:
            require(isinstance(linking_result, dict), "Completed Linking stage has no result")
            llm = linking_result.get("processing_metadata", {}).get("llm", {})
            require(llm.get("provider") == "Polza AI" and llm.get("calls", 0) > 0, "Linking result does not contain a real Polza model call")

        evidence_sides = 0
        for link in linking_result.get("links", []) if linking_result else []:
            for evidence in link.get("evidence", []):
                for side, expected_id in (("source", link["source_document_id"]), ("target", link["target_document_id"])):
                    citation = evidence.get(side) or {}
                    document_id, path = citation.get("document_id"), citation.get("path")
                    require(document_id == expected_id and document_id in extractions and isinstance(path, str), "Link evidence points to an unknown document or path")
                    require(resolve_json_path(extractions[document_id], path) == citation.get("raw_value"), f"Evidence path does not resolve to its reported value: {document_id}:{path}")
                    provenance = citation.get("provenance")
                    require(isinstance(provenance, dict) and provenance.get("document_id") == document_id, "Evidence provenance is missing or belongs to another document")
                    evidence_sides += 1

        report["extraction_mode"] = project["stages"]["extraction"].get("mode")
        report["document_results"] = [
            {"name": doc["file_name"], "document_id": doc["document_id"], "extraction_id": doc["extraction_id"]}
            for doc in project["documents"]
        ]
        if linking_result:
            report["linking"] = {
                "status": "completed", "model_provider": llm.get("provider"), "model": llm.get("model"),
                "model_calls": llm.get("calls"), "links": len(linking_result.get("links", [])),
                "evidence_sides": evidence_sides, "source_documents_resolved": source_checks,
            }
            report["checks"].extend([
                "Persisted source files resolve through Gateway after retry",
                "Real Linking evidence paths resolve to exact Extraction values and matching provenance",
            ])
            report["status"] = "full-e2e-passed" if linking_result.get("links") and evidence_sides else "linking-completed-without-supported-relations"
            exit_code = 0 if report["status"] == "full-e2e-passed" else 3

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["elapsed_seconds"] = round((datetime.fromisoformat(report["finished_at"]) - datetime.fromisoformat(report["started_at"])).total_seconds(), 2)
    results = TRACE_ROOT / "tests" / "e2e" / "results"
    results.mkdir(parents=True, exist_ok=True)
    report_path = results / "latest-run.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "project_id": args.project_id, "documents": len(report.get("document_results", [])), "report": str(report_path), "linking": report.get("linking"), "checks": report["checks"]}, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
