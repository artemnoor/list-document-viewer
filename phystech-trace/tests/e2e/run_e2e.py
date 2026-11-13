#!/usr/bin/env python3
"""Run the Phystech Trace HTTP E2E with synthetic, repository-owned documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx
import fitz
from docx import Document
from openpyxl import Workbook


TRACE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = TRACE_ROOT.parent
FIXTURE_ROOT = REPO_ROOT / "backend" / "tests" / "complex_fixtures"
PATH_TOKEN = re.compile(r"[^.\[\]]+|\[(\d+)\]")


def walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def resolve_json_path(document: Any, path: str) -> Any:
    current = document
    for match in PATH_TOKEN.finditer(path.removeprefix("$.")):
        token = match.group(0)
        if token.startswith("["):
            if not isinstance(current, list):
                raise AssertionError(f"Evidence path {path} indexes a non-list value")
            current = current[int(token[1:-1])]
        else:
            if not isinstance(current, dict) or token not in current:
                raise AssertionError(f"Evidence path {path} does not resolve")
            current = current[token]
    return current


def make_synthetic_documents(directory: Path, compact_linking: bool = False) -> list[tuple[str, bytes, str]]:
    work_rows = [
        ("Р-110", "Обследование насосного узла № 4", 1, 286500),
        ("Р-204", "Измерение вибрации электроприводов", 24, 93600),
        ("Р-315", "Калибровка преобразователей частоты", 4, 99600),
        ("Р-418", "Пусконаладка контура сигнализации", 46, 158700),
        ("Р-522", "Монтаж шкафов РУ-0,4 кВ", 2, 541900),
    ]
    if compact_linking:
        work_rows = work_rows[:1]
    kfz_path = directory / "synthetic_kfz_report.pdf"
    font_candidates = [
        Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font_path = next((candidate for candidate in font_candidates if candidate.is_file()), None)
    if font_path is None:
        raise RuntimeError("A Unicode font is required to generate the synthetic KFZ PDF")
    pdf = fitz.open()
    page = pdf.new_page(width=595.28, height=841.89)
    page.insert_font(fontname="E2EUnicode", fontfile=str(font_path))
    kfz_text = "\n".join([
        "Контрольно-финансовый отчёт КФЗ-01/2026",
        "Номер отчёта: КФЗ-01/2026",
        "Дата отчёта: 31.03.2026",
        "Отчётный период: 01.01.2026 — 31.03.2026",
        "Отчитывающаяся организация: ООО «ИнжКонтур Бета»",
        "Заказчик: АО «Городские инженерные системы»",
        "Номер договора: КД240315",
        "Общая сумма по отчёту: 1 180 300,00 руб.",
        "Выполненные работы:",
        *(f"{code} | {description} | {quantity} | {amount:,}".replace(",", " ") for code, description, quantity, amount in work_rows),
    ])
    if page.insert_textbox(fitz.Rect(48, 48, 548, 790), kfz_text, fontname="E2EUnicode", fontsize=11, lineheight=1.45) < 0:
        raise RuntimeError("Synthetic KFZ PDF text exceeded the page bounds")
    pdf.save(kfz_path)
    pdf.close()

    xlsx_path = directory / "synthetic_primary_register.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Реестр выполненных работ"
    sheet.append(["Идентификатор", "Описание", "Количество", "Сумма, руб."])
    for row in work_rows:
        sheet.append(row)
    metadata = workbook.create_sheet("Реквизиты")
    metadata.append(["Наименование реестра", "Реестр выполненных работ по договору КД240315"])
    metadata.append(["Договор", "КД240315"])
    metadata.append(["Организация", "ООО «ИнжКонтур Бета»"])
    metadata.append(["Контрагент", "АО «Городские инженерные системы»"])
    metadata.append(["Общая сумма по реестру", "1 180 300,00 руб."])
    workbook.save(xlsx_path)

    docx_path = directory / "synthetic_acceptance_act.docx"
    document = Document()
    document.add_heading("Акт приёмки выполненных работ № А-024/26", level=1)
    for line in (
        "Номер акта: А-024/26",
        "Дата акта: 07.04.2026",
        "Договор: КД240315",
        "Исполнитель: ООО «ИнжКонтур Бета»",
        "Заказчик: АО «Городские инженерные системы»",
        "Итого к оплате: 1 180 300,00 руб.",
    ):
        document.add_paragraph(line)
    document.add_heading("Перечень выполненных работ", level=2)
    table = document.add_table(rows=1, cols=3)
    for cell, text in zip(table.rows[0].cells, ("Описание", "Количество", "Сумма, руб.")):
        cell.text = text
    for _, description, quantity, amount in work_rows:
        row = (description, str(quantity), f"{amount:,}".replace(",", " "))
        for cell, text in zip(table.add_row().cells, row):
            cell.text = text
    document.save(docx_path)

    documents = [
        (kfz_path.name, kfz_path.read_bytes(), "application/pdf"),
        (xlsx_path.name, xlsx_path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (docx_path.name, docx_path.read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ]
    if not compact_linking:
        png = FIXTURE_ROOT / "01_borderless.png"
        documents.append((png.name, png.read_bytes(), "image/png"))
    return documents


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wait_for_project(client: httpx.Client, base: str, project_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"{base}/api/projects/{project_id}")
        require(response.status_code == 200, f"Project poll failed: {response.status_code}")
        project = response.json()
        stages = project.get("stages", {})
        all_stages_terminal = all(
            stages.get(name, {}).get("status") in {"completed", "failed", "blocked"}
            for name in ("parser", "extraction", "linking")
        )
        if project["status"] in {"completed", "partial", "failed"} or all_stages_terminal:
            return project
        time.sleep(2)
    raise TimeoutError(f"Project {project_id} did not finish in {timeout_seconds} seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084", help="Gateway URL")
    parser.add_argument("--timeout", type=int, default=1800, help="Maximum end-to-end wait in seconds")
    parser.add_argument("--compact-linking", action="store_true", help="Use three synthetic documents and one row each for a bounded live LLM check")
    args = parser.parse_args()
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "synthetic-only",
        "external_llm_consent": True,
        "checks": [],
    }

    source_files: dict[str, bytes] = {}
    pdf_path = FIXTURE_ROOT / "10_mixed_native_and_scan.pdf"
    if not args.compact_linking:
        require(pdf_path.is_file(), f"Missing synthetic repository fixture: {pdf_path}")
        source_files[pdf_path.name] = pdf_path.read_bytes()

    with tempfile.TemporaryDirectory(prefix="phystech-trace-e2e-") as scratch:
        extras = make_synthetic_documents(Path(scratch), compact_linking=args.compact_linking)
        source_files.update({name: data for name, data, _ in extras})
        kfz_file = next(item for item in extras if item[0] == "synthetic_kfz_report.pdf")
        primary_uploads = [] if args.compact_linking else [(pdf_path.name, source_files[pdf_path.name], "application/pdf")]
        primary_uploads.extend(item for item in extras if item[0] != kfz_file[0])
        if not args.compact_linking:
            # The repeated PNG deliberately exercises Parser's content-addressed duplicate path.
            image = next(item for item in extras if item[0].lower().endswith(".png"))
            primary_uploads.append(image)

        with httpx.Client(timeout=httpx.Timeout(45, connect=8), follow_redirects=False) as client:
            base = args.base_url.rstrip("/")
            for port, service in ((8081, "document-parser"), (8082, "structured-extraction"), (8083, "document-linking")):
                for route in ("/health", "/openapi.json", "/docs"):
                    response = client.get(f"http://127.0.0.1:{port}{route}")
                    require(response.status_code == 200, f"{service}{route} returned {response.status_code}")
                    if route == "/health" and service == "document-linking":
                        report["linking_model_configured"] = bool(response.json().get("llm", {}).get("configured"))
                    if route == "/openapi.json":
                        body = response.json()
                        require(str(body.get("openapi", "")).startswith("3."), f"{service} OpenAPI document is invalid")
            report["checks"].append("Parser, Extraction and Linking health/OpenAPI/Swagger endpoints")

            frontend = client.get("http://127.0.0.1:8080/")
            require(frontend.status_code == 200 and "Phystech Trace" in frontend.text, "Vue frontend did not serve the application")
            report["checks"].append("Vue production frontend is served")

            gateway_health = client.get(f"{base}/health")
            require(gateway_health.status_code == 200, f"Gateway health returned {gateway_health.status_code}: {gateway_health.text[:500]}")
            openapi = client.get(f"{base}/openapi.json")
            require(openapi.status_code == 200 and str(openapi.json().get("openapi", "")).startswith("3."), "Gateway OpenAPI endpoint is invalid")
            gateway_docs = client.get(f"{base}/docs")
            require(gateway_docs.status_code == 200 and "swagger-ui" in gateway_docs.text.lower(), "Gateway Swagger UI is unavailable")
            report["checks"].append("Gateway health, Swagger UI and OpenAPI endpoints")

            created = client.post(f"{base}/api/projects", json={
                "name": f"Synthetic E2E {datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                "data_classification": "synthetic",
                "allow_external_llm": True,
            })
            require(created.status_code == 201, f"Project creation failed: {created.status_code} {created.text[:1000]}")
            project_id = created.json()["id"]
            report["project_id"] = project_id

            kfz_upload = client.post(
                f"{base}/api/projects/{project_id}/documents",
                data={"role": "kfz"},
                files={"files": (kfz_file[0], kfz_file[1], kfz_file[2])},
            )
            require(kfz_upload.status_code == 201, f"KFZ upload failed: {kfz_upload.status_code} {kfz_upload.text[:1000]}")

            primary_upload = client.post(
                f"{base}/api/projects/{project_id}/documents",
                data={"role": "primary"},
                files=[("files", (name, data, mime)) for name, data, mime in primary_uploads],
            )
            require(primary_upload.status_code == 201, f"Primary documents upload failed: {primary_upload.status_code} {primary_upload.text[:1000]}")
            primary_body = primary_upload.json()
            if not args.compact_linking:
                require(sum(1 for row in primary_body["documents"] if row.get("duplicate")) == 1, "Duplicate image upload was not detected")
            project = client.get(f"{base}/api/projects/{project_id}").json()
            expected_documents = 3 if args.compact_linking else 5
            require(len(project["documents"]) == expected_documents, f"Expected {expected_documents} uploaded documents, got {len(project['documents'])}")
            if args.compact_linking:
                report["checks"].append("Bounded live Linking set: synthetic PDF, XLSX and DOCX with one known matching row")
            else:
                report["checks"].append("Multipart upload for PDF/XLSX/DOCX/PNG and duplicate detection")

            started = client.post(f"{base}/api/projects/{project_id}/process")
            require(started.status_code == 202, f"Processing did not start: {started.status_code} {started.text[:500]}")
            project = wait_for_project(client, base, project_id, args.timeout)
            parser_retries = 0
            while project["stages"]["parser"]["status"] == "failed" and parser_retries < 4:
                retry_response = client.post(f"{base}/api/projects/{project_id}/retry", params={"stage": "parser"})
                require(retry_response.status_code == 202, f"Parser retry did not start: {retry_response.status_code} {retry_response.text[:500]}")
                parser_retries += 1
                project = wait_for_project(client, base, project_id, min(args.timeout, 600))
            if parser_retries:
                report["parser_retries"] = parser_retries
                report["checks"].append("Failed or stale empty Parser result was retried through Gateway")

            require(project["stages"]["parser"]["status"] == "completed", f"Parser stage failed: {project['stages']['parser']}")
            require(project["stages"]["extraction"]["status"] == "completed", f"Extraction stage failed: {project['stages']['extraction']}")
            report["extraction_mode"] = project["stages"]["extraction"].get("mode")
            docs = project["documents"]
            require(len(docs) == expected_documents, "Document count changed during orchestration")
            report["document_results"] = []
            extraction_ids: dict[str, str] = {}
            extractions_by_document_id: dict[str, dict[str, Any]] = {}
            locator_summary: dict[str, dict[str, bool]] = {}
            for doc in docs:
                require(doc.get("has_parser_result"), f"No persisted Parser result for {doc['file_name']}")
                result_response = client.get(f"{base}/api/projects/{project_id}/documents/{doc['id']}/result")
                require(result_response.status_code == 200, f"Could not read saved result for {doc['file_name']}")
                result = result_response.json()
                parser_result = result["parser_result"]
                extraction = result["extraction"]
                require(parser_result and parser_result.get("document_id") == doc["document_id"], f"Parser document ID changed for {doc['file_name']}")
                require(parser_result.get("phystech_trace", {}).get("source_file_id") == doc["document_id"], f"Source trace was lost for {doc['file_name']}")
                parser_parts = parser_result.get("parts") or (parser_result.get("visual_layout") or {}).get("parts", [])
                require(isinstance(parser_parts, list) and parser_parts, f"Parser returned no source parts for {doc['file_name']}")
                require(extraction and extraction.get("document_id") == doc["document_id"], f"Extraction changed the Parser document ID for {doc['file_name']}")
                require(str(extraction.get("schema_version", "")).startswith("1.2."), f"Unexpected Extraction schema version for {doc['file_name']}")
                require(extraction.get("extraction_id"), f"Extraction result was not persisted for {doc['file_name']}")

                nodes = list(walk(parser_result))
                has_pdf_bbox = any((node.get("bbox") is not None) and (node.get("page_no") is not None) for node in nodes)
                has_xlsx_address = any(any(node.get(key) for key in ("coordinate", "address", "cell_address")) for node in nodes)
                has_provenance = any(isinstance(node.get("provenance"), (dict, list)) for node in nodes)
                extraction_ids[doc["document_id"]] = extraction["extraction_id"]
                extractions_by_document_id[doc["document_id"]] = extraction
                locator_summary[doc["file_name"]] = {"pdf_page_bbox": has_pdf_bbox, "xlsx_cell_address": has_xlsx_address, "parser_provenance": has_provenance}
                report["document_results"].append({
                    "name": doc["file_name"], "role": doc["role"], "document_id": doc["document_id"],
                    "parts": len(parser_parts), "extraction_id": extraction["extraction_id"],
                    "schema_version": extraction["schema_version"], "classification": extraction.get("classification"),
                    "locators": locator_summary[doc["file_name"]],
                })

                saved_source = client.get(f"{base}/api/projects/{project_id}/sources/{doc['document_id']}")
                require(saved_source.status_code == 200, f"Gateway source resolution failed for {doc['file_name']}")
                require(hashlib.sha256(saved_source.content).hexdigest() == hashlib.sha256(source_files[doc["file_name"]]).hexdigest(), f"Source bytes changed for {doc['file_name']}")

            require(locator_summary.get("synthetic_primary_register.xlsx", {}).get("xlsx_cell_address"), "XLSX cell address provenance was not preserved")
            require(any(item["locators"]["pdf_page_bbox"] for item in report["document_results"] if item["name"].lower().endswith(".pdf")), "PDF page/bbox provenance was not preserved")
            kfz_extraction = next(extractions_by_document_id[doc["document_id"]] for doc in docs if doc["file_name"] == "synthetic_kfz_report.pdf")
            act_extraction = next(extractions_by_document_id[doc["document_id"]] for doc in docs if doc["file_name"] == "synthetic_acceptance_act.docx")
            require(kfz_extraction.get("document_type") == "kfz_report", "Synthetic KFZ source was not classified as a KFZ report")
            require(act_extraction.get("document_type") == "act", "Synthetic primary DOCX was not classified as an act")
            kfz_contract = (kfz_extraction.get("fields", {}).get("contract_reference") or {}).get("value")
            act_contract = (act_extraction.get("fields", {}).get("contract_reference") or {}).get("value")
            require(kfz_contract == "КД240315" and act_contract == kfz_contract, "Known contract reference was not extracted from both the KFZ PDF and DOCX act")
            report["checks"].append("Known synthetic KFZ, act and contract reference values were extracted from the source files")
            pdf_doc = next(doc for doc in docs if doc["file_name"].lower().endswith(".pdf"))
            pdf_page = client.get(f"{base}/api/projects/{project_id}/sources/{pdf_doc['document_id']}/pages/1")
            require(pdf_page.status_code == 200 and pdf_page.headers.get("content-type", "").startswith("image/png"), "PDF page source navigation did not return a rendered image")
            report["checks"].append("Persisted parser/extraction results, stable IDs, XLSX cell and PDF bbox provenance, source file and page re-resolution")

            bad_contract = client.post("http://127.0.0.1:8082/api/extractions", json={"parser_result": {}})
            require(bad_contract.status_code == 422 and bad_contract.json().get("code") == "PARSER_CONTRACT_INVALID", "Structured Extraction did not diagnose an invalid parser contract")
            report["checks"].append("Invalid Parser payload is rejected with a diagnostic contract error")

            first_ids = {doc["document_id"]: doc.get("extraction_id") for doc in project["documents"]}
            linking = project["stages"]["linking"]
            if linking["status"] == "completed":
                linking_result = project.get("linking_result")
                require(isinstance(linking_result, dict), "Completed Linking stage has no result")
                require(linking_result.get("input_documents"), "Linking result has no input documents")
                require(all(item.get("document_id") in extraction_ids for item in linking_result["input_documents"]), "Linking result references an unknown document")
                llm = linking_result.get("processing_metadata", {}).get("llm", {})
                require(llm.get("provider") == "Polza AI" and llm.get("calls", 0) > 0, "Linking did not record a real Polza model call")
                evidence_count = 0
                resolved_evidence_sides = 0
                for link in linking_result.get("links", []):
                    for evidence in link.get("evidence", []):
                        for side, expected_document_id in (("source", link["source_document_id"]), ("target", link["target_document_id"])):
                            citation = evidence.get(side) or {}
                            document_id = citation.get("document_id")
                            path = citation.get("path")
                            require(document_id == expected_document_id, f"Linking {side} evidence points to the wrong document")
                            require(document_id in extractions_by_document_id and isinstance(path, str) and path, f"Linking {side} evidence has no resolvable document path")
                            actual_value = resolve_json_path(extractions_by_document_id[document_id], path)
                            require(actual_value == citation.get("raw_value"), f"Linking {side} evidence value does not match {document_id}:{path}")
                            provenance = citation.get("provenance")
                            require(isinstance(provenance, dict) and provenance.get("document_id") == document_id, f"Linking {side} evidence lost source provenance")
                            evidence_count += 1
                            resolved_evidence_sides += 1

                report["linking"] = {
                    "status": "completed", "model_provider": llm.get("provider"), "model": llm.get("model"),
                    "model_calls": llm.get("calls"), "links": len(linking_result.get("links", [])),
                    "evidence_sides": resolved_evidence_sides,
                    "pending_review": sum(1 for link in linking_result.get("links", []) if link.get("status") in {"proposed", "review"}),
                }
                if args.compact_linking:
                    relations = {link.get("relationship_type") for link in linking_result.get("links", [])}
                    expected_relations = {"report_summarizes_registry", "act_validates_registry", "act_contains_line_item"}
                    require(expected_relations <= relations, f"Known synthetic relations were not found: {sorted(expected_relations - relations)}")
                    line_link = next(link for link in linking_result["links"] if link.get("relationship_type") == "act_contains_line_item")
                    require(any(
                        evidence.get("source", {}).get("path") == "line_items[0].description.value"
                        and evidence.get("target", {}).get("path") == "tables[0].rows[0].description.value"
                        and evidence.get("source", {}).get("raw_value") == evidence.get("target", {}).get("raw_value")
                        for evidence in line_link.get("evidence", [])
                    ), "Known act-to-register row relation has no equal, resolvable description evidence")
                    report["linking"]["known_relations"] = sorted(expected_relations)
                    report["checks"].append("Live Linking found the expected report, act, registry and matching line-item relationships")
                if linking_result.get("links") and evidence_count:
                    report["status"] = "full-e2e-passed"
                    report["checks"].append("Live Linking relations resolve back to exact extracted values and their source provenance")
                    exit_code = 0
                else:
                    report["status"] = "linking-completed-without-supported-relations"
                    report["checks"].append("Live Linking completed successfully but produced no relation with evidence")
                    exit_code = 3
            else:
                message = json.dumps(linking.get("error", {}), ensure_ascii=False)
                require(linking["status"] in {"failed", "blocked"}, f"Unexpected Linking status: {linking}")
                # Retry Linking and prove successful Parser/Extraction stages remain saved.
                retry = client.post(f"{base}/api/projects/{project_id}/retry", params={"stage": "linking"})
                require(retry.status_code == 202, f"Linking retry did not start: {retry.status_code} {retry.text[:500]}")
                retry_deadline = time.monotonic() + min(args.timeout, 180)
                while time.monotonic() < retry_deadline:
                    project = client.get(f"{base}/api/projects/{project_id}").json()
                    if project["stages"]["linking"]["status"] in {"failed", "blocked", "completed"} and project["status"] != "running":
                        break
                    time.sleep(2)
                require(project["stages"]["parser"]["status"] == "completed", "Parser result was not retained after retry")
                require(project["stages"]["extraction"]["status"] == "completed", "Extraction result was not retained after retry")
                after_ids = {doc["document_id"]: doc.get("extraction_id") for doc in project["documents"]}
                require(first_ids == after_ids, "Linking retry caused Extraction to rerun or lose saved extraction IDs")
                report["status"] = "partial-e2e-passed-linking-unavailable"
                report["linking"] = {"status": project["stages"]["linking"]["status"], "initial_error": linking.get("error"), "retry_error": project["stages"]["linking"].get("error"), "reason": "Live Linking API failure was recorded; successful Parser and Extraction outputs were retained"}
                report["checks"].append("Linking failure is visible; retry preserves completed Parser and Extraction results")
                exit_code = 2

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["elapsed_seconds"] = round((datetime.fromisoformat(report["finished_at"]) - datetime.fromisoformat(report["started_at"])).total_seconds(), 2)
    results_dir = TRACE_ROOT / "tests" / "e2e" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "latest-run.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "project_id": report.get("project_id"), "documents": len(report.get("document_results", [])), "report": str(report_path), "checks": report["checks"], "linking": report.get("linking")}, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"E2E FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        raise
