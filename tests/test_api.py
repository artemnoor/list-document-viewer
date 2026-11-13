import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.api import create_app
from app.artifact_adapter import FileArtifactAdapter
from tests.helpers import base_payload


def test_versioned_api_create_get_history_and_diagnostics():
    with TestClient(create_app(":memory:", auth_mode="development")) as client:
        response = client.post("/api/v1/verifications", json=base_payload())
        assert response.status_code == 200
        result = response.json()
        verification_id = result["verification_id"]
        assert result["overall_status"] == "matched"

        fetched = client.get(f"/api/v1/verifications/{verification_id}", params={"project_id": "synthetic-project"})
        assert fetched.status_code == 200
        assert fetched.json() == result

        history = client.get("/api/v1/verifications", params={"project_id": "synthetic-project"})
        assert history.status_code == 200
        assert history.json()["items"][0]["verification_id"] == verification_id

        diagnostics = client.get(f"/api/v1/verifications/{verification_id}/diagnostics", params={"project_id": "synthetic-project"})
        assert diagnostics.status_code == 200
        assert diagnostics.json()["verification_id"] == verification_id
        assert "target-reported-total" not in diagnostics.json()["indicator_diagnostics"]


def test_api_health_docs_openapi_and_not_found():
    with TestClient(create_app(":memory:", auth_mode="development")) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/docs").status_code == 200
        openapi = client.get("/openapi.json").json()
        assert "/api/v1/verifications" in openapi["paths"]
        assert "/api/v1/verifications/from-artifacts" in openapi["paths"]
        assert "VerificationResult" in openapi["components"]["schemas"]
        assert client.get("/api/v1/verifications/unknown", params={"project_id": "synthetic-project"}).status_code == 404


def test_api_reports_contract_errors_as_422():
    payload = base_payload()
    payload["extraction"].pop("document_id")
    with TestClient(create_app(":memory:", auth_mode="development")) as client:
        response = client.post("/api/v1/verifications", json=payload)
        assert response.status_code == 422
        assert any(issue["path"].endswith("document_id") for issue in response.json()["detail"])


def test_api_preserves_idempotent_legacy_records_without_input_metadata():
    app = create_app(":memory:", auth_mode="development")
    payload = base_payload()
    with TestClient(app) as client:
        created = client.post("/api/v1/verifications", json=payload)
        assert created.status_code == 200
        verification_id = created.json()["verification_id"]

        row = app.state.store._db.execute(
            "SELECT result_json FROM verification_runs WHERE verification_id = ?", (verification_id,)
        ).fetchone()
        legacy = json.loads(row["result_json"])
        legacy.pop("input_metadata")
        legacy["schema_version"] = "1.0.0"
        legacy.pop("completeness", None)
        for indicator in legacy["indicators"]:
            indicator.pop("trust", None)
        app.state.store._db.execute(
            "UPDATE verification_runs SET result_json = ? WHERE verification_id = ?",
            (json.dumps(legacy), verification_id),
        )

        repeated = client.post("/api/v1/verifications", json=payload)
        assert repeated.status_code == 200
        assert repeated.json()["verification_id"] == verification_id
        assert repeated.json()["input_metadata"] == {
            "available": False,
            "reason": "legacy_record_predates_input_metadata",
        }
        assert repeated.json()["schema_version"] == "1.2.0"
        assert repeated.json()["integrity_status"] == "legacy_unverified"
        assert repeated.json()["legacy_overall_status"] == "matched"
        assert repeated.json()["overall_status"] == "needs_review"
        assert repeated.json()["completeness"]["complete"] is False
        assert repeated.json()["conclusion"]["has_proven_mismatch"] is False
        assert repeated.json()["indicators"][0]["legacy_status"] == "matched"

        fetched = client.get(f"/api/v1/verifications/{verification_id}")
        assert fetched.status_code == 422  # project scope is mandatory for result reads
        fetched = client.get(f"/api/v1/verifications/{verification_id}", params={"project_id": "synthetic-project"})
        assert fetched.status_code == 200
        assert fetched.json()["input_metadata"] == repeated.json()["input_metadata"]
        history = client.get("/api/v1/verifications", params={"project_id": "synthetic-project"})
        assert history.status_code == 200
        assert history.json()["items"][0]["overall_status"] == "needs_review"


def test_project_credentials_isolate_results_and_history():
    app = create_app(":memory:", auth_mode="required", project_tokens={"synthetic-project": "secret-one", "other-project": "secret-two"})
    payload = base_payload()
    with TestClient(app) as client:
        assert client.post("/api/v1/verifications", json=payload).status_code == 401
        created = client.post("/api/v1/verifications", json=payload, headers={"X-Service-Token": "secret-one"})
        assert created.status_code == 200
        verification_id = created.json()["verification_id"]
        own_history = client.get("/api/v1/verifications", params={"project_id": "synthetic-project"}, headers={"X-Service-Token": "secret-one"})
        assert own_history.status_code == 200 and len(own_history.json()["items"]) == 1
        hidden = client.get(f"/api/v1/verifications/{verification_id}", params={"project_id": "other-project"}, headers={"X-Service-Token": "secret-two"})
        assert hidden.status_code == 404


def test_request_size_limit_and_validation_errors_do_not_echo_financial_values():
    payload = base_payload()
    payload["context"]["notes"] = ["secret-financial-text-" + "x" * 1500]
    with TestClient(create_app(":memory:", auth_mode="development", max_request_bytes=1024)) as client:
        oversized = client.post("/api/v1/verifications", json=payload)
        assert oversized.status_code == 413

    payload = base_payload()
    payload["project_id"] = {"secret": "SENSITIVE-987654"}
    with TestClient(create_app(":memory:", auth_mode="development")) as client:
        invalid = client.post("/api/v1/verifications", json=payload)
        assert invalid.status_code == 422
        assert "SENSITIVE-987654" not in invalid.text
    with pytest.raises(ValueError):
        create_app(":memory:", auth_mode="development", max_request_bytes=64 * 1024 * 1024 + 1)


def test_artifact_reference_endpoint_is_project_scoped_and_idempotent(tmp_path: Path):
    payload = base_payload()
    project_id = payload["project_id"]
    project_key = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    artifact_root = tmp_path / "artifacts"
    references = {}
    for name in ("extraction", "reconciliation_result", "linking_result"):
        value = payload.get(name)
        if value is None:
            continue
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        directory = artifact_root / project_key
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{digest}.json").write_bytes(content)
        references[name] = {"artifact_id": f"{name}-v1", "sha256": digest}
    references["supporting_extractions"] = []
    for index, value in enumerate(payload.get("supporting_extractions", [])):
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        directory = artifact_root / project_key
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{digest}.json").write_bytes(content)
        references["supporting_extractions"].append({"artifact_id": f"supporting-{index}-v1", "sha256": digest})
    content = json.dumps(payload["context"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # The route keeps user context in the small reference request, not as a separate artifact.
    bundle = {
        "project_id": project_id,
        "extraction": references["extraction"],
        "supporting_extractions": references["supporting_extractions"],
        "reconciliation_result": references["reconciliation_result"],
        "context": payload["context"],
    }
    if "linking_result" in references:
        bundle["linking_result"] = references["linking_result"]
    assert len(content) < 4096 and len(json.dumps(bundle)) < 8192
    app = create_app(":memory:", auth_mode="development", artifact_root=artifact_root)
    with TestClient(app) as client:
        first = client.post("/api/v1/verifications/from-artifacts", json=bundle)
        assert first.status_code == 200, first.text
        second = client.post("/api/v1/verifications/from-artifacts", json=bundle)
        assert second.status_code == 200
        assert second.json()["verification_id"] == first.json()["verification_id"]
        assert app.state.artifacts._cache_size > 0
        foreign = dict(bundle, project_id="different-project")
        assert client.post("/api/v1/verifications/from-artifacts", json=foreign).status_code == 422
        expected_hash = hashlib.sha256(b'{"value":"expected"}').hexdigest()
        (artifact_root / project_key / f"{expected_hash}.json").write_text('{"value":"tampered"}', encoding="utf-8")
        tampered = dict(bundle, extraction={"artifact_id": "tampered-primary", "sha256": expected_hash})
        integrity_error = client.post("/api/v1/verifications/from-artifacts", json=tampered)
        assert integrity_error.status_code == 422
        assert integrity_error.json()["detail"] == "Artifact integrity check failed"


def test_artifact_cache_stays_bounded_under_parallel_reads(tmp_path: Path):
    project_id = "parallel-artifact-project"
    artifact = {"payload": "x" * 2048}
    content = json.dumps(artifact, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    project_key = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
    project_dir = tmp_path / project_key
    project_dir.mkdir()
    (project_dir / f"{digest}.json").write_bytes(content)
    adapter = FileArtifactAdapter(tmp_path, max_artifact_bytes=4096, cache_bytes=4096)
    with ThreadPoolExecutor(max_workers=12) as workers:
        values = list(workers.map(lambda _: adapter.resolve(project_id, "artifact-one", digest), range(12)))
    assert values == [artifact] * 12
    assert len(adapter._cache) == 1
    assert adapter._cache_size == len(content)


def test_full_upstream_bundle_over_two_mib_is_not_rejected_by_default_limit():
    fixture_root = Path(__file__).parent / "fixtures" / "upstream"
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    primary = read(fixture_root / "extraction" / "kfz-2026-q1.json")
    supporting = [read(path) for path in sorted((fixture_root / "extraction").glob("*.json")) if path.name != "kfz-2026-q1.json"]
    payload = {
        "project_id": "large-upstream-fixture-bundle",
        "extraction": primary,
        "supporting_extractions": supporting,
        "reconciliation_result": read(fixture_root / "reconciliation-engine" / "act-reconciliation-result.json"),
    }
    request_body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    request_bytes = len(request_body)
    assert request_bytes > 2 * 1024 * 1024
    with TestClient(create_app(":memory:", auth_mode="development")) as client:
        response = client.post("/api/v1/verifications", content=request_body, headers={"Content-Type": "application/json"})
        assert response.status_code == 200, response.text[:500]
        assert response.json()["conclusion"]["has_proven_mismatch"] is False


def test_all_published_upstream_fixture_files_reach_contract_validation_over_two_mib():
    fixture_root = Path(__file__).parent / "fixtures" / "upstream"
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    extraction_root = fixture_root / "extraction"
    extractions = [read(path) for path in sorted(extraction_root.glob("*.json"))]
    primary = next(item for item in extractions if item["document_type"] == "kfz_report")
    payload = {
        "project_id": "all-published-upstream-fixtures",
        "extraction": primary,
        "supporting_extractions": [item for item in extractions if item is not primary],
        "linking_result": read(fixture_root / "linking" / "linking-result.json"),
        "reconciliation_result": read(fixture_root / "reconciliation-engine" / "act-reconciliation-result.json"),
    }
    request_body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    assert len(request_body) > 2 * 1024 * 1024
    with TestClient(create_app(":memory:", auth_mode="development")) as client:
        response = client.post("/api/v1/verifications", content=request_body, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert any(issue["contract"] == "document-linking-1.2.0" for issue in response.json()["detail"])
