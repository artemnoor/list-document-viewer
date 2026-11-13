from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from app.engine import run_verification
from app.models import VerificationRequest


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprint(extraction: dict[str, Any]) -> str:
    value = copy.deepcopy(extraction)
    value.pop("input_hash", None)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _initialize_fingerprints(payload: dict[str, Any]) -> None:
    primary = payload["extraction"]
    primary["input_hash"] = _fingerprint(primary)
    input_data = payload["reconciliation_result"]["run_metadata"]["input_data"]
    input_data["extraction_hash"] = primary["input_hash"]
    supporting_hashes = {}
    for extraction in payload.get("supporting_extractions", []):
        extraction["input_hash"] = _fingerprint(extraction)
        supporting_hashes[extraction["document_id"]] = extraction["input_hash"]
    input_data["supporting_extraction_hashes"] = supporting_hashes


def _refresh_fingerprints_if_consistent(payload: dict[str, Any]) -> None:
    """Keep ordinary fixture mutations bound while preserving deliberate bad hashes in tests."""
    input_data = payload["reconciliation_result"]["run_metadata"]["input_data"]
    primary = payload["extraction"]
    if primary.get("input_hash") and input_data.get("extraction_hash") == primary.get("input_hash"):
        primary["input_hash"] = _fingerprint(primary)
        input_data["extraction_hash"] = primary["input_hash"]
    support_hashes = input_data.get("supporting_extraction_hashes", {})
    for extraction in payload.get("supporting_extractions", []):
        document_id = extraction.get("document_id")
        old_hash = extraction.get("input_hash")
        if old_hash and support_hashes.get(document_id) == old_hash:
            extraction["input_hash"] = _fingerprint(extraction)
            support_hashes[document_id] = extraction["input_hash"]
    linking = payload.get("linking_result")
    if linking:
        by_document = {item.get("document_id"): item for item in [primary, *payload.get("supporting_extractions", [])]}
        for item in linking.get("input_documents", []):
            extraction = by_document.get(item.get("document_id"))
            if extraction and item.get("input_hash") == extraction.get("input_hash"):
                item["input_hash"] = extraction["input_hash"]


def base_payload() -> dict[str, Any]:
    payload = {
        "project_id": "synthetic-project",
        "extraction": read_json(FIXTURES / "extraction-kfz.json"),
        "supporting_extractions": [read_json(FIXTURES / "extraction-support.json")],
        "reconciliation_result": read_json(FIXTURES / "reconciliation-matched.json"),
        "linking_result": None,
        "context": {"period": None, "tolerance": {"absolute": None, "absolute_unit": None, "relative": None, "rounding_scale": None, "rounding_mode": "HALF_UP"}, "notes": []},
    }
    _initialize_fingerprints(payload)
    return payload


def make_request(payload: dict[str, Any] | None = None) -> VerificationRequest:
    value = payload or base_payload()
    _refresh_fingerprints_if_consistent(value)
    return VerificationRequest.model_validate(value)


def verify(payload: dict[str, Any] | None = None):
    return run_verification(make_request(payload))


def indicator(result, target_id: str = "target-reported-total"):
    return next(item for item in result.indicators if item.target_id == target_id)


def set_actual(payload: dict[str, Any], value: Any, status: str = "extracted", source_value: Any = None) -> None:
    field = payload["extraction"]["fields"]["reported_total"]
    field["value"] = value
    field["source_value"] = source_value if source_value is not None else str(value)
    field["status"] = status
    field["provenance"]["source_text"] = str(field["source_value"])
    payload["extraction"]["indicators"][0]["extracted"]["value"] = copy.deepcopy(value)
    payload["extraction"]["indicators"][0]["extracted"]["source_value"] = field["source_value"]
    payload["extraction"]["indicators"][0]["extracted"]["status"] = status
    payload["extraction"]["indicators"][0]["extracted"]["provenance"]["source_text"] = str(field["source_value"])


def set_source_amount(payload: dict[str, Any], value: Any, source_value: str | None = None) -> None:
    field = payload["supporting_extractions"][0]["fields"]["source_amount"]
    field["value"] = value
    field["source_value"] = source_value if source_value is not None else str(value)
    field["provenance"]["source_text"] = str(field["source_value"])


def set_expected(payload: dict[str, Any], value: Any, currency: str = "RUB") -> None:
    result = payload["reconciliation_result"]["targets"][0]["result"]
    result["expected_value"] = {"amount": str(value), "currency": currency}
    result["currency"] = currency
    result["operations"][0]["output_value"] = str(value)


def confirmed_linking_payload() -> dict[str, Any]:
    payload = base_payload()
    linking = read_json(FIXTURES / "linking-confirmed.json")
    linking["linking_run_id"] = "synthetic-linking-run-001"
    source = payload["reconciliation_result"]["targets"][0]["result"]["used_sources"][0]
    source["link_id"] = "synthetic-link-invoice-kfz"
    source["evidence_index"] = 0
    payload["reconciliation_result"]["run_metadata"]["input_data"]["linking_run_id"] = linking["linking_run_id"]
    payload["reconciliation_result"]["run_metadata"]["input_data"]["linking_contract_version"] = "1.2.0"
    by_document = {item["document_id"]: item for item in [payload["extraction"], *payload["supporting_extractions"]]}
    for linked_input in linking["input_documents"]:
        linked_input["input_hash"] = by_document[linked_input["document_id"]]["input_hash"]
    payload["linking_result"] = linking
    return payload
