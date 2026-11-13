import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import Diagnostic, InputContractError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas" / "upstream"


@lru_cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _schema_diagnostics(validator: Draft202012Validator, value: Any, prefix: str) -> list[Diagnostic]:
    errors = sorted(validator.iter_errors(value), key=lambda item: (list(map(str, item.absolute_path)), item.message))
    return [
        Diagnostic(
            "schema_validation_error",
            prefix + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path),
            error.message,
        )
        for error in errors[:50]
    ]


def validate_upstream_inputs(extractions: list[dict[str, Any]], linking: dict[str, Any]) -> None:
    diagnostics: list[Diagnostic] = []
    seen: dict[str, int] = {}
    extraction_validator = _validator("structured-extraction-1.2.0.schema.json")
    for index, extraction in enumerate(extractions):
        path = f"$.extraction_results[{index}]"
        document_id = extraction.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            diagnostics.append(Diagnostic("missing_document_id", f"{path}.document_id", "document_id must be a non-empty string"))
        elif document_id in seen:
            diagnostics.append(Diagnostic("duplicate_document_id", f"{path}.document_id", f"document_id also appears at extraction_results[{seen[document_id]}]", {"document_id": document_id}))
        else:
            seen[document_id] = index
        version = extraction.get("schema_version")
        if version != "1.2.0":
            diagnostics.append(Diagnostic("unsupported_extraction_schema_version", f"{path}.schema_version", "Only Structured Extraction schema_version 1.2.0 is supported", {"expected": "1.2.0", "actual": version}))
        diagnostics.extend(_schema_diagnostics(extraction_validator, extraction, path))

    link_version = linking.get("contract_version")
    if link_version != "1.2.0":
        diagnostics.append(Diagnostic("unsupported_linking_contract_version", "$.linking_result.contract_version", "Only Document Linking contract_version 1.2.0 is supported", {"expected": "1.2.0", "actual": link_version}))
    diagnostics.extend(_schema_diagnostics(_validator("document-linking-1.2.0.schema.json"), linking, "$.linking_result"))

    if not diagnostics:
        extraction_by_id = {item["document_id"]: item for item in extractions}
        input_documents = linking.get("input_documents", [])
        link_docs: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(input_documents):
            document_id = item.get("document_id")
            if document_id in link_docs:
                diagnostics.append(Diagnostic("duplicate_linking_document_id", f"$.linking_result.input_documents[{index}].document_id", "Linking snapshot contains this document_id more than once", {"document_id": document_id}))
            else:
                link_docs[document_id] = item
        for document_id, extraction in extraction_by_id.items():
            linked = link_docs.get(document_id)
            path = "$.linking_result.input_documents"
            if linked is None:
                diagnostics.append(Diagnostic("linking_snapshot_missing_document", path, "Linking snapshot does not contain this extraction result", {"document_id": document_id, "extraction_id": extraction.get("extraction_id")}))
                continue
            checks = {
                "extraction_id": extraction.get("extraction_id"),
                "version": extraction.get("version"),
                "schema_version": extraction.get("schema_version"),
                "input_version": extraction.get("version"),
            }
            for key, expected in checks.items():
                if key == "input_version" and key not in linked:
                    continue
                if linked.get(key) != expected:
                    diagnostics.append(Diagnostic("linking_snapshot_version_mismatch", f"{path}[document_id={document_id}].{key}", "Linking input snapshot does not match the supplied extraction", {"expected": expected, "actual": linked.get(key)}))
            linked_hash = linked.get("input_hash")
            source_hash = extraction.get("input_hash") or extraction.get("source_hash")
            if linked_hash is not None and (not isinstance(linked_hash, str) or len(linked_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in linked_hash)):
                diagnostics.append(Diagnostic("invalid_linking_input_hash", f"{path}[document_id={document_id}].input_hash", "input_hash must be a 64-character SHA-256 digest when supplied"))
            if source_hash is not None and linked_hash != source_hash:
                diagnostics.append(Diagnostic("linking_input_hash_mismatch", f"{path}[document_id={document_id}].input_hash", "Linking input hash differs from the source hash recorded by Extraction", {"expected": source_hash, "actual": linked_hash}))
        for document_id in link_docs:
            if document_id not in extraction_by_id:
                diagnostics.append(Diagnostic("extraction_missing_from_linking_snapshot", "$.extraction_results", "Linking snapshot contains a document without its extraction result", {"document_id": document_id}))
        for index, link in enumerate(linking.get("links", [])):
            for endpoint in ("source_document_id", "target_document_id"):
                document_id = link.get(endpoint)
                if document_id not in link_docs:
                    diagnostics.append(Diagnostic("link_endpoint_missing_document", f"$.linking_result.links[{index}].{endpoint}", "Link endpoint does not exist in the Linking input snapshot", {"document_id": document_id}))
    if diagnostics:
        raise InputContractError(diagnostics)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

