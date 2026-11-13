import json

from fastapi.testclient import TestClient

from app.api import create_app
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
        assert repeated.json()["schema_version"] == "1.1.0"
        assert repeated.json()["completeness"]["complete"] is True

        fetched = client.get(f"/api/v1/verifications/{verification_id}")
        assert fetched.status_code == 422  # project scope is mandatory for result reads
        fetched = client.get(f"/api/v1/verifications/{verification_id}", params={"project_id": "synthetic-project"})
        assert fetched.status_code == 200
        assert fetched.json()["input_metadata"] == repeated.json()["input_metadata"]


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
