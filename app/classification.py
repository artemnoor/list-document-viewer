from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from app.evidence import SourceCheck
from app.models import Discrepancy, DiscrepancyCategory, VerificationStatus


def _item(
    category: DiscrepancyCategory,
    description: str,
    evidence: list[str] | None = None,
    established: bool = True,
    hypothesis: bool = False,
) -> Discrepancy:
    return Discrepancy(
        category=category,
        description=description,
        evidence_references=evidence or [],
        established=established,
        hypothesis=hypothesis,
    )


def classify_reconciliation_diagnostics(
    diagnostics: list[dict[str, Any]], source_checks: list[SourceCheck], excluded_sources: list[dict[str, Any]] | None = None
) -> list[Discrepancy]:
    """Classify only causes that carry explicit, resolvable source references."""
    by_id = {check.source.get("source_id"): check for check in source_checks}
    results: list[Discrepancy] = []
    for diagnostic in diagnostics:
        code = diagnostic.get("code")
        refs = diagnostic.get("evidence_references", [])
        source_ids = diagnostic.get("source_ids", [])
        confirmed = diagnostic.get("confirmed") is True
        sources_resolve = bool(source_ids) and all(
            source_id in by_id and by_id[source_id].is_human_confirmed for source_id in source_ids
        )
        has_refs = bool(refs) and all(
            ref in by_id or any(ref == operation_id for check in source_checks for operation_id in check.source.get("operation_ids", []))
            for ref in refs
        )

        if code == "duplicate_confirmed":
            operation_sets = [set(by_id[source_id].source.get("operation_ids", [])) for source_id in source_ids if source_id in by_id]
            shared_operation = len(operation_sets) >= 2 and bool(set.intersection(*operation_sets))
            supported = confirmed and len(set(source_ids)) >= 2 and sources_resolve and has_refs and shared_operation
            results.append(_item(
                DiscrepancyCategory.DUPLICATE_OPERATION,
                diagnostic.get("message", "Reconciliation reports a duplicate operation."),
                refs,
                established=supported,
                hypothesis=not supported,
            ))
        elif code == "duplicate_suspected":
            results.append(_item(
                DiscrepancyCategory.DUPLICATE_OPERATION,
                diagnostic.get("message", "A duplicate operation is only suspected."),
                refs,
                established=False,
                hypothesis=True,
            ))
        elif code == "missing_document":
            excluded_ids = {source.get("document_id") for source in (excluded_sources or [])}
            declared_docs = set(diagnostic.get("document_ids", []))
            supported = confirmed and bool(declared_docs) and bool(declared_docs & excluded_ids) and has_refs and sources_resolve
            results.append(_item(
                DiscrepancyCategory.MISSING_SUPPORTING_DOCUMENT,
                diagnostic.get("message", "Reconciliation reports a missing supporting document."),
                refs,
                established=supported,
                hypothesis=not supported,
            ))
        elif code == "wrong_period":
            results.append(_item(
                DiscrepancyCategory.WRONG_PERIOD,
                diagnostic.get("message", "Reconciliation reports a period mismatch."),
                refs,
                established=confirmed and sources_resolve and has_refs,
                hypothesis=not (confirmed and sources_resolve and has_refs),
            ))
        elif code == "conflicting_documents":
            values = [by_id[source_id].resolved_value for source_id in source_ids if source_id in by_id and by_id[source_id].reference_resolved]
            distinct = {json.dumps(value, sort_keys=True, ensure_ascii=False, default=str) for value in values}
            supported = confirmed and len(set(source_ids)) >= 2 and sources_resolve and has_refs and len(distinct) >= 2
            results.append(_item(
                DiscrepancyCategory.CONFLICTING_PRIMARY_DOCUMENTS,
                diagnostic.get("message", "Reconciliation reports conflicting primary documents."),
                refs,
                established=supported,
                hypothesis=not supported,
            ))
        elif code == "invalid_unit":
            results.append(_item(
                DiscrepancyCategory.INCOMPATIBLE_UNIT,
                diagnostic.get("message", "Reconciliation reports incompatible units."),
                refs,
                established=confirmed and sources_resolve and has_refs,
                hypothesis=not (confirmed and sources_resolve and has_refs),
            ))
        elif code == "rounding_rule_unknown":
            results.append(_item(
                DiscrepancyCategory.ROUNDING_PROBLEM,
                diagnostic.get("message", "The rounding rule is unknown."),
                refs,
                established=False,
                hypothesis=True,
            ))
    return results


def classify_linking_issue(source_checks: list[SourceCheck]) -> list[Discrepancy]:
    results: list[Discrepancy] = []
    seen: set[str] = set()
    for check in source_checks:
        link = check.link
        if not link:
            continue
        link_id = link.get("link_id")
        if link_id in seen:
            continue
        seen.add(link_id)
        if link.get("status") == "rejected" and link.get("verification_status") == "human_rejected":
            results.append(_item(
                DiscrepancyCategory.INCORRECT_DOCUMENT_LINK,
                "A used source depends on a link that was explicitly rejected by a reviewer.",
                [str(link_id)],
                established=True,
            ))
        elif link.get("status") in {"review", "proposed"} or link.get("verification_status") != "human_confirmed":
            results.append(_item(
                DiscrepancyCategory.INCORRECT_DOCUMENT_LINK,
                "The referenced document relationship has not been human-confirmed.",
                [str(link_id)],
                established=False,
                hypothesis=True,
            ))
        if link.get("conflicts"):
            results.append(_item(
                DiscrepancyCategory.CONFLICTING_PRIMARY_DOCUMENTS,
                "Linking reports conflicting evidence for a relationship used in the calculation.",
                [str(link_id)],
                established=False,
                hypothesis=True,
            ))
    return results


def classify_value_difference(
    difference: dict[str, Any], value_type: str, evidence_valid: bool
) -> list[Discrepancy]:
    amount = difference.get("absolute")
    if amount is None:
        return []
    try:
        nonzero = Decimal(str(amount)) != 0
    except (InvalidOperation, TypeError, ValueError):
        nonzero = False
    if not nonzero:
        return []
    category = DiscrepancyCategory.AMOUNT_DIFFERENCE if value_type == "money" else DiscrepancyCategory.INDICATOR_DIFFERENCE
    if difference.get("accepted_by") == "rounding":
        return [_item(
            DiscrepancyCategory.ROUNDING_PROBLEM,
            "Raw values differ, but the explicitly supplied rounding rule makes them equal.",
            ["actual", "expected"],
            established=evidence_valid,
            hypothesis=not evidence_valid,
        )]
    return [_item(
        category,
        "Actual and expected values differ under the declared comparison rules.",
        ["actual", "expected"],
        established=evidence_valid,
        hypothesis=not evidence_valid,
    )]


def aggregate_status(statuses: list[VerificationStatus]) -> VerificationStatus:
    if not statuses:
        return VerificationStatus.INSUFFICIENT_DATA
    # A run-level green result is only possible when every indicator is proven.
    for status in (
        VerificationStatus.NEEDS_REVIEW,
        VerificationStatus.INSUFFICIENT_DATA,
        VerificationStatus.MISMATCH,
    ):
        if status in statuses:
            return status
    if all(status == VerificationStatus.NOT_APPLICABLE for status in statuses):
        return VerificationStatus.NOT_APPLICABLE
    return VerificationStatus.MATCHED
