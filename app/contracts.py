from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.models import VerificationRequest, VerificationResult


ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"


class ContractIssue(ValueError):
    def __init__(self, path: str, message: str, contract: str):
        super().__init__(message)
        self.path = path
        self.contract = contract
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"contract": self.contract, "path": self.path, "message": self.message}


def load_schema(name: str) -> dict[str, Any]:
    with (CONTRACTS / name).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _validate(payload: Any, schema: dict[str, Any], contract: str) -> list[ContractIssue]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    flattened = []

    def visit(error):
        if error.context:
            for child in error.context:
                visit(child)
        else:
            flattened.append(error)

    for error in errors:
        visit(error)
    unique = {}
    for error in flattened:
        path = [str(part) for part in error.absolute_path]
        if error.validator == "required":
            missing = re.search(r"'([^']+)' is a required property", error.message)
            if missing:
                path.append(missing.group(1))
        unique[(tuple(path), error.message)] = (path, error)
    return [
        ContractIssue(
            path="/" + "/".join(path),
            message=error.message,
            contract=contract,
        )
        for path, error in list(unique.values())[:50]
    ]


def validate_request_contracts(request: VerificationRequest) -> None:
    issues: list[ContractIssue] = []
    extraction_schema = load_schema("upstream/structured-extraction-1.2.0.schema.json")
    linking_schema = load_schema("upstream/document-linking-1.2.0.schema.json")
    reconciliation_schema = load_schema("reconciliation-result-1.0.0.schema.json")

    extraction_version = request.extraction.get("schema_version")
    if not isinstance(extraction_version, str) or not extraction_version.startswith("1."):
        issues.append(ContractIssue("/extraction/schema_version", "Only additive Extraction contract 1.x is supported", "structured-extraction"))
    issues.extend(_validate(request.extraction, extraction_schema, "structured-extraction-1.2.0"))
    if request.extraction.get("document_type") != "kfz_report":
        issues.append(ContractIssue("/extraction/document_type", "Primary extraction must be a kfz_report", "structured-extraction"))

    document_ids = {request.extraction.get("document_id")}
    for index, extraction in enumerate(request.supporting_extractions):
        version = extraction.get("schema_version") if isinstance(extraction, dict) else None
        if not isinstance(version, str) or not version.startswith("1."):
            issues.append(ContractIssue(f"/supporting_extractions/{index}/schema_version", "Only additive Extraction contract 1.x is supported", "structured-extraction"))
        issues.extend(_validate(extraction, extraction_schema, f"supporting-extraction-{index}"))
        document_id = extraction.get("document_id") if isinstance(extraction, dict) else None
        if document_id in document_ids:
            issues.append(ContractIssue(f"/supporting_extractions/{index}/document_id", "Duplicate document_id in extraction inputs", "structured-extraction"))
        document_ids.add(document_id)

    issues.extend(_validate(request.reconciliation_result, reconciliation_schema, "reconciliation-result-1.0.0"))
    if request.linking_result is not None:
        issues.extend(_validate(request.linking_result, linking_schema, "document-linking-1.2.0"))

    if issues:
        raise ContractValidationError(issues)


class ContractValidationError(ValueError):
    def __init__(self, issues: list[ContractIssue]):
        super().__init__("One or more input contracts are invalid")
        self.issues = issues

    def as_list(self) -> list[dict[str, str]]:
        return [issue.as_dict() for issue in self.issues]


def validate_result_contract(result: VerificationResult) -> None:
    schema = VerificationResult.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://phystech-trace.local/contracts/verification-result-1.0.0.schema.json"
    schema["title"] = "Phystech Trace Verification Result 1.0.0"
    errors = _validate(result.model_dump(mode="json"), schema, "verification-result-1.0.0")
    if errors:
        raise ContractValidationError(errors)
