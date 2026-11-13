from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.adapters import (
    ReferenceResolutionError,
    pointer_tokens,
    resolve_pointer,
    row_id_for_pointer,
    sibling_unit,
)
from app.classification import (
    aggregate_status,
    classify_linking_issue,
    classify_reconciliation_diagnostics,
    classify_value_difference,
)
from app.comparison import compare_metric
from app.contracts import ContractIssue, ContractValidationError, validate_request_contracts
from app.evidence import SourceCheck, actual_reference_is_valid, validate_source_references
from app.explanations import ReviewExplanationProvider, apply_review_suggestions
from app.models import (
    Difference,
    Discrepancy,
    EvidenceTrace,
    IndicatorResult,
    PeriodRange,
    EvidenceTrust,
    Uncertainty,
    VerificationCompleteness,
    ValueEvidence,
    VerificationContext,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from app.reconciliation_adapter import ReconciliationTarget, get_reconciliation_adapter


INSUFFICIENT_SOURCE_CODES = {
    "source_document_missing",
    "extraction_id_mismatch",
    "source_pointer_missing",
    "source_wrapper_missing",
    "source_reference_unresolved",
    "source_value_missing",
    "source_provenance_missing",
    "source_provenance_document_mismatch",
    "source_locator_unavailable",
    "source_locator_missing",
    "row_id_mismatch",
    "link_reference_unresolved",
    "link_document_mismatch",
    "link_row_id_mismatch",
    "link_input_document_missing",
    "link_input_extraction_mismatch",
    "link_input_document_type_mismatch",
    "link_input_schema_version_mismatch",
    "link_input_version_mismatch",
    "link_input_hash_mismatch",
    "link_evidence_unresolved",
    "link_evidence_value_mismatch",
    "link_diagnostic_unresolved",
}

REVIEW_SOURCE_CODES = {
    "source_not_validated",
    "source_rejected",
    "link_not_confirmed",
    "link_human_rejected",
    "link_input_fingerprint_missing",
    "link_has_conflicts",
    "source_not_extracted",
    "source_conflict",
}

INVALID_PROOF_CODES = {
    "calculation_id_mismatch", "calculation_source_id_duplicate", "calculation_operation_id_duplicate",
    "calculation_input_source_unresolved", "calculation_operation_source_mismatch", "calculation_source_unused",
    "calculation_output_mismatch", "calculation_formula_mismatch", "calculation_formula_input_mismatch", "excluded_source_used",
}

INVALID_RUN_CODES = {
    "project_id_mismatch", "extraction_id_mismatch", "extraction_version_mismatch", "extraction_hash_mismatch",
    "linking_run_id_mismatch", "linking_result_missing", "linking_version_mismatch", "linking_run_id_missing",
    "linking_contract_version_missing", "supporting_extraction_missing", "supporting_extraction_hash_mismatch",
}

UNVERIFIED_RUN_CODES = {
    "extraction_hash_missing", "extraction_hash_unverifiable", "supporting_extraction_hash_missing",
    "supporting_extraction_hash_unverifiable",
}

INVALID_SOURCE_CODES = {
    "extraction_id_mismatch", "source_provenance_document_mismatch", "source_locator_unavailable", "row_id_mismatch",
    "link_document_mismatch", "link_row_id_mismatch", "link_input_extraction_mismatch", "link_input_document_type_mismatch",
    "link_input_schema_version_mismatch", "link_input_version_mismatch", "link_input_hash_mismatch",
    "link_evidence_value_mismatch", "source_conflict",
}


def canonical_fingerprint(request: VerificationRequest) -> str:
    payload = request.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _period_reference(extraction: dict[str, Any]) -> tuple[dict[str, str] | None, list[dict[str, Any]]]:
    """Resolve the actual reporting period from Extraction, never from a claim by Reconciliation/context."""
    pointers = ["/fields/reporting_period/value", "/fields/period/value"]
    for index, indicator in enumerate(extraction.get("indicators", [])):
        if isinstance(indicator, dict) and indicator.get("key") in {"reporting_period", "period"}:
            pointers.append(f"/indicators/{index}/extracted/value")
    for pointer in pointers:
        try:
            value, _, provenance, status, issues = actual_reference_is_valid(
                extraction,
                pointer,
                str(extraction.get("document_id", "")),
                str(extraction.get("extraction_id", "")),
            )
        except Exception:
            continue
        if any(issue.get("code") == "actual_reference_unresolved" for issue in issues):
            continue
        parent_pointer = pointer.rsplit("/", 1)[0]
        try:
            wrapper = resolve_pointer(extraction, parent_pointer)
        except ReferenceResolutionError:
            wrapper = None
        if isinstance(wrapper, dict) and wrapper.get("conflict"):
            issues.append({"code": "actual_period_conflict", "message": "Extraction marks the reporting period as conflicting"})
        path = ".".join(pointer_tokens(pointer)[:-1])
        if any(isinstance(review, dict) and review.get("path") == path for review in extraction.get("review_required", [])):
            issues.append({"code": "actual_period_requires_review", "message": "Extraction review_required includes the reporting period"})
        if status != "extracted":
            issues.append({"code": "actual_period_requires_review", "message": "Extraction reporting period is not marked extracted"})
        if not isinstance(value, dict) or not isinstance(value.get("start"), str) or not isinstance(value.get("end"), str):
            issues.append({"code": "actual_period_invalid", "message": "Extraction reporting period is not a valid start/end range"})
            return None, issues
        normalized = {"start": value["start"], "end": value["end"]}
        return normalized, issues
    return None, [{"code": "actual_period_missing", "message": "No reporting period could be resolved from the supplied Extraction"}]


def _target_period(target: dict[str, Any], extraction: dict[str, Any], context: VerificationContext) -> dict[str, Any] | None:
    # target.period and context.period are comparison inputs; neither proves the
    # actual period reported by the KFZ document.
    return _period_reference(extraction)[0]


def _as_period(value: Any) -> PeriodRange | None:
    if isinstance(value, dict) and isinstance(value.get("start"), str) and isinstance(value.get("end"), str):
        return PeriodRange(start=value["start"], end=value["end"])
    return None


def _infer_type(value: Any, label: str | None = None, field_key: str | None = None) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        if "amount" in value:
            return "money"
        if {"start", "end"} <= value.keys():
            return "period"
    if field_key in {"quantity", "plan_quantity", "actual_quantity"}:
        return "quantity"
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "date"
    return "string"


def _actual_evidence(
    extraction: dict[str, Any],
    target: dict[str, Any],
    pointer: str,
    value_type: str,
    context: VerificationContext,
) -> tuple[ValueEvidence | None, list[dict[str, Any]], str | None]:
    value, raw, provenance, status, issues = actual_reference_is_valid(
        extraction,
        pointer,
        target.get("source_document_id", ""),
        target.get("extraction_id", ""),
    )
    if not any(issue.get("code") == "actual_reference_unresolved" for issue in issues):
        review_path = ".".join(pointer_tokens(pointer)[:-1])
        matching_reviews = [
            item for item in extraction.get("review_required", [])
            if isinstance(item, dict) and item.get("path") == review_path
        ]
        if matching_reviews:
            issues.append({"code": "actual_review_required", "message": matching_reviews[0].get("reason", "Extraction review_required includes this value")})
        parent_path = pointer.rsplit("/", 1)[0]
        try:
            container = resolve_pointer(extraction, parent_path)
        except ReferenceResolutionError:
            container = None
        if isinstance(container, dict) and container.get("conflict"):
            issues.append({"code": "actual_conflict", "message": "Extraction marks this value as conflicting"})
        if isinstance(container, dict) and container.get("status") == "review":
            issues.append({"code": "actual_review_required", "message": "Extraction marks this value for review"})
    row_id = row_id_for_pointer(extraction, pointer)
    expected_row_id = target.get("row_id")
    if expected_row_id and expected_row_id != row_id:
        issues.append({"code": "target_row_mismatch", "message": "Reconciliation target row_id does not match the line item"})
    source_unit = sibling_unit(extraction, pointer)
    actual_unit = source_unit or target.get("unit")
    if target.get("unit") and source_unit and target["unit"] != source_unit:
        issues.append({"code": "actual_unit_metadata_mismatch", "message": f"Target unit {target['unit']} differs from the Extraction row unit {source_unit}"})
    source_currency = value.get("currency") if isinstance(value, dict) else None
    actual_currency = source_currency or target.get("currency")
    if target.get("currency") and source_currency and target["currency"] != source_currency:
        issues.append({"code": "actual_currency_metadata_mismatch", "message": f"Target currency {target['currency']} differs from the Extraction value currency {source_currency}"})
    if isinstance(value, dict) and value.get("amount") is not None:
        normalized_value = {"amount": str(value["amount"]), "currency": actual_currency}
    elif isinstance(value, Decimal):
        normalized_value = format(value, "f")
    else:
        normalized_value = value
    actual_period, period_issues = _period_reference(extraction)
    issues.extend(period_issues)
    actual = ValueEvidence(
        source_value=raw,
        normalized_value=normalized_value,
        value_type=value_type,
        currency=str(actual_currency) if actual_currency is not None else None,
        unit=str(actual_unit) if actual_unit is not None else None,
        period=_as_period(actual_period),
        extraction_status=status,
        json_pointer=pointer,
        document_id=extraction.get("document_id"),
        extraction_id=extraction.get("extraction_id"),
        row_id=row_id,
        provenance=provenance,
    )
    return actual, issues, str(actual_unit) if actual_unit is not None else None


def _expected_evidence(result: dict[str, Any], target: dict[str, Any], target_id: str, target_index: int) -> ValueEvidence:
    expected = result.get("expected_value")
    currency = result.get("currency")
    if isinstance(expected, dict) and "amount" in expected:
        currency = expected.get("currency", currency)
        normalized: Any = {"amount": str(expected["amount"]), "currency": currency}
    elif isinstance(expected, (int, float, Decimal)) and not isinstance(expected, bool):
        normalized = str(expected)
    else:
        normalized = expected
    return ValueEvidence(
        source_value=expected,
        normalized_value=normalized,
        value_type=result.get("value_type", target.get("value_type", "string")),
        currency=currency,
        unit=result.get("unit"),
        period=_as_period(result.get("period")),
        extraction_status="reconciliation_result",
        json_pointer=f"/targets/{target_index}/result/expected_value",
        document_id=None,
        extraction_id=None,
        row_id=None,
        provenance={"calculation_id": target_id, "formula": result.get("formula"), "applied_rules": result.get("applied_rules", [])},
    )


def _source_data(
    target_result: ReconciliationTarget,
    request: VerificationRequest,
    extraction_index: dict[str, dict[str, Any]],
) -> tuple[list[SourceCheck], list[dict[str, Any]]]:
    expected = target_result.result
    used = expected.get("used_sources", [])
    checks = validate_source_references(used, extraction_index, request.linking_result)
    excluded_checks = validate_source_references(expected.get("excluded_sources", []), extraction_index, request.linking_result)
    excluded = [check.as_trace() for check in excluded_checks]
    return checks, excluded


def _reconciliation_run_diagnostics(request: VerificationRequest) -> list[dict[str, Any]]:
    metadata = request.reconciliation_result["run_metadata"]
    input_data = metadata["input_data"]
    issues: list[dict[str, Any]] = []
    if metadata["project_id"] != request.project_id:
        issues.append({"code": "project_id_mismatch", "message": "Reconciliation project_id does not match the request"})
    if input_data["extraction_id"] != request.extraction.get("extraction_id"):
        issues.append({"code": "extraction_id_mismatch", "message": "Reconciliation run metadata references a different primary extraction"})
    if input_data["extraction_schema_version"] != request.extraction.get("schema_version"):
        issues.append({"code": "extraction_version_mismatch", "message": "Reconciliation run metadata references a different Extraction schema version"})
    declared_hash = input_data.get("extraction_hash")
    actual_hash = request.extraction.get("input_hash")
    if not declared_hash:
        issues.append({"code": "extraction_hash_missing", "message": "Reconciliation did not bind this run to a primary Extraction input hash"})
    elif not actual_hash:
        issues.append({"code": "extraction_hash_unverifiable", "message": "The supplied Extraction has no input_hash to verify against Reconciliation"})
    elif declared_hash != actual_hash:
        issues.append({"code": "extraction_hash_mismatch", "message": "Reconciliation run metadata hash differs from the supplied Extraction input hash"})
    declared_linking_run = input_data.get("linking_run_id")
    actual_linking_run = (request.linking_result or {}).get("linking_run_id")
    if declared_linking_run and actual_linking_run and declared_linking_run != actual_linking_run:
        issues.append({"code": "linking_run_id_mismatch", "message": "Reconciliation run metadata references a different Linking run"})
    elif declared_linking_run and not actual_linking_run:
        issues.append({"code": "linking_result_missing", "message": "Reconciliation used a Linking run that was not supplied"})
    declared_linking_version = input_data.get("linking_contract_version")
    actual_linking_version = (request.linking_result or {}).get("contract_version")
    if declared_linking_version and declared_linking_version != actual_linking_version:
        issues.append({"code": "linking_version_mismatch", "message": "Reconciliation metadata and supplied Linking contract versions differ"})
    used_link_ids = {
        source.get("link_id")
        for target_result in request.reconciliation_result.get("targets", [])
        for source in target_result.get("result", {}).get("used_sources", [])
        if isinstance(source, dict) and source.get("link_id")
    }
    if used_link_ids and not declared_linking_run:
        issues.append({"code": "linking_run_id_missing", "message": "Reconciliation used Linking evidence but did not declare its Linking run ID"})
    if used_link_ids and not declared_linking_version:
        issues.append({"code": "linking_contract_version_missing", "message": "Reconciliation used Linking evidence but did not declare its Linking contract version"})
    for document_id, declared in input_data.get("supporting_extraction_hashes", {}).items():
        supporting = next((item for item in request.supporting_extractions if item.get("document_id") == document_id), None)
        if supporting is None:
            issues.append({"code": "supporting_extraction_missing", "message": f"Reconciliation input hash names missing supporting document {document_id}"})
        elif not supporting.get("input_hash"):
            issues.append({"code": "supporting_extraction_hash_unverifiable", "message": f"Supporting Extraction {document_id} has no input_hash to verify"})
        elif supporting["input_hash"] != declared:
            issues.append({"code": "supporting_extraction_hash_mismatch", "message": f"Input hash differs for supporting document {document_id}"})
    used_supporting_ids = {
        source.get("document_id")
        for target_result in request.reconciliation_result.get("targets", [])
        for source in target_result.get("result", {}).get("used_sources", [])
        if isinstance(source, dict)
        and source.get("document_id") != request.extraction.get("document_id")
    }
    declared_support_hashes = input_data.get("supporting_extraction_hashes", {})
    for document_id in sorted(used_supporting_ids):
        supporting = next((item for item in request.supporting_extractions if item.get("document_id") == document_id), None)
        if supporting is None:
            continue
        if document_id not in declared_support_hashes:
            issues.append({"code": "supporting_extraction_hash_missing", "message": f"Reconciliation did not bind supporting document {document_id} to an input hash"})
        elif not supporting.get("input_hash"):
            issues.append({"code": "supporting_extraction_hash_unverifiable", "message": f"Supporting Extraction {document_id} has no input_hash to verify"})
    return issues


def _normalized_proof_value(value: Any, value_type: str, currency: str | None = None) -> Any:
    if value_type == "money":
        if isinstance(value, dict):
            amount, currency = value.get("amount"), value.get("currency")
        else:
            amount = value
        try:
            amount = format(Decimal(str(amount)).normalize(), "f")
        except Exception:
            amount = str(amount)
        return {"amount": amount, "currency": currency}
    if value_type in {"decimal", "integer", "quantity"}:
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except Exception:
            return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _calculation_proof_diagnostics(
    expected: dict[str, Any], calculation_id: str, checks: list[SourceCheck]
) -> list[dict[str, Any]]:
    """Validate the handoff proof graph without re-running Reconciliation arithmetic."""
    issues: list[dict[str, Any]] = []
    declared_id = expected.get("calculation_id")
    if declared_id is not None and declared_id != calculation_id:
        issues.append({"code": "calculation_id_mismatch", "message": "Target result calculation_id differs from run metadata"})
    proof = expected.get("calculation_proof")
    if isinstance(proof, dict) and proof.get("calculation_id") not in (None, calculation_id):
        issues.append({"code": "calculation_id_mismatch", "message": "Calculation proof calculation_id differs from run metadata"})

    sources = expected.get("used_sources", [])
    source_by_id = {source.get("source_id"): source for source in sources if isinstance(source, dict)}
    if len(source_by_id) != len(sources):
        issues.append({"code": "calculation_source_id_duplicate", "message": "Used source IDs must be unique within a target"})
    operations = expected.get("operations", [])
    operation_by_id = {operation.get("operation_id"): operation for operation in operations if isinstance(operation, dict)}
    if not operations:
        issues.append({"code": "calculation_proof_unverified", "message": "No calculation operations were supplied to support the result"})
    if len(operation_by_id) != len(operations):
        issues.append({"code": "calculation_operation_id_duplicate", "message": "Operation IDs must be unique within a target"})
    referenced_source_ids: set[str] = set()
    for operation in operations:
        operation_id = operation.get("operation_id")
        inputs = operation.get("input_source_ids", [])
        referenced_source_ids.update(inputs)
        if not operation.get("formula"):
            issues.append({"code": "calculation_formula_missing", "message": f"Operation {operation_id} has no formula"})
        else:
            mentioned = {
                source_id for source_id in source_by_id
                if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(str(source_id))}(?![A-Za-z0-9_-])", operation["formula"])
            }
            if mentioned and mentioned != set(inputs):
                issues.append({"code": "calculation_formula_input_mismatch", "message": f"Operation {operation_id} formula and input_source_ids refer to different sources"})
        for source_id in inputs:
            if source_id not in source_by_id:
                issues.append({"code": "calculation_input_source_unresolved", "message": f"Operation {operation_id} references an undeclared used source"})
    for source_id, source in source_by_id.items():
        declared_operations = source.get("operation_ids", [])
        if not declared_operations:
            issues.append({"code": "calculation_source_operation_missing", "message": f"Used source {source_id} is not bound to an operation"})
        for operation_id in declared_operations:
            operation = operation_by_id.get(operation_id)
            if operation is None:
                issues.append({"code": "calculation_operation_unresolved", "message": f"Used source {source_id} references a missing operation"})
            elif source_id not in operation.get("input_source_ids", []):
                issues.append({"code": "calculation_operation_source_mismatch", "message": f"Operation {operation_id} does not list its declared source input"})
        if operations and source_id not in referenced_source_ids:
            issues.append({"code": "calculation_source_unused", "message": f"Used source {source_id} is not consumed by a declared operation"})

    excluded_ids = {source.get("source_id") for source in expected.get("excluded_sources", []) if isinstance(source, dict)}
    if referenced_source_ids & excluded_ids:
        issues.append({"code": "excluded_source_used", "message": "An excluded source is also listed as a calculation input"})
    if checks and any(not check.is_automatically_confirmed for check in checks):
        issues.append({"code": "calculation_evidence_unverified", "message": "One or more used sources are not technically and automatically validated"})

    expected_value = expected.get("expected_value")
    value_type = expected.get("value_type", "string")
    matching_outputs = [
        operation for operation in operations
        if _normalized_proof_value(operation.get("output_value"), value_type, expected.get("currency"))
        == _normalized_proof_value(expected_value, value_type, expected.get("currency"))
    ]
    if operations and not matching_outputs:
        issues.append({"code": "calculation_output_mismatch", "message": "No declared operation output matches the Reconciliation result value"})
    elif operations and len(matching_outputs) > 1:
        issues.append({"code": "calculation_output_ambiguous", "message": "More than one operation output could be the final Reconciliation value"})
    formula = expected.get("formula")
    if not formula:
        issues.append({"code": "calculation_formula_missing", "message": "The target result has no declared formula"})
    elif len(operations) == 1 and operations[0].get("operation_type") != "period_selection" and formula != operations[0].get("formula"):
        issues.append({"code": "calculation_formula_mismatch", "message": "Target formula differs from its sole declared operation formula"})
    return issues


def _validate_reconciliation_semantics(request: VerificationRequest) -> None:
    targets = request.reconciliation_result["targets"]
    seen_ids: set[str] = set()
    issues: list[ContractIssue] = []
    for index, item in enumerate(targets):
        target_id = item["target_id"]
        if target_id in seen_ids:
            issues.append(ContractIssue(f"/reconciliation_result/targets/{index}/target_id", "target_id must be unique", "reconciliation-result-1.0.0"))
        seen_ids.add(target_id)
        target = item["target"]
        if target["source_document_id"] != request.extraction.get("document_id"):
            issues.append(ContractIssue(f"/reconciliation_result/targets/{index}/target/source_document_id", "Each target must reference the supplied primary KFZ extraction", "reconciliation-result-1.0.0"))
        if target["extraction_id"] != request.extraction.get("extraction_id"):
            issues.append(ContractIssue(f"/reconciliation_result/targets/{index}/target/extraction_id", "Target extraction_id does not match the supplied primary extraction", "reconciliation-result-1.0.0"))
    if issues:
        raise ContractValidationError(issues)


def _missing_expected_result(
    extraction: dict[str, Any],
    context: VerificationContext,
    semantic_key: str,
    label: str | None,
    value_type: str,
    pointer: str,
) -> IndicatorResult:
    actual, actual_issues, _ = _actual_evidence(
        extraction,
        {"source_document_id": extraction.get("document_id"), "extraction_id": extraction.get("extraction_id"), "period": None, "unit": None},
        pointer,
        value_type,
        context,
    )
    issues = [{"code": "expected_value_not_provided", "message": "No matching target was present in the Reconciliation result"}, *actual_issues]
    status = VerificationStatus.INSUFFICIENT_DATA
    if any(issue.get("code") in {"actual_review_required", "actual_conflict"} for issue in actual_issues):
        status = VerificationStatus.NEEDS_REVIEW
    actual_ref = actual.model_dump(mode="json") if actual else None
    return IndicatorResult(
        target_id=f"unreconciled:{semantic_key}",
        semantic_key=semantic_key,
        label=label,
        value_type=value_type,
        status=status,
        actual=actual,
        expected=None,
        evidence=EvidenceTrace(actual_reference=actual_ref),
        trust=EvidenceTrust(
            technical_validity="valid" if actual is not None and not actual_issues else "incomplete" if actual is not None else "invalid",
            automatic_link_confirmation="not_required",
            human_confirmation="unconfirmed",
            calculation_trust="unproven",
        ),
        diagnostics=issues,
        uncertainty=Uncertainty(
            level="high",
            reasons=["reconciliation_target_missing"],
            manual_review_required=True,
            status_reason="The actual metric exists, but no expected value was supplied.",
        ),
    )


def _extraction_candidates(extraction: dict[str, Any]) -> list[tuple[str, str | None, str, str]]:
    candidates: list[tuple[str, str | None, str, str]] = []
    seen: set[str] = set()
    for indicator in extraction.get("indicators", []):
        if not isinstance(indicator, dict) or not isinstance(indicator.get("key"), str):
            continue
        key = indicator["key"]
        pointer = f"/fields/{key}/value"
        try:
            resolve_pointer(extraction, pointer)
        except ReferenceResolutionError:
            # Some Extraction implementations expose the indicator only under indicators[].
            index = extraction.get("indicators", []).index(indicator)
            pointer = f"/indicators/{index}/extracted/value"
        try:
            value = resolve_pointer(extraction, pointer)
        except ReferenceResolutionError:
            continue
        if pointer in seen:
            continue
        seen.add(pointer)
        candidates.append((key, indicator.get("label"), _infer_type(value, indicator.get("label"), key), pointer))

    for index, row in enumerate(extraction.get("line_items", [])):
        if not isinstance(row, dict):
            continue
        row_id = row.get("row_id", str(index))
        for field_key in ("quantity", "plan_quantity", "actual_quantity", "unit_price", "amount"):
            field = row.get(field_key)
            if not isinstance(field, dict) or "value" not in field:
                continue
            semantic = f"line_item:{row_id}:{field_key}"
            pointer = f"/line_items/{index}/{field_key}/value"
            kind = "money" if field_key in {"unit_price", "amount"} else "quantity"
            candidates.append((semantic, field.get("label") or semantic, kind, pointer))
    return candidates


def _classify_value_categories(
    result: IndicatorResult,
    source_checks: list[SourceCheck],
    explicit_diagnostics: list[dict[str, Any]],
    excluded_sources: list[dict[str, Any]],
    actual_issues: list[dict[str, Any]],
    evidence_valid: bool,
) -> None:
    result.discrepancies.extend(classify_reconciliation_diagnostics(explicit_diagnostics, source_checks, excluded_sources))
    result.discrepancies.extend(classify_linking_issue(source_checks))
    result.discrepancies.extend(classify_value_difference(result.difference.model_dump(mode="json"), result.value_type, evidence_valid))
    for diagnostic in result.diagnostics:
        if diagnostic.get("code") in {"currency_mismatch", "unit_mismatch"} and not any(
            item.category == "incompatible_unit" and item.description == diagnostic.get("message")
            for item in result.discrepancies
        ):
            result.discrepancies.append(Discrepancy(
                category="incompatible_unit",
                established=evidence_valid,
                hypothesis=not evidence_valid,
                description=diagnostic.get("message", "Actual and expected units are incompatible."),
                evidence_references=["actual", "expected"],
            ))
        elif diagnostic.get("code") in {"economic_meaning_mismatch", "value_type_mismatch", "comparison_basis_mismatch", "vat_basis_mismatch"}:
            result.discrepancies.append(Discrepancy(
                category="economic_meaning_mismatch",
                established=evidence_valid,
                hypothesis=not evidence_valid,
                description=diagnostic.get("message", "The values use different economic meanings or bases."),
                evidence_references=["actual", "expected"],
            ))
    established_causes = {
        "wrong_period", "duplicate_operation", "missing_supporting_document", "incorrect_document_link",
        "conflicting_primary_documents", "incompatible_unit", "rounding_problem",
    }
    has_cause = any(item.established and item.category.value in established_causes for item in result.discrepancies)
    accepted_by_tolerance = result.difference.accepted_by in {"absolute_tolerance", "relative_tolerance"}
    if result.difference.absolute not in (None, "0", "0.0", "0.00") and not has_cause and not accepted_by_tolerance:
        result.discrepancies.append(Discrepancy(
            category="unsubstantiated_cause",
            established=False,
            hypothesis=True,
            description="A value difference is established, but the available evidence does not establish its cause.",
            evidence_references=["actual", "expected"],
        ))


def _make_target_result(
    item: ReconciliationTarget,
    request: VerificationRequest,
    extraction_index: dict[str, dict[str, Any]],
    run_diagnostics: list[dict[str, Any]],
) -> IndicatorResult:
    target_id = item.target_id
    target = item.target
    expected_result = item.result
    context = request.context
    pointer = target["json_pointer"]
    value_type = target["value_type"]
    actual, actual_issues, actual_unit = _actual_evidence(request.extraction, target, pointer, value_type, context)
    checks, excluded = _source_data(item, request, extraction_index)
    source_diagnostics = [issue for check in checks for issue in check.issues]
    diagnostics = [*run_diagnostics, *actual_issues, *source_diagnostics]
    proof_diagnostics = _calculation_proof_diagnostics(
        expected_result,
        request.reconciliation_result["run_metadata"]["calculation_id"],
        checks,
    )
    diagnostics.extend(proof_diagnostics)
    explicit_diagnostics = expected_result.get("diagnostics", [])
    expected_value = expected_result.get("expected_value")
    expected = _expected_evidence(expected_result, target, target_id, item.array_index) if expected_value is not None else None
    actual_value = actual.normalized_value if actual else None
    actual_currency = actual.currency if actual else target.get("currency")
    expected_currency = expected.currency if expected else expected_result.get("currency")
    expected_unit = expected.unit if expected else expected_result.get("unit")
    comparison = None
    status = VerificationStatus.INSUFFICIENT_DATA
    uncertainty_reasons: list[str] = []

    if expected_result["calculation_status"] == "not_applicable" or not expected_result["comparison_eligible"]:
        status = VerificationStatus.NOT_APPLICABLE
        diagnostics.append({"code": "comparison_not_eligible", "message": "Reconciliation declared this target non-comparable"})
    elif expected_result["calculation_status"] in {"incomplete", "invalid"}:
        status = VerificationStatus.INSUFFICIENT_DATA
        diagnostics.append({"code": "reconciliation_incomplete", "message": f"Reconciliation calculation_status is {expected_result['calculation_status']}"})
    elif expected_value is None:
        status = VerificationStatus.INSUFFICIENT_DATA
        diagnostics.append({"code": "expected_value_missing", "message": "Expected value is explicitly null; it is not treated as zero"})
    elif not actual or actual.normalized_value is None:
        status = VerificationStatus.INSUFFICIENT_DATA
    elif target["semantic_key"] != expected_result["semantic_key"]:
        status = VerificationStatus.NOT_APPLICABLE
        diagnostics.append({"code": "economic_meaning_mismatch", "message": "Actual and expected values refer to different semantic indicators"})
    elif target["value_type"] != expected_result["value_type"]:
        status = VerificationStatus.NOT_APPLICABLE
        diagnostics.append({"code": "value_type_mismatch", "message": "Actual and expected values have different types"})
    elif target["comparison_basis"] != expected_result["comparison_basis"]:
        status = VerificationStatus.NOT_APPLICABLE
        diagnostics.append({"code": "comparison_basis_mismatch", "message": "Actual and expected values use different economic bases (for example plan versus actual)"})
    elif "unknown" in {target["comparison_basis"], expected_result["comparison_basis"]}:
        status = VerificationStatus.NEEDS_REVIEW
        uncertainty_reasons.append("comparison_basis_unknown")
    elif value_type == "money" and target["vat_basis"] != expected_result["vat_basis"]:
        status = VerificationStatus.NOT_APPLICABLE
        diagnostics.append({"code": "vat_basis_mismatch", "message": "Gross and net amounts cannot be compared directly"})
    elif value_type == "money" and target["vat_basis"] == "unknown":
        status = VerificationStatus.NEEDS_REVIEW
        uncertainty_reasons.append("vat_basis_unknown")
    elif target.get("unit") and expected_result.get("unit") and target["unit"] != expected_result["unit"]:
        status = VerificationStatus.NOT_APPLICABLE
        diagnostics.append({"code": "unit_mismatch", "message": f"Actual and expected units differ: {target['unit']} vs {expected_result['unit']}"})
    else:
        actual_period = _target_period(target, request.extraction, context)
        expected_period = expected_result.get("period") or (context.period.model_dump(mode="json") if context.period else None)
        if expected_result.get("period") is None and context.period is not None:
            diagnostics.append({"code": "expected_period_from_context", "message": "User context supplies the comparison period; it does not establish the Extraction period"})
        if actual_period and expected_period and actual_period != expected_period:
            status = VerificationStatus.MISMATCH
            diagnostics.append({"code": "period_mismatch", "message": f"Actual period {actual_period} differs from expected period {expected_period}"})
            if expected_result["calculation_status"] != "complete" or not checks or any(issue.get("code") in INSUFFICIENT_SOURCE_CODES for issue in source_diagnostics):
                status = VerificationStatus.INSUFFICIENT_DATA
            elif any(issue.get("code") in REVIEW_SOURCE_CODES for issue in source_diagnostics):
                status = VerificationStatus.NEEDS_REVIEW
            elif any(issue.get("code") in {"actual_provenance_missing", "actual_provenance_document_mismatch", "actual_source_unavailable", "actual_locator_missing", "actual_reference_unresolved", "actual_value_missing", "actual_value_wrapper_missing"} for issue in actual_issues):
                status = VerificationStatus.INSUFFICIENT_DATA
            elif any(issue.get("code") in {"actual_review_required", "actual_conflict", "actual_period_conflict", "actual_period_requires_review", "target_row_mismatch", "actual_currency_metadata_mismatch", "actual_unit_metadata_mismatch"} for issue in actual_issues):
                status = VerificationStatus.NEEDS_REVIEW
        elif value_type in {"money", "quantity", "decimal", "integer"} and (not actual_period or not expected_period):
            status = VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("comparison_period_unknown")
        elif not actual_period and not expected_period and value_type in {"period", "date", "string", "boolean"}:
            actual_period = None
        elif actual_period is None or expected_period is None:
            status = VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("comparison_period_unknown")

        if status not in {VerificationStatus.MISMATCH, VerificationStatus.NEEDS_REVIEW}:
            if expected_result["calculation_status"] != "complete":
                status = VerificationStatus.INSUFFICIENT_DATA
            elif not checks:
                status = VerificationStatus.INSUFFICIENT_DATA
                diagnostics.append({"code": "calculation_sources_missing", "message": "A complete Reconciliation result must identify its used source values"})
            elif any(issue.get("code") in INSUFFICIENT_SOURCE_CODES for issue in source_diagnostics):
                status = VerificationStatus.INSUFFICIENT_DATA
            elif any(issue.get("code") in REVIEW_SOURCE_CODES for issue in source_diagnostics):
                status = VerificationStatus.NEEDS_REVIEW
                uncertainty_reasons.append("calculation_evidence_not_automatically_validated")
            elif any(issue.get("code") in {"actual_provenance_missing", "actual_provenance_document_mismatch", "actual_source_unavailable", "actual_locator_missing", "actual_reference_unresolved", "actual_value_missing", "actual_value_wrapper_missing"} for issue in actual_issues):
                status = VerificationStatus.INSUFFICIENT_DATA
            elif any(issue.get("code") in {"actual_review_required", "actual_conflict", "actual_period_conflict", "actual_period_requires_review", "target_row_mismatch", "actual_currency_metadata_mismatch", "actual_unit_metadata_mismatch"} for issue in actual_issues):
                status = VerificationStatus.NEEDS_REVIEW
                uncertainty_reasons.append("actual_extraction_requires_review")
            else:
                outcome = compare_metric(
                    actual=actual_value,
                    expected=expected_value,
                    value_type=value_type,
                    context=context,
                    actual_currency=actual_currency,
                    expected_currency=expected_currency,
                    actual_unit=actual_unit or target.get("unit"),
                    expected_unit=expected_unit,
                )
                comparison = outcome
                diagnostics.extend(outcome.issues)
                uncertainty_reasons.extend(outcome.uncertainty_reasons)
                if not outcome.comparable:
                    code = {issue.get("code") for issue in outcome.issues}
                    if code & {"currency_mismatch", "unit_mismatch"}:
                        status = VerificationStatus.NOT_APPLICABLE
                    else:
                        status = VerificationStatus.NEEDS_REVIEW
                else:
                    evidence_valid = all(check.is_automatically_confirmed for check in checks)
                    if outcome.equal and evidence_valid:
                        status = VerificationStatus.MATCHED
                    elif outcome.equal:
                        status = VerificationStatus.NEEDS_REVIEW
                        uncertainty_reasons.append("evidence_not_automatically_validated")
                    elif evidence_valid:
                        status = VerificationStatus.MISMATCH
                    else:
                        status = VerificationStatus.NEEDS_REVIEW
                        uncertainty_reasons.append("difference_uses_unconfirmed_or_incomplete_evidence")

    # Keep an arithmetic trace even when evidence is not conclusive. The status
    # remains review/insufficient until the calculation and source chain qualify.
    blocked_codes = {
        "economic_meaning_mismatch", "value_type_mismatch", "comparison_basis_mismatch",
        "vat_basis_mismatch", "unit_mismatch", "period_mismatch", "currency_mismatch",
        "actual_currency_metadata_mismatch", "actual_unit_metadata_mismatch",
    }
    if (
        comparison is None
        and actual is not None
        and actual.normalized_value is not None
        and expected_value is not None
        and not any(diagnostic.get("code") in blocked_codes for diagnostic in diagnostics)
    ):
        outcome = compare_metric(
            actual=actual.normalized_value,
            expected=expected_value,
            value_type=value_type,
            context=context,
            actual_currency=actual_currency,
            expected_currency=expected_currency,
            actual_unit=actual_unit or target.get("unit"),
            expected_unit=expected_unit,
        )
        if outcome.comparable:
            comparison = outcome
            diagnostics.extend(outcome.issues)
            uncertainty_reasons.extend(outcome.uncertainty_reasons)
    used_by_id = {check.source.get("source_id"): check for check in checks}
    for item_diagnostic in explicit_diagnostics:
        code = item_diagnostic.get("code")
        confirmed = item_diagnostic.get("confirmed") is True
        diagnostic_status: VerificationStatus | None = None
        if code in {"missing_document", "incomplete_sources"}:
            diagnostic_status = VerificationStatus.INSUFFICIENT_DATA if confirmed else VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("reconciliation_reports_missing_or_incomplete_source")
        elif code == "duplicate_suspected":
            diagnostic_status = VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("duplicate_operation_only_suspected")
        elif code == "duplicate_confirmed":
            ids = item_diagnostic.get("source_ids", [])
            operation_sets = [set(used_by_id[source_id].source.get("operation_ids", [])) for source_id in ids if source_id in used_by_id]
            references_resolve = all(source_id in used_by_id and used_by_id[source_id].is_automatically_confirmed for source_id in ids)
            shared_operation = len(operation_sets) >= 2 and bool(set.intersection(*operation_sets))
            diagnostic_status = VerificationStatus.MISMATCH if confirmed and len(set(ids)) >= 2 and references_resolve and shared_operation else VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("confirmed_duplicate_operation" if diagnostic_status == VerificationStatus.MISMATCH else "duplicate_evidence_incomplete")
        elif code == "wrong_period":
            ids = item_diagnostic.get("source_ids", [])
            refs = item_diagnostic.get("evidence_references", [])
            references_resolve = bool(ids) and all(source_id in used_by_id and used_by_id[source_id].is_automatically_confirmed for source_id in ids)
            known_refs = set(used_by_id) | {operation_id for check in checks for operation_id in check.source.get("operation_ids", [])}
            refs_resolve = bool(refs) and all(reference in known_refs for reference in refs)
            actual_period = _target_period(target, request.extraction, context)
            expected_period = expected_result.get("period") or (context.period.model_dump(mode="json") if context.period else None)
            periods_differ = bool(actual_period and expected_period and actual_period != expected_period)
            diagnostic_status = VerificationStatus.MISMATCH if confirmed and references_resolve and refs_resolve and periods_differ and expected_result.get("calculation_status") == "complete" else VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("confirmed_wrong_period" if diagnostic_status == VerificationStatus.MISMATCH else "wrong_period_evidence_incomplete")
        elif code == "conflicting_documents":
            diagnostic_status = VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("conflicting_primary_document_evidence")
        elif code == "invalid_unit":
            diagnostic_status = VerificationStatus.NOT_APPLICABLE if confirmed else VerificationStatus.NEEDS_REVIEW
        elif code == "rounding_rule_unknown":
            diagnostic_status = VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("rounding_policy_not_known")
        elif code not in {"missing_document", "incomplete_sources", "duplicate_suspected", "duplicate_confirmed", "conflicting_documents", "invalid_unit", "rounding_rule_unknown"}:
            diagnostic_status = VerificationStatus.NEEDS_REVIEW
            diagnostics.append({"code": "unrecognized_reconciliation_diagnostic", "message": "An unsupported Reconciliation diagnostic requires review"})
            uncertainty_reasons.append("unrecognized_reconciliation_diagnostic")
        if diagnostic_status is not None:
            status = aggregate_status([status, diagnostic_status])
        if not confirmed and code not in {"duplicate_suspected", "missing_document", "incomplete_sources"}:
            uncertainty_reasons.append(f"unconfirmed_reconciliation_diagnostic:{code}")
            if status == VerificationStatus.MATCHED:
                status = VerificationStatus.NEEDS_REVIEW
    if run_diagnostics:
        status = VerificationStatus.INSUFFICIENT_DATA
        uncertainty_reasons.append("reconciliation_run_metadata_mismatch")
    elif proof_diagnostics and status != VerificationStatus.NOT_APPLICABLE:
        if any(issue.get("code") in INVALID_PROOF_CODES for issue in proof_diagnostics):
            status = VerificationStatus.INSUFFICIENT_DATA
            uncertainty_reasons.append("calculation_proof_invalid")
        elif status not in {VerificationStatus.INSUFFICIENT_DATA, VerificationStatus.NEEDS_REVIEW}:
            status = VerificationStatus.NEEDS_REVIEW
            uncertainty_reasons.append("calculation_proof_unverified")

    difference_data = comparison.difference if comparison is not None else {}
    if any(d.get("code") == "period_mismatch" for d in diagnostics):
        period_proof = (
            bool(checks)
            and all(check.is_automatically_confirmed for check in checks)
            and expected_result.get("calculation_status") == "complete"
            and not source_diagnostics
            and not actual_issues
            and not run_diagnostics
        )
        discrepancy_items = [
            {"category": "wrong_period", "established": period_proof, "hypothesis": not period_proof, "description": diagnostic["message"], "evidence_references": ["actual.period", "expected.period"]}
            for diagnostic in diagnostics if diagnostic.get("code") == "period_mismatch"
        ]
    else:
        discrepancy_items = []
    proof_complete = (
        bool(checks)
        and all(check.is_automatically_confirmed for check in checks)
        and expected_result.get("calculation_status") == "complete"
        and not run_diagnostics
        and not proof_diagnostics
        and not any(issue.get("code") in INSUFFICIENT_SOURCE_CODES | REVIEW_SOURCE_CODES for issue in source_diagnostics)
        and not any(issue.get("code") in {"actual_provenance_missing", "actual_provenance_document_mismatch", "actual_source_unavailable", "actual_locator_missing", "actual_reference_unresolved", "actual_value_missing", "actual_value_wrapper_missing", "actual_conflict", "actual_review_required", "actual_currency_metadata_mismatch", "actual_unit_metadata_mismatch", "actual_period_requires_review", "actual_period_invalid", "actual_period_missing"} for issue in actual_issues)
        and not any(diagnostic.get("code") in {"missing_document", "incomplete_sources", "conflicting_documents", "duplicate_suspected"} for diagnostic in explicit_diagnostics)
    )
    result = IndicatorResult(
        target_id=target_id,
        semantic_key=target.get("semantic_key"),
        label=target.get("label"),
        value_type=value_type,
        status=status,
        actual=actual,
        expected=expected,
        difference=Difference(**difference_data),
        discrepancies=discrepancy_items,
        evidence=EvidenceTrace(
            actual_reference={
                "document_id": target.get("source_document_id"),
                "extraction_id": target.get("extraction_id"),
                "json_pointer": pointer,
                "row_id": target.get("row_id") or (actual.row_id if actual else None),
                "source_value": actual.source_value if actual else None,
                "normalized_value": actual.normalized_value if actual else None,
                "provenance": actual.provenance if actual else None,
            },
            reconciliation_reference={
                "run_id": request.reconciliation_result["run_metadata"]["run_id"],
                "calculation_id": request.reconciliation_result["run_metadata"]["calculation_id"],
                "target_id": target_id,
                "json_pointer": f"/targets/{item.array_index}/result",
                "formula": expected_result.get("formula"),
                "operations": expected_result.get("operations", []),
                "applied_rules": expected_result.get("applied_rules", []),
                "provenance": expected_result.get("provenance", []),
            },
            used_sources=[check.as_trace() for check in checks],
            excluded_sources=excluded,
            linking_references=[
                {"link_id": check.link.get("link_id"), "status": check.link.get("status"), "verification_status": check.link.get("verification_status"), "evidence": check.link_evidence}
                for check in checks if check.link
            ],
            provenance_chain=[
                *([{"stage": "extraction", "document_id": target.get("source_document_id"), "extraction_id": target.get("extraction_id"), "json_pointer": pointer, "provenance": actual.provenance}] if actual else []),
                {"stage": "reconciliation", "run_id": request.reconciliation_result["run_metadata"]["run_id"], "calculation_id": request.reconciliation_result["run_metadata"]["calculation_id"], "target_id": target_id, "operations": expected_result.get("operations", []), "used_sources": [check.as_trace() for check in checks]},
            ],
        ),
        trust=EvidenceTrust(
            technical_validity=(
                "invalid" if any(issue.get("code") in INVALID_PROOF_CODES | INVALID_RUN_CODES | INVALID_SOURCE_CODES | {
                    "actual_reference_unresolved", "actual_value_missing", "actual_value_wrapper_missing",
                    "actual_provenance_missing", "actual_provenance_document_mismatch", "actual_source_unavailable",
                    "actual_locator_missing", "actual_conflict", "actual_period_conflict",
                } for issue in [*actual_issues, *proof_diagnostics, *run_diagnostics, *source_diagnostics])
                else "incomplete" if any(not check.is_technically_valid for check in checks) or not checks or any(issue.get("code") in UNVERIFIED_RUN_CODES for issue in run_diagnostics)
                else "valid"
            ),
            automatic_link_confirmation=(
                "not_required" if not any(check.source.get("link_id") for check in checks)
                else "rejected" if any(check.link and check.link.get("verification_status") == "human_rejected" for check in checks)
                else "confirmed" if all(check.is_automatically_confirmed for check in checks)
                else "unconfirmed"
            ),
            human_confirmation=(
                "not_required" if not checks
                else "rejected" if any(check.source.get("evidence_status") == "rejected" or (check.link and check.link.get("verification_status") == "human_rejected") for check in checks)
                else "confirmed" if all(check.is_human_confirmed for check in checks)
                else "unconfirmed"
            ),
            calculation_trust=(
                "not_applicable" if status == VerificationStatus.NOT_APPLICABLE
                else "invalid" if any(issue.get("code") in INVALID_PROOF_CODES | INVALID_RUN_CODES | INVALID_SOURCE_CODES for issue in [*proof_diagnostics, *run_diagnostics, *source_diagnostics])
                else "proven" if proof_complete
                else "unproven"
            ),
        ),
        comparison_rules={
            "value_type": value_type,
            "actual_currency": actual_currency,
            "expected_currency": expected_currency,
            "actual_unit": actual_unit or target.get("unit"),
            "expected_unit": expected_unit,
            "actual_vat_basis": target.get("vat_basis"),
            "expected_vat_basis": expected_result.get("vat_basis"),
            "actual_comparison_basis": target.get("comparison_basis"),
            "expected_comparison_basis": expected_result.get("comparison_basis"),
            "tolerance": context.tolerance.model_dump(mode="json"),
            "period": {
                "actual": _target_period(target, request.extraction, context),
                "expected": expected_result.get("period") or (context.period.model_dump(mode="json") if context.period else None),
                "expected_source": "reconciliation" if expected_result.get("period") is not None else "user_context" if context.period else None,
            },
            "applied_rules": expected_result.get("applied_rules", []),
            "formula": "actual - expected" if value_type in {"money", "decimal", "quantity", "integer"} else "type-specific equality",
        },
        diagnostics=diagnostics,
        uncertainty=Uncertainty(
            level="none" if status in {VerificationStatus.MATCHED, VerificationStatus.NOT_APPLICABLE} else "high" if status in {VerificationStatus.INSUFFICIENT_DATA, VerificationStatus.NEEDS_REVIEW} else "medium",
            reasons=list(dict.fromkeys(uncertainty_reasons)),
            manual_review_required=status in {VerificationStatus.INSUFFICIENT_DATA, VerificationStatus.NEEDS_REVIEW},
            status_reason=_status_reason(status, diagnostics),
        ),
    )
    _classify_value_categories(result, checks, explicit_diagnostics, excluded, actual_issues, proof_complete)
    return result


def _status_reason(status: VerificationStatus, diagnostics: list[dict[str, Any]]) -> str:
    if status == VerificationStatus.MATCHED:
        return "Values are compatible and equal under explicit rules, with a complete calculation proof and validated source references."
    if status == VerificationStatus.MISMATCH:
        return "A reproducible difference or period mismatch is established using a complete, validated calculation basis."
    if status == VerificationStatus.NOT_APPLICABLE:
        return "The values cannot be compared under the declared economic meaning, basis, currency, or units."
    if status == VerificationStatus.INSUFFICIENT_DATA:
        return "A required value, source, provenance reference, or complete calculation basis is unavailable."
    return "The data is ambiguous, unconfirmed, or requires expert interpretation before a conclusion can be confirmed."


def _make_unreconciled_results(request: VerificationRequest, compared_semantics: set[str]) -> list[IndicatorResult]:
    results: list[IndicatorResult] = []
    for semantic, label, kind, pointer in _extraction_candidates(request.extraction):
        if semantic in compared_semantics:
            continue
        results.append(_missing_expected_result(request.extraction, request.context, semantic, label, kind, pointer))
    return results


def run_verification(
    request: VerificationRequest,
    verification_id: str | None = None,
    created_at: str | None = None,
    input_fingerprint: str | None = None,
    explanation_provider: ReviewExplanationProvider | None = None,
    deadline: float | None = None,
) -> VerificationResult:
    def ensure_time_remaining() -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("Verification processing time limit exceeded")

    ensure_time_remaining()
    validate_request_contracts(request)
    _validate_reconciliation_semantics(request)
    fingerprint = input_fingerprint or canonical_fingerprint(request)
    verification_id = verification_id or f"ver_{fingerprint[:24]}"
    created_at = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    extraction_index = {
        item["document_id"]: item
        for item in [request.extraction, *request.supporting_extractions]
        if isinstance(item, dict) and isinstance(item.get("document_id"), str)
    }
    run_diagnostics = _reconciliation_run_diagnostics(request)
    results: list[IndicatorResult] = []
    consumed_semantics: set[str] = set()
    adapter = get_reconciliation_adapter(request.reconciliation_result["contract_version"])
    for item in adapter.adapt(request.reconciliation_result):
        ensure_time_remaining()
        results.append(_make_target_result(item, request, extraction_index, run_diagnostics))
        consumed_semantics.add(item.target["semantic_key"])
    results.extend(_make_unreconciled_results(request, consumed_semantics))
    if explanation_provider is not None:
        for indicator in results:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                provider_timeout = getattr(explanation_provider, "timeout_seconds", 0)
                if remaining <= 0 or (provider_timeout and remaining <= provider_timeout):
                    break
            apply_review_suggestions(indicator, explanation_provider)

    counts = {status.value: 0 for status in VerificationStatus}
    for indicator in results:
        counts[indicator.status.value] += 1
    overall = aggregate_status([indicator.status for indicator in results])
    not_applicable_count = counts[VerificationStatus.NOT_APPLICABLE.value]
    matched_count = counts[VerificationStatus.MATCHED.value]
    mismatch_count = counts[VerificationStatus.MISMATCH.value]
    verified_count = matched_count + mismatch_count
    completeness = VerificationCompleteness(
        total_indicators=len(results),
        applicable_indicators=len(results) - not_applicable_count,
        verified_indicators=verified_count,
        matched_indicators=matched_count,
        mismatched_indicators=mismatch_count,
        not_applicable_indicators=not_applicable_count,
        unresolved_indicators=len(results) - verified_count - not_applicable_count,
        complete=bool(results) and verified_count == len(results),
    )
    run_diagnostics.extend(
        {"code": "indicator_requires_review", "target_id": indicator.target_id, "message": indicator.uncertainty.status_reason}
        for indicator in results
        if indicator.status in {VerificationStatus.NEEDS_REVIEW, VerificationStatus.INSUFFICIENT_DATA, VerificationStatus.MISMATCH}
    )
    return VerificationResult(
        verification_id=verification_id,
        project_id=request.project_id,
        calculation_id=request.reconciliation_result["run_metadata"]["calculation_id"],
        created_at=created_at,
        input_fingerprint=fingerprint,
        input_metadata={
            "structured_extraction": {
                "primary": {
                    "document_id": request.extraction.get("document_id"),
                    "extraction_id": request.extraction.get("extraction_id"),
                    "schema_version": request.extraction.get("schema_version"),
                    "input_hash": request.extraction.get("input_hash"),
                },
                "supporting": [
                    {
                        "document_id": extraction.get("document_id"),
                        "extraction_id": extraction.get("extraction_id"),
                        "schema_version": extraction.get("schema_version"),
                        "input_hash": extraction.get("input_hash"),
                    }
                    for extraction in request.supporting_extractions
                ],
            },
            "document_linking": {
                "schema_version": "1.2.0" if request.linking_result is not None else None,
                "payload_contract_version": request.linking_result.get("contract_version") if request.linking_result else None,
                "linking_run_id": request.linking_result.get("linking_run_id") if request.linking_result else None,
            },
            "reconciliation": {
                "contract_version": request.reconciliation_result.get("contract_version"),
                "run_id": request.reconciliation_result["run_metadata"]["run_id"],
                "calculation_id": request.reconciliation_result["run_metadata"]["calculation_id"],
                "engine_version": request.reconciliation_result["run_metadata"].get("reconciliation_engine_version"),
            },
        },
        overall_status=overall,
        summary=counts,
        completeness=completeness,
        indicators=results,
        diagnostics=run_diagnostics,
    )
