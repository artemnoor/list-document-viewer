from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import psycopg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent
CONTRACTS_ROOT = ROOT / "contracts" if (ROOT / "contracts").is_dir() else ROOT.parent / "contracts"
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://trace:trace@postgres:5432/phystech_trace")
PARSER_URL = os.getenv("PARSER_URL", "http://document-parser:18765").rstrip("/")
EXTRACTION_URL = os.getenv("EXTRACTION_URL", "http://structured-extraction:8082").rstrip("/")
LINKING_URL = os.getenv("LINKING_URL", "http://document-linking:3000").rstrip("/")
RECONCILIATION_URL = os.getenv("RECONCILIATION_URL", "http://reconciliation-engine:8000").rstrip("/")
LINKING_TOKEN = os.getenv("API_BEARER_TOKEN", "phystech_trace_local_api_token_32_chars")
POLL_INTERVAL = max(0.25, float(os.getenv("POLL_INTERVAL_SECONDS", "2")))
LINKING_POLL_INTERVAL = max(5.0, float(os.getenv("LINKING_POLL_INTERVAL_SECONDS", "10")))
PARSER_TIMEOUT = max(60, int(os.getenv("PARSER_TIMEOUT_SECONDS", "1800")))
MAX_UPLOAD_BYTES = min(25 * 1024 * 1024, int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))))
ALLOWED_CLASSIFICATIONS = {"public", "synthetic", "anonymized"}
ACTIVE_TASKS: dict[str, asyncio.Task] = {}
CLIENT: httpx.AsyncClient | None = None
CONTRACTS = {
    "parser": json.loads((CONTRACTS_ROOT / "parser-to-extraction-v1.schema.json").read_text(encoding="utf-8")),
    "extraction": json.loads((CONTRACTS_ROOT / "structured-extraction-1.2.0.schema.json").read_text(encoding="utf-8")),
    "linking": json.loads((CONTRACTS_ROOT / "document-linking-1.2.0.schema.json").read_text(encoding="utf-8")),
}
VALIDATORS = {name: Draft202012Validator(schema) for name, schema in CONTRACTS.items()}


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)


def now():
    return datetime.now(timezone.utc).isoformat()


def initial_stages():
    return {
        "parser": {"status": "pending", "completed": 0, "total": 0, "updated_at": now()},
        "extraction": {"status": "pending", "completed": 0, "total": 0, "updated_at": now()},
        "linking": {"status": "pending", "completed": 0, "total": 0, "updated_at": now()},
        "reconciliation": {"status": "pending", "completed": 0, "total": 0, "updated_at": now()},
    }


def mark_reconciliation_pending(stages: dict) -> dict:
    updated = dict(stages)
    previous = updated.get("reconciliation", {})
    updated["reconciliation"] = {
        **previous, "status": "pending", "completed": 0, "error": None, "updated_at": now(),
    }
    return updated


def should_resume_linking_job(job_status: str | None) -> bool:
    return job_status != "completed"


def should_reuse_saved_linking_result(retry_stage: str | None) -> bool:
    return retry_stage == "reconciliation"


def ensure_database():
    with db() as conn:
        conn.execute("""
          CREATE TABLE IF NOT EXISTS trace_projects (
            id text PRIMARY KEY, name text NOT NULL, data_classification text NOT NULL,
            allow_external_llm boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL DEFAULT 'draft',
            stages jsonb NOT NULL, linking_job_id text, linking_result jsonb,
            reconciliation_result jsonb, last_error jsonb
          )
        """)
        conn.execute("""
          CREATE TABLE IF NOT EXISTS trace_documents (
            id text PRIMARY KEY, project_id text NOT NULL REFERENCES trace_projects(id) ON DELETE CASCADE,
            role text NOT NULL CHECK (role IN ('kfz','primary')), file_name text NOT NULL,
            parser_document_id text NOT NULL, parser_state text NOT NULL DEFAULT 'queued',
            parser_result jsonb, parser_error jsonb, extraction_result jsonb,
            extraction_error jsonb, created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (project_id, parser_document_id)
          )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS trace_documents_project_idx ON trace_documents(project_id,created_at)")
        conn.execute("ALTER TABLE trace_projects ADD COLUMN IF NOT EXISTS reconciliation_result jsonb")
        conn.commit()


def project_row(project_id: str):
    with db() as conn:
        return conn.execute("SELECT * FROM trace_projects WHERE id=%s", (project_id,)).fetchone()


def document_rows(project_id: str):
    with db() as conn:
        return conn.execute("SELECT * FROM trace_documents WHERE project_id=%s ORDER BY created_at,id", (project_id,)).fetchall()


def update_stage(project_id: str, stage: str, **patch):
    with db() as conn:
        row = conn.execute("SELECT stages,status FROM trace_projects WHERE id=%s", (project_id,)).fetchone()
        if not row:
            return
        stages = dict(row["stages"])
        state = {**stages.get(stage, {}), **patch, "updated_at": now()}
        stages[stage] = state
        conn.execute("UPDATE trace_projects SET stages=%s,status='running',updated_at=now() WHERE id=%s", (Jsonb(stages), project_id))
        conn.commit()


def update_document(document_id: str, **fields):
    allowed = {"parser_state", "parser_result", "parser_error", "extraction_result", "extraction_error"}
    if not fields or set(fields) - allowed:
        raise ValueError("Invalid document update fields")
    assignments, values = [], []
    for key, value in fields.items():
        assignments.append(f"{key}=%s")
        values.append(Jsonb(value) if key.endswith("_result") or key.endswith("_error") else value)
    values.append(document_id)
    with db() as conn:
        conn.execute(f"UPDATE trace_documents SET {','.join(assignments)} WHERE id=%s", values)
        conn.commit()


def project_payload(project_id: str):
    project = project_row(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    documents = document_rows(project_id)
    return {
        "id": project["id"], "name": project["name"], "data_classification": project["data_classification"],
        "allow_external_llm": project["allow_external_llm"], "status": project["status"],
        "created_at": project["created_at"].isoformat(), "updated_at": project["updated_at"].isoformat(),
        "stages": project["stages"], "last_error": project["last_error"],
        "linking_job_id": project["linking_job_id"], "linking_result": project["linking_result"],
        "reconciliation_result": project["reconciliation_result"],
        "documents": [
            {"id": doc["id"], "role": doc["role"], "file_name": doc["file_name"],
             "document_id": doc["parser_document_id"], "parser_state": doc["parser_state"],
             "parser_error": doc["parser_error"], "has_parser_result": doc["parser_result"] is not None,
             "extraction_id": (doc["extraction_result"] or {}).get("extraction_id"),
             "document_type": (doc["extraction_result"] or {}).get("document_type"),
             "extraction_error": doc["extraction_error"],
             "source_url": f"/api/projects/{project_id}/sources/{doc['parser_document_id']}"}
            for doc in documents
        ],
    }


def contract_errors(name: str, value, limit: int = 30):
    issues = []
    for error in VALIDATORS[name].iter_errors(value):
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        issues.append({"path": path, "message": error.message})
        if len(issues) >= limit:
            break
    return issues


def set_project_status(project_id: str, status: str, error=None, linking_job_id=None, linking_result=None, reconciliation_result=None):
    with db() as conn:
        conn.execute(
            "UPDATE trace_projects SET status=%s,last_error=%s,linking_job_id=COALESCE(%s,linking_job_id),linking_result=COALESCE(%s,linking_result),reconciliation_result=COALESCE(%s,reconciliation_result),updated_at=now() WHERE id=%s",
            (status, Jsonb(error) if error is not None else None, linking_job_id,
             Jsonb(linking_result) if linking_result is not None else None,
             Jsonb(reconciliation_result) if reconciliation_result is not None else None, project_id),
        )
        conn.commit()


def invalidate_reconciliation(project_id: str, linking_result: dict | None = None):
    with db() as conn:
        row = conn.execute("SELECT stages FROM trace_projects WHERE id=%s", (project_id,)).fetchone()
        if not row:
            return
        stages = mark_reconciliation_pending(dict(row["stages"]))
        conn.execute(
            "UPDATE trace_projects SET stages=%s,status='partial',reconciliation_result=NULL,linking_result=COALESCE(%s,linking_result),updated_at=now() WHERE id=%s",
            (Jsonb(stages), Jsonb(linking_result) if linking_result is not None else None, project_id),
        )
        conn.commit()


def auth_headers():
    return {"Authorization": f"Bearer {LINKING_TOKEN}"}


async def parser_analysis(client: httpx.AsyncClient, parser_id: str, retry: bool):
    if retry:
        response = await client.post(f"{PARSER_URL}/api/documents/{parser_id}/retry", timeout=15)
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Document Parser retry failed ({response.status_code}): {response.text[:500]}")
    deadline = time.monotonic() + PARSER_TIMEOUT
    while time.monotonic() < deadline:
        response = await client.get(f"{PARSER_URL}/api/documents/{parser_id}/analysis", timeout=15)
        if response.status_code != 200:
            raise RuntimeError(f"Document Parser analysis returned HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        state = body.get("state")
        if state == "ready" and isinstance(body.get("result"), dict):
            result = body["result"]
            parts = result.get("parts") or (result.get("visual_layout") or {}).get("parts", [])
            if not isinstance(parts, list) or not parts:
                raise RuntimeError(json.dumps({
                    "code": "PARSER_RESULT_NO_PARTS",
                    "status": result.get("status"),
                    "warnings": result.get("warnings", []),
                }, ensure_ascii=False))
            return result
        if state == "error":
            raise RuntimeError(body.get("error") or body.get("processing_status") or "Document Parser reported an error")
        if state not in {"queued", "processing", "pending", None}:
            raise RuntimeError(f"Document Parser returned an unsupported state: {state}")
        await asyncio.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Document Parser exceeded {PARSER_TIMEOUT} seconds")


def reconciliation_targets(kfz_extraction: dict):
    """Select only explicit currency amount wrappers from the saved KFZ extraction."""
    targets = []
    indicators = kfz_extraction.get("indicators") or []
    for key, wrapper in (kfz_extraction.get("fields") or {}).items():
        value = wrapper.get("value") if isinstance(wrapper, dict) else None
        if not isinstance(value, dict) or "amount" not in value or not value.get("currency"):
            continue
        label = str(wrapper.get("label") or key)
        source_path = "#/fields/" + key.replace("~", "~0").replace("/", "~1")
        provenance = wrapper.get("provenance") or {}
        # Extraction may publish the same source value as both a field and an
        # indicator. The Reconciliation Engine canonicalizes duplicate evidence
        # to the indicator fact, so bind the target to that exact locator.
        for index, indicator in enumerate(indicators):
            extracted = indicator.get("extracted") if isinstance(indicator, dict) else None
            indicator_provenance = extracted.get("provenance") if isinstance(extracted, dict) else None
            if (
                isinstance(extracted, dict)
                and extracted.get("value") == value
                and isinstance(indicator_provenance, dict)
                and indicator_provenance.get("source_ref") == provenance.get("source_ref")
                and indicator_provenance.get("source_part_id") == provenance.get("source_part_id")
            ):
                source_path = f"#/indicators/{index}/extracted"
                break
        targets.append({
            "target_id": "kfz-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "kfz_document_id": kfz_extraction["document_id"],
            "kfz_source_path": source_path,
            "label": label,
            "description": f"Reported monetary indicator '{label}' from the saved KФЗ extraction.",
            "currency": value.get("currency"),
            "amount_basis": "unspecified",
            "economic_measure": "unspecified",
            "period_basis": "document_period",
            "rounding_scale": 2,
        })
    return targets


async def reconcile_saved_project(client: httpx.AsyncClient, project: dict, docs: list[dict], linking_result: dict):
    kfz = next((doc for doc in docs if doc["role"] == "kfz"), None)
    if not kfz or not kfz.get("extraction_result"):
        raise RuntimeError("Saved KФЗ extraction is unavailable for Reconciliation")
    targets = reconciliation_targets(kfz["extraction_result"])
    if not targets:
        raise RuntimeError("KФЗ extraction contains no explicit currency amount targets; Reconciliation was not run")

    reporting_period = (kfz["extraction_result"].get("fields") or {}).get("reporting_period", {})
    period_value = reporting_period.get("value") if isinstance(reporting_period, dict) else None
    if not isinstance(period_value, dict):
        period_value = {}
    context = {
        "period_start": period_value.get("start"),
        "period_end": period_value.get("end"),
        "targets": targets,
        "data_classification": "anonymized" if project["data_classification"] in {"synthetic", "anonymized"} else "open",
        "external_llm_allowed": bool(project["allow_external_llm"]),
        "rounding_mode": "ROUND_HALF_UP",
    }
    payload = {
        "contract_version": "1.0.0",
        "extraction_results": [doc["extraction_result"] for doc in docs],
        "linking_result": linking_result,
        "context": context,
    }
    response = await client.post(f"{RECONCILIATION_URL}/api/v1/reconciliations", json=payload, timeout=240)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Reconciliation Engine returned HTTP {response.status_code}: {response.text[:2000]}")
    created = response.json()
    reconciliation_id = created.get("reconciliation_id")
    if not reconciliation_id:
        raise RuntimeError("Reconciliation Engine response has no reconciliation_id")
    saved = await client.get(f"{RECONCILIATION_URL}/api/v1/reconciliations/{reconciliation_id}", timeout=30)
    if saved.status_code != 200:
        raise RuntimeError(f"Reconciliation result could not be reread ({saved.status_code}): {saved.text[:1000]}")
    result = saved.json()
    if result.get("reconciliation_id") != reconciliation_id:
        raise RuntimeError("Reconciliation reread returned a different result ID")
    return result


async def process_project(project_id: str, retry_stage: str | None = None):
    client = CLIENT
    if client is None:
        return
    try:
        project = project_row(project_id)
        if not project:
            return
        docs = document_rows(project_id)
        kfz = [doc for doc in docs if doc["role"] == "kfz"]
        primary = [doc for doc in docs if doc["role"] == "primary"]
        if len(kfz) != 1 or not primary:
            message = "Комплект должен содержать один файл КФЗ и хотя бы один первичный документ."
            set_project_status(project_id, "draft", {"code": "INCOMPLETE_DOCUMENT_SET", "message": message})
            return

        # Parser stage: reuse successful results; retry only files that have no saved result.
        pending_parser = [doc for doc in docs if doc["parser_result"] is None]
        if pending_parser:
            update_stage(project_id, "parser", status="running", completed=len(docs) - len(pending_parser), total=len(docs), error=None)
            for doc in pending_parser:
                try:
                    result = await parser_analysis(client, doc["parser_document_id"], retry=retry_stage == "parser" and doc["parser_state"] == "error")
                    enriched = {
                        **result,
                        "document_id": doc["parser_document_id"],
                        "source_file_id": doc["parser_document_id"],
                        "phystech_trace": {
                            "contract_version": "1.0.0", "project_id": project_id,
                            "source_file_id": doc["parser_document_id"], "source_file_name": doc["file_name"], "document_role": doc["role"],
                        },
                    }
                    issues = contract_errors("parser", enriched)
                    if issues:
                        raise ValueError(json.dumps({"code": "PARSER_CONTRACT_INVALID", "diagnostics": issues}, ensure_ascii=False))
                    update_document(doc["id"], parser_state="ready", parser_result=enriched, parser_error=None)
                except Exception as exc:
                    error = {"code": "PARSER_STAGE_FAILED", "message": str(exc)[:2000]}
                    update_document(doc["id"], parser_state="error", parser_error=error)
                    update_stage(project_id, "parser", status="failed", completed=sum(1 for item in document_rows(project_id) if item["parser_result"] is not None), total=len(docs), error=error)
                    set_project_status(project_id, "partial", error)
                    return
                completed = sum(1 for item in document_rows(project_id) if item["parser_result"] is not None)
                update_stage(project_id, "parser", status="running", completed=completed, total=len(docs), error=None)
        update_stage(project_id, "parser", status="completed", completed=len(docs), total=len(docs), error=None)

        # Extraction stage: call the existing rules/LLM module for each saved parser result.
        docs = document_rows(project_id)
        pending_extraction = [doc for doc in docs if doc["extraction_result"] is None]
        if pending_extraction:
            extraction_mode = "rules_only"
            extraction_warning = None
            if project["allow_external_llm"] and project["data_classification"] in ALLOWED_CLASSIFICATIONS:
                try:
                    readiness = (await client.get(f"{EXTRACTION_URL}/health", timeout=10)).json().get("llm", {})
                    if readiness.get("configured"):
                        extraction_mode = "llm_assisted"
                    else:
                        extraction_warning = "Polza API key is not configured; extraction used rules_only. Linking may remain unavailable."
                except Exception:
                    extraction_warning = "Extraction LLM readiness could not be confirmed; extraction used rules_only."
            update_stage(project_id, "extraction", status="running", completed=len(docs) - len(pending_extraction), total=len(docs), error=None, mode=extraction_mode, warning=extraction_warning)
            for doc in pending_extraction:
                try:
                    response = await client.post(
                        f"{EXTRACTION_URL}/api/extractions",
                        json={"parser_result": doc["parser_result"], "mode": extraction_mode,
                              "data_classification": project["data_classification"], "allow_external_llm": project["allow_external_llm"]},
                        timeout=180,
                    )
                    if response.status_code != 201:
                        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"error": response.text[:1000]}
                        raise RuntimeError(json.dumps({"http_status": response.status_code, **body}, ensure_ascii=False))
                    extraction = response.json().get("extraction")
                    issues = contract_errors("extraction", extraction)
                    if issues:
                        raise ValueError(json.dumps({"code": "EXTRACTION_CONTRACT_INVALID", "diagnostics": issues}, ensure_ascii=False))
                    if extraction.get("document_id") != doc["parser_document_id"]:
                        raise ValueError(f"document_id changed at extraction boundary: {extraction.get('document_id')}")
                    update_document(doc["id"], extraction_result=extraction, extraction_error=None)
                except Exception as exc:
                    error = {"code": "EXTRACTION_STAGE_FAILED", "message": str(exc)[:2000]}
                    update_document(doc["id"], extraction_error=error)
                    update_stage(project_id, "extraction", status="failed", completed=sum(1 for item in document_rows(project_id) if item["extraction_result"] is not None), total=len(docs), error=error)
                    set_project_status(project_id, "partial", error)
                    return
                completed = sum(1 for item in document_rows(project_id) if item["extraction_result"] is not None)
                update_stage(project_id, "extraction", status="running", completed=completed, total=len(docs), error=None, mode=extraction_mode, warning=extraction_warning)
        else:
            extraction_mode = project.get("stages", {}).get("extraction", {}).get("mode", "rules_only")
            extraction_warning = project.get("stages", {}).get("extraction", {}).get("warning")
        update_stage(project_id, "extraction", status="completed", completed=len(docs), total=len(docs), error=None, mode=extraction_mode, warning=extraction_warning)

        docs = document_rows(project_id)
        extractions = [doc["extraction_result"] for doc in docs]
        if should_reuse_saved_linking_result(retry_stage):
            linking_result = project.get("linking_result")
            if not isinstance(linking_result, dict):
                error = {"code": "SAVED_LINKING_RESULT_MISSING", "message": "A saved Linking result is required before Reconciliation can be retried."}
                update_stage(project_id, "reconciliation", status="failed", completed=0, total=1, error=error)
                set_project_status(project_id, "partial", error)
                return
            issues = contract_errors("linking", linking_result)
            if issues:
                error = {"code": "LINKING_CONTRACT_INVALID", "diagnostics": issues}
                update_stage(project_id, "reconciliation", status="failed", completed=0, total=1, error=error)
                set_project_status(project_id, "partial", error)
                return
            project_document_ids = {doc["parser_document_id"] for doc in docs}
            if any(item.get("document_id") not in project_document_ids for item in linking_result.get("input_documents", [])):
                error = {"code": "LINKING_DOCUMENT_OUTSIDE_PROJECT", "message": "Saved Linking result refers to a document outside this project."}
                update_stage(project_id, "reconciliation", status="failed", completed=0, total=1, error=error)
                set_project_status(project_id, "partial", error)
                return
            update_stage(project_id, "linking", status="completed", completed=1, total=1, error=None)
            update_stage(project_id, "reconciliation", status="running", completed=0, total=1, error=None)
            try:
                reconciliation_result = await reconcile_saved_project(client, project, docs, linking_result)
                update_stage(project_id, "reconciliation", status="completed", completed=1, total=1, error=None)
                set_project_status(project_id, "completed", reconciliation_result=reconciliation_result)
            except Exception as reconciliation_exc:
                error = {"code": "RECONCILIATION_STAGE_FAILED", "message": str(reconciliation_exc)[:2000]}
                update_stage(project_id, "reconciliation", status="failed", completed=0, total=1, error=error)
                set_project_status(project_id, "partial", error)
            return
        if not project["allow_external_llm"] or project["data_classification"] not in ALLOWED_CLASSIFICATIONS:
            error = {"code": "EXTERNAL_LLM_CONSENT_REQUIRED", "message": "Document Linking uses an external LLM. Explicit consent is required for public, synthetic, or anonymized data."}
            update_stage(project_id, "linking", status="blocked", completed=0, total=1, error=error)
            set_project_status(project_id, "partial", error)
            return

        update_stage(project_id, "linking", status="running", completed=0, total=1, error=None)
        try:
            existing_job = project.get("linking_job_id")
            resume_existing_job = False
            if retry_stage == "linking" and existing_job:
                existing_response = await client.get(
                    f"{LINKING_URL}/api/linking-jobs/{existing_job}", headers=auth_headers(), timeout=30,
                )
                if existing_response.status_code == 200:
                    resume_existing_job = should_resume_linking_job(existing_response.json().get("status"))
            if resume_existing_job:
                response = await client.post(f"{LINKING_URL}/api/linking-jobs/{existing_job}/resume", headers=auth_headers(), timeout=30)
            else:
                signature = ":".join(f"{item['document_id']}:{item['extraction_id']}" for item in extractions)
                request_hash = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
                retry_nonce = f":retry:{uuid.uuid4()}" if retry_stage == "linking" else ""
                key = f"phystech-trace:{project_id}:{request_hash}{retry_nonce}"
                response = await client.post(
                    f"{LINKING_URL}/api/linking-jobs",
                    headers={**auth_headers(), "Idempotency-Key": key},
                    json={"documents": extractions, "data_classification": project["data_classification"], "allow_external_llm": True},
                    timeout=60,
                )
            if response.status_code not in (200, 202):
                body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"error": response.text[:1000]}
                raise RuntimeError(json.dumps({"http_status": response.status_code, **body}, ensure_ascii=False))
            job = response.json()
            job_id = job.get("job_id")
            if not job_id:
                # Idempotent API replays may return an already-completed job without a result field.
                raise RuntimeError("Document Linking returned no job_id")
            set_project_status(project_id, "running", linking_job_id=job_id)
            deadline = time.monotonic() + int(os.getenv("LINKING_TIMEOUT_SECONDS", "1800"))
            while time.monotonic() < deadline:
                job_response = await client.get(f"{LINKING_URL}/api/linking-jobs/{job_id}", headers=auth_headers(), timeout=30)
                if job_response.status_code != 200:
                    raise RuntimeError(f"Document Linking job poll failed ({job_response.status_code}): {job_response.text[:500]}")
                state = job_response.json()
                if state.get("status") == "completed" and isinstance(state.get("result"), dict):
                    linking_result = state["result"]
                    issues = contract_errors("linking", linking_result)
                    if issues:
                        raise ValueError(json.dumps({"code": "LINKING_CONTRACT_INVALID", "diagnostics": issues}, ensure_ascii=False))
                    if any(item.get("document_id") not in {doc["parser_document_id"] for doc in docs} for item in linking_result.get("input_documents", [])):
                        raise ValueError("Document Linking result refers to a document outside this project")
                    update_stage(project_id, "linking", status="completed", completed=1, total=1, error=None)
                    update_stage(project_id, "reconciliation", status="running", completed=0, total=1, error=None)
                    try:
                        reconciliation_result = await reconcile_saved_project(client, project, docs, linking_result)
                        update_stage(project_id, "reconciliation", status="completed", completed=1, total=1, error=None)
                        set_project_status(project_id, "completed", linking_result=linking_result, reconciliation_result=reconciliation_result)
                    except Exception as reconciliation_exc:
                        error = {"code": "RECONCILIATION_STAGE_FAILED", "message": str(reconciliation_exc)[:2000]}
                        update_stage(project_id, "reconciliation", status="failed", completed=0, total=1, error=error)
                        set_project_status(project_id, "partial", error, linking_result=linking_result)
                    return
                if state.get("status") == "failed":
                    raise RuntimeError(state.get("last_error") or "Document Linking job failed")
                await asyncio.sleep(LINKING_POLL_INTERVAL)
            raise TimeoutError("Document Linking exceeded the configured timeout")
        except Exception as exc:
            error = {"code": "LINKING_STAGE_FAILED", "message": str(exc)[:2000]}
            update_stage(project_id, "linking", status="failed", completed=0, total=1, error=error)
            set_project_status(project_id, "partial", error)
    except Exception as exc:
        error = {"code": "ORCHESTRATION_FAILED", "message": str(exc)[:2000]}
        set_project_status(project_id, "partial", error)
    finally:
        ACTIVE_TASKS.pop(project_id, None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global CLIENT
    ensure_database()
    CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
    with db() as conn:
        running = conn.execute("SELECT id FROM trace_projects WHERE status='running'").fetchall()
        for row in running:
            conn.execute("UPDATE trace_projects SET status='partial',updated_at=now() WHERE id=%s", (row["id"],))
            asyncio.create_task(_resume_later(row["id"]))
        conn.commit()
    yield
    await CLIENT.aclose()
    CLIENT = None


async def _resume_later(project_id: str):
    await asyncio.sleep(1)
    if project_id not in ACTIVE_TASKS:
        ACTIVE_TASKS[project_id] = asyncio.create_task(process_project(project_id))


app = FastAPI(title="Phystech Trace Gateway API", version="1.1.0", description="Projects, source uploads and durable Parser → Extraction → Linking → Reconciliation orchestration.", lifespan=lifespan)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data_classification: Literal["confidential", "public", "synthetic", "anonymized"] = "confidential"
    allow_external_llm: bool = False


class LinkDecision(BaseModel):
    status: Literal["confirmed", "rejected"]


@app.get("/health")
async def health():
    dependencies = {}
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        dependencies["postgres"] = "ok"
    except Exception as exc:
        dependencies["postgres"] = "unavailable"
        return {"status": "unavailable", "service": "gateway", "dependencies": dependencies, "error": str(exc)[:300]}
    if CLIENT is not None:
        for name, url in (("parser", PARSER_URL), ("extraction", EXTRACTION_URL), ("linking", LINKING_URL), ("reconciliation", RECONCILIATION_URL)):
            try:
                response = await CLIENT.get(f"{url}/health", timeout=5)
                dependencies[name] = "ok" if response.status_code == 200 else f"unavailable:{response.status_code}"
            except httpx.HTTPError:
                dependencies[name] = "unavailable"
    return {"status": "ok" if all(value == "ok" for value in dependencies.values()) else "degraded", "service": "gateway", "dependencies": dependencies}


@app.get("/api/projects")
def list_projects():
    with db() as conn:
        ids = conn.execute("SELECT id FROM trace_projects ORDER BY updated_at DESC").fetchall()
    return {"projects": [project_payload(row["id"]) for row in ids]}


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate):
    if payload.allow_external_llm and payload.data_classification not in ALLOWED_CLASSIFICATIONS:
        raise HTTPException(422, "External LLM is limited to public, synthetic or anonymized data")
    project_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO trace_projects(id,name,data_classification,allow_external_llm,stages) VALUES(%s,%s,%s,%s,%s)",
            (project_id, payload.name.strip(), payload.data_classification, payload.allow_external_llm, Jsonb(initial_stages())),
        )
        conn.commit()
    return project_payload(project_id)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return project_payload(project_id)


@app.post("/api/projects/{project_id}/documents", status_code=201)
async def upload_documents(project_id: str, role: Literal["kfz", "primary"] = Form(...), files: list[UploadFile] = File(...)):
    if not project_row(project_id):
        raise HTTPException(404, "Project not found")
    if not files:
        raise HTTPException(422, "Select at least one document")
    if role == "kfz" and len(files) > 1:
        raise HTTPException(422, "Upload one KFZ report per request")
    added = []
    assert CLIENT is not None
    for upload in files:
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if not data:
            raise HTTPException(422, f"{upload.filename or 'File'} is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{upload.filename or 'File'} exceeds 25 MiB")
        name = Path(upload.filename or "document").name[:200]
        response = await CLIENT.post(
            f"{PARSER_URL}/api/documents", content=data,
            headers={"X-File-Name": name, "Content-Type": upload.content_type or "application/octet-stream"}, timeout=60,
        )
        if response.status_code not in (200, 201):
            raise HTTPException(response.status_code, f"Document Parser upload failed: {response.text[:800]}")
        parser_doc = response.json()
        parser_id = parser_doc.get("id")
        if not parser_id:
            raise HTTPException(502, "Document Parser upload response did not include id")
        document_id = str(uuid.uuid4())
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO trace_documents(id,project_id,role,file_name,parser_document_id,parser_state) VALUES(%s,%s,%s,%s,%s,%s)",
                    (document_id, project_id, role, name, parser_id, "queued"),
                )
                conn.commit()
        except psycopg.errors.UniqueViolation:
            with db() as conn:
                existing = conn.execute("SELECT id,role,file_name,parser_document_id FROM trace_documents WHERE project_id=%s AND parser_document_id=%s", (project_id, parser_id)).fetchone()
            added.append({"id": existing["id"], "role": existing["role"], "file_name": existing["file_name"], "document_id": existing["parser_document_id"], "duplicate": True})
            continue
        added.append({"id": document_id, "role": role, "file_name": name, "document_id": parser_id, "duplicate": False})
    return {"documents": added, "project": project_payload(project_id)}


@app.post("/api/projects/{project_id}/process", status_code=202)
async def process(project_id: str):
    if not project_row(project_id):
        raise HTTPException(404, "Project not found")
    existing = ACTIVE_TASKS.get(project_id)
    if existing and not existing.done():
        return {"project_id": project_id, "status": "running", "message": "Processing is already running"}
    with db() as conn:
        project = conn.execute("SELECT stages FROM trace_projects WHERE id=%s", (project_id,)).fetchone()
        stages = project["stages"]
        for stage_name in stages:
            if stages[stage_name]["status"] in {"failed", "blocked"}:
                stages[stage_name] = {**stages[stage_name], "status": "pending", "error": None, "updated_at": now()}
        conn.execute("UPDATE trace_projects SET stages=%s,status='running',last_error=NULL,updated_at=now() WHERE id=%s", (Jsonb(stages), project_id))
        conn.commit()
    ACTIVE_TASKS[project_id] = asyncio.create_task(process_project(project_id))
    return {"project_id": project_id, "status": "queued"}


@app.post("/api/projects/{project_id}/retry", status_code=202)
async def retry(project_id: str, stage: Literal["parser", "extraction", "linking", "reconciliation"]):
    project = project_row(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    existing = ACTIVE_TASKS.get(project_id)
    if existing and not existing.done():
        raise HTTPException(409, "Project processing is already running")
    if stage == "linking" and project["data_classification"] not in ALLOWED_CLASSIFICATIONS:
        raise HTTPException(403, "External LLM retry is blocked for confidential data")
    if stage == "linking" and not project["allow_external_llm"]:
        raise HTTPException(403, "External LLM retry requires explicit project consent")
    if stage == "reconciliation" and project["linking_result"] is None:
        raise HTTPException(409, "A saved Linking result is required before Reconciliation can be retried")
    if stage == "reconciliation":
        invalidate_reconciliation(project_id)
    update_stage(project_id, stage, status="pending", error=None)
    ACTIVE_TASKS[project_id] = asyncio.create_task(process_project(project_id, retry_stage=stage))
    return {"project_id": project_id, "stage": stage, "status": "queued"}


@app.get("/api/projects/{project_id}/documents/{document_id}/result")
def document_result(project_id: str, document_id: str):
    with db() as conn:
        doc = conn.execute("SELECT parser_result,extraction_result,parser_error,extraction_error FROM trace_documents WHERE project_id=%s AND id=%s", (project_id, document_id)).fetchone()
    if not doc:
        raise HTTPException(404, "Project document not found")
    return {"parser_result": doc["parser_result"], "extraction": doc["extraction_result"], "parser_error": doc["parser_error"], "extraction_error": doc["extraction_error"]}


@app.get("/api/projects/{project_id}/linking")
def project_linking(project_id: str):
    project = project_row(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {"linking_result": project["linking_result"], "linking_job_id": project["linking_job_id"], "status": project["stages"].get("linking", {}).get("status")}


@app.get("/api/projects/{project_id}/reconciliation")
def get_reconciliation(project_id: str):
    project = project_row(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {"reconciliation_result": project["reconciliation_result"], "status": project["stages"].get("reconciliation", {}).get("status")}


@app.patch("/api/projects/{project_id}/links/{link_id}")
async def decide_link(project_id: str, link_id: str, decision: LinkDecision):
    project = project_row(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    result = project["linking_result"]
    if not result:
        raise HTTPException(409, "Linking result is not available")
    if CLIENT is None:
        raise HTTPException(503, "Gateway HTTP client is unavailable")
    response = await CLIENT.patch(
        f"{LINKING_URL}/api/linking-runs/{result['linking_run_id']}/links/{link_id}",
        headers=auth_headers(), json={"status": decision.status}, timeout=30,
    )
    if response.status_code != 200:
        raise HTTPException(response.status_code, f"Document Linking decision failed: {response.text[:800]}")
    updated = response.json()
    invalidate_reconciliation(project_id, linking_result=updated)
    return {"linking_result": updated}


def source_lookup(project_id: str, parser_id: str):
    with db() as conn:
        row = conn.execute("SELECT file_name FROM trace_documents WHERE project_id=%s AND parser_document_id=%s", (project_id, parser_id)).fetchone()
    if not row:
        raise HTTPException(404, "Source document is not part of this project")
    return row["file_name"]


@app.get("/api/projects/{project_id}/sources/{parser_id}")
async def source_file(project_id: str, parser_id: str):
    source_lookup(project_id, parser_id)
    assert CLIENT is not None
    response = await CLIENT.get(f"{PARSER_URL}/api/documents/{parser_id}/source", timeout=60)
    if response.status_code != 200:
        raise HTTPException(response.status_code, "Parser source file is unavailable")
    name = source_lookup(project_id, parser_id).replace('"', "")
    return Response(response.content, media_type=response.headers.get("content-type", "application/octet-stream"), headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/api/projects/{project_id}/sources/{parser_id}/pages/{page_no}")
async def source_page(project_id: str, parser_id: str, page_no: int):
    source_lookup(project_id, parser_id)
    assert CLIENT is not None
    response = await CLIENT.get(f"{PARSER_URL}/api/documents/{parser_id}/pages/{page_no}", timeout=60)
    if response.status_code != 200:
        raise HTTPException(response.status_code, "Parser page image is unavailable")
    return Response(response.content, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/services")
async def service_links():
    return {
        "parser": {"name": "Document Parser", "docs": "http://localhost:8081/docs", "openapi": "http://localhost:8081/openapi.json"},
        "extraction": {"name": "Structured Extraction", "docs": "http://localhost:8082/docs", "openapi": "http://localhost:8082/openapi.json"},
        "linking": {"name": "Document Linking", "docs": "http://localhost:8083/docs", "openapi": "http://localhost:8083/openapi.json"},
        "reconciliation": {"name": "Reconciliation Engine", "docs": "http://localhost:8085/docs", "openapi": "http://localhost:8085/openapi.json"},
        "gateway": {"name": "Gateway", "docs": "http://localhost:8084/docs", "openapi": "http://localhost:8084/openapi.json"},
    }
