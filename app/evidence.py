from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adapters import (
    ReferenceResolutionError,
    pointer_tokens,
    resolve_extracted_reference,
    resolve_pointer,
    row_id_for_pointer,
)


@dataclass
class SourceCheck:
    source: dict[str, Any]
    resolved_value: Any = None
    resolved_raw_value: Any = None
    extraction_status: str | None = None
    provenance: dict[str, Any] | None = None
    reference_resolved: bool = False
    issues: list[dict[str, Any]] = field(default_factory=list)
    link: dict[str, Any] | None = None
    link_evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_human_confirmed(self) -> bool:
        return (
            self.reference_resolved
            and not self.issues
            and self.source.get("evidence_status") == "human_confirmed"
            and (self.link is None or self.link.get("verification_status") == "human_confirmed")
        )

    def as_trace(self) -> dict[str, Any]:
        return {
            "source_id": self.source.get("source_id"),
            "document_id": self.source.get("document_id"),
            "extraction_id": self.source.get("extraction_id"),
            "row_id": self.source.get("row_id"),
            "json_pointer": self.source.get("json_pointer"),
            "reason": self.source.get("reason"),
            "evidence_status": self.source.get("evidence_status"),
            "resolved_value": self.resolved_value,
            "raw_value": self.resolved_raw_value,
            "declared_evidence_status": self.source.get("evidence_status"),
            "reference_resolved": self.reference_resolved,
            "provenance": self.provenance,
            "link_id": self.source.get("link_id"),
            "linking_evidence": self.link_evidence,
            "diagnostics": self.issues,
        }


def _dotted_path_pointer(path: str) -> str:
    if path.startswith("/"):
        pointer = path
    else:
        pointer = "/" + "/".join(path.split("."))
    if not pointer.endswith("/value"):
        pointer += "/value"
    return pointer


def _matching_link_evidence(
    link: dict[str, Any], source: dict[str, Any], index: int | None
) -> list[dict[str, Any]]:
    evidence = link.get("evidence")
    if not isinstance(evidence, list):
        return []
    indexed = [(index, evidence[index])] if index is not None and index < len(evidence) else list(enumerate(evidence))
    matches: list[dict[str, Any]] = []
    for evidence_index, item in indexed:
        if not isinstance(item, dict):
            continue
        for endpoint_name in ("source", "target"):
            endpoint = item.get(endpoint_name)
            if not isinstance(endpoint, dict):
                continue
            if endpoint.get("document_id") != source.get("document_id"):
                continue
            endpoint_path = endpoint.get("path")
            requested_path = source.get("json_pointer")
            if isinstance(endpoint_path, str) and isinstance(requested_path, str):
                try:
                    if _dotted_path_pointer(endpoint_path) != requested_path:
                        continue
                except Exception:
                    continue
            matches.append({"evidence_index": evidence_index, "endpoint": endpoint_name, **item})
            break
    return matches


def validate_source_references(
    sources: list[dict[str, Any]],
    extractions: dict[str, dict[str, Any]],
    linking_result: dict[str, Any] | None,
) -> list[SourceCheck]:
    links = {
        item.get("link_id"): item
        for item in (linking_result or {}).get("links", [])
        if isinstance(item, dict) and isinstance(item.get("link_id"), str)
    }
    linking_inputs = {
        item.get("document_id"): item
        for item in (linking_result or {}).get("input_documents", [])
        if isinstance(item, dict) and isinstance(item.get("document_id"), str)
    }
    checks: list[SourceCheck] = []

    for source in sources:
        check = SourceCheck(source=source)
        checks.append(check)
        document_id = source.get("document_id")
        extraction = extractions.get(document_id)
        pointer = source.get("json_pointer")
        if extraction is None:
            check.issues.append({"code": "source_document_missing", "message": "Referenced extraction document is not present in the request"})
        elif extraction.get("extraction_id") != source.get("extraction_id"):
            check.issues.append({"code": "extraction_id_mismatch", "message": "The referenced extraction_id does not match the supplied extraction"})
        elif not isinstance(pointer, str):
            check.issues.append({"code": "source_pointer_missing", "message": "No exact JSON Pointer was supplied for this used source"})
        else:
            try:
                extracted = resolve_extracted_reference(extraction, pointer)
                check.resolved_value = extracted.value
                check.resolved_raw_value = extracted.raw_value
                check.extraction_status = extracted.status
                check.provenance = extracted.provenance
                check.reference_resolved = True
                if extracted.container is None:
                    check.issues.append({"code": "source_wrapper_missing", "message": "The source pointer does not address an Extraction value wrapper"})
                tokens = pointer_tokens(pointer)
                extraction_review_path = ".".join(tokens[:-1])
                if any(
                    isinstance(review, dict) and review.get("path") == extraction_review_path
                    for review in extraction.get("review_required", [])
                ):
                    check.issues.append({"code": "source_not_extracted", "message": "Structured Extraction review_required includes this source path"})
                if extracted.status == "review":
                    check.issues.append({"code": "source_not_extracted", "message": "Source value is marked for review"})
                elif extracted.status == "missing" or extracted.value is None:
                    check.issues.append({"code": "source_value_missing", "message": "Referenced source value is missing"})
                elif extracted.status != "extracted":
                    check.issues.append({"code": "source_not_extracted", "message": f"Source value status is {extracted.status!r}, not 'extracted'"})
                if not extracted.provenance:
                    check.issues.append({"code": "source_provenance_missing", "message": "Extraction value has no provenance object"})
                elif extracted.provenance.get("document_id") != document_id:
                    check.issues.append({"code": "source_provenance_document_mismatch", "message": "Provenance document_id does not match the referenced extraction"})
                elif extracted.provenance.get("source_available") is False:
                    check.issues.append({"code": "source_locator_unavailable", "message": "Extraction marks its original source as unavailable"})
                elif not any(extracted.provenance.get(key) for key in ("source_ref", "page_no", "sheet_name", "cell_address")):
                    check.issues.append({"code": "source_locator_missing", "message": "No PDF/XLSX/source locator is present in provenance"})
                found_row_id = row_id_for_pointer(extraction, pointer)
                if source.get("row_id") and found_row_id and source["row_id"] != found_row_id:
                    check.issues.append({"code": "row_id_mismatch", "message": "The supplied row_id does not match the referenced line item"})
            except ReferenceResolutionError as exc:
                check.issues.append({"code": "source_reference_unresolved", "message": str(exc)})

        if source.get("evidence_status") != "human_confirmed":
            check.issues.append({"code": "source_not_human_confirmed", "message": "Reconciliation source is not explicitly marked human_confirmed"})

        link_id = source.get("link_id")
        if link_id:
            link = links.get(link_id)
            check.link = link
            if link is None:
                check.issues.append({"code": "link_reference_unresolved", "message": f"Linking result has no link_id {link_id!r}"})
            else:
                if document_id not in {link.get("source_document_id"), link.get("target_document_id")}:
                    check.issues.append({"code": "link_document_mismatch", "message": "Referenced link does not connect the used source document"})
                declared_input = linking_inputs.get(document_id)
                if declared_input is None:
                    check.issues.append({"code": "link_input_document_missing", "message": "Referenced source document is absent from Linking input_documents"})
                elif declared_input.get("extraction_id") != source.get("extraction_id"):
                    check.issues.append({"code": "link_input_extraction_mismatch", "message": "Linking input extraction_id differs from the used source"})
                evidence_index = source.get("evidence_index")
                matches = _matching_link_evidence(link, source, evidence_index)
                check.link_evidence = matches
                if not matches:
                    check.issues.append({"code": "link_evidence_unresolved", "message": "No supplied Linking evidence resolves to the referenced source document and value path"})
                elif check.reference_resolved:
                    endpoint = matches[0].get(matches[0].get("endpoint"), {})
                    if endpoint.get("raw_value") != check.resolved_raw_value:
                        check.issues.append({"code": "link_evidence_value_mismatch", "message": "Linking evidence raw_value differs from the referenced Extraction source_value"})
                if link.get("status") != "confirmed" or link.get("verification_status") != "human_confirmed":
                    check.issues.append({"code": "link_not_human_confirmed", "message": "Linked evidence is not both confirmed and human_confirmed"})
                if link.get("conflicts"):
                    check.issues.append({"code": "link_has_conflicts", "message": "Linking result declares conflicts for this relationship"})
                unresolved_diagnostics = [
                    diagnostic
                    for diagnostic in (linking_result or {}).get("link_validation_diagnostics", [])
                    if isinstance(diagnostic, dict)
                    and diagnostic.get("link_id") == link_id
                    and diagnostic.get("resolution") in {"unresolved", "review_required"}
                ]
                if unresolved_diagnostics:
                    check.issues.append({"code": "link_diagnostic_unresolved", "message": "Linking diagnostics leave this relationship unresolved"})

    return checks


def actual_reference_is_valid(
    extraction: dict[str, Any], pointer: str, expected_document_id: str, expected_extraction_id: str
) -> tuple[Any, dict[str, Any] | None, dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        reference = resolve_extracted_reference(extraction, pointer)
    except ReferenceResolutionError as exc:
        return None, None, None, None, [{"code": "actual_reference_unresolved", "message": str(exc)}]
    container = reference.container
    if extraction.get("document_id") != expected_document_id:
        issues.append({"code": "target_document_mismatch", "message": "Reconciliation target document_id does not match the primary Extraction"})
    if extraction.get("extraction_id") != expected_extraction_id:
        issues.append({"code": "target_extraction_mismatch", "message": "Reconciliation target extraction_id does not match the primary Extraction"})
    if container is None:
        issues.append({"code": "actual_value_wrapper_missing", "message": "Target pointer must address an Extraction value wrapper ending in /value"})
    else:
        if reference.status == "missing" or reference.value is None:
            issues.append({"code": "actual_value_missing", "message": "Actual extracted value is missing"})
        elif reference.status != "extracted":
            issues.append({"code": "actual_value_requires_review", "message": f"Actual Extraction status is {reference.status!r}"})
        if not reference.provenance:
            issues.append({"code": "actual_provenance_missing", "message": "Actual value has no provenance object"})
        elif reference.provenance.get("document_id") != expected_document_id:
            issues.append({"code": "actual_provenance_document_mismatch", "message": "Actual provenance document_id differs from the target document"})
        elif reference.provenance.get("source_available") is False:
            issues.append({"code": "actual_source_unavailable", "message": "Extraction reports that its source is unavailable"})
        elif not any(reference.provenance.get(key) for key in ("source_ref", "page_no", "sheet_name", "cell_address")):
            issues.append({"code": "actual_locator_missing", "message": "No source_ref, PDF page, or XLSX cell locator is present"})
    return reference.value, reference.raw_value, reference.provenance, reference.status, issues
