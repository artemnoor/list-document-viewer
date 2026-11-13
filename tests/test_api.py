import json

from fastapi.testclient import TestClient

from app.api import create_app
from tests.helpers import base_payload


def test_versioned_api_create_get_history_and_diagnostics():
    with TestClient(create_app(":memory:")) as client:
        response = client.post("/api/v1/verifications", json=base_payload())
        assert response.status_code == 200
        result = response.json()
        verification_id = result["verification_id"]
        assert result["overall_status"] == "matched"

        fetched = client.get(f"/api/v1/verifications/{verification_id}")
        assert fetched.status_code == 200
        assert fetched.json() == result

        history = client.get("/api/v1/verifications", params={"project_id": "synthetic-project"})
        assert history.status_code == 200
        assert history.json()["items"][0]["verification_id"] == verification_id

        diagnostics = client.get(f"/api/v1/verifications/{verification_id}/diagnostics")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["verification_id"] == verification_id
        assert "target-reported-total" not in diagnostics.json()["indicator_diagnostics"]


def test_api_health_docs_openapi_and_not_found():
    with TestClient(create_app(":memory:")) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/docs").status_code == 200
        openapi = client.get("/openapi.json").json()
        assert "/api/v1/verifications" in openapi["paths"]
        assert "VerificationResult" in openapi["components"]["schemas"]
        assert client.get("/api/v1/verifications/unknown").status_code == 404


def test_api_reports_contract_errors_as_422():
    payload = base_payload()
    payload["extraction"].pop("document_id")
    with TestClient(create_app(":memory:")) as client:
        response = client.post("/api/v1/verifications", json=payload)
        assert response.status_code == 422
        assert any("document_id" in issue["message"] for issue in response.json()["detail"])


def test_api_preserves_idempotent_legacy_records_without_input_metadata():
    app = create_app(":memory:")
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

        fetched = client.get(f"/api/v1/verifications/{verification_id}")
        assert fetched.status_code == 200
        assert fetched.json()["input_metadata"] == repeated.json()["input_metadata"]
