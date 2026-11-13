from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.engine import run_verification
from app.models import VerificationRequest


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def base_payload() -> dict[str, Any]:
    return {
        "project_id": "synthetic-project",
        "extraction": read_json(FIXTURES / "extraction-kfz.json"),
        "supporting_extractions": [read_json(FIXTURES / "extraction-support.json")],
        "reconciliation_result": read_json(FIXTURES / "reconciliation-matched.json"),
        "linking_result": None,
        "context": {"period": None, "tolerance": {"absolute": None, "absolute_unit": None, "relative": None, "rounding_scale": None, "rounding_mode": "HALF_UP"}, "notes": []},
    }


def make_request(payload: dict[str, Any] | None = None) -> VerificationRequest:
    return VerificationRequest.model_validate(payload or base_payload())


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
    payload["linking_result"] = linking
    return payload
