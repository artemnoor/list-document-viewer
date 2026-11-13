import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from pydantic import ValidationError

from .config import Settings
from .contracts import canonical_json, validate_upstream_inputs
from .engine import decimal_string, execute_plan, related_links_for_fact, validate_plan
from .errors import Diagnostic, InputContractError
from .facts import Fact, extract_facts, fact_input_hash, numeric_value
from .models import ReconciliationRequest, TargetIndicator
from .planner import LLMPlanner, PlannerUnavailable
from .plans import CalculationPlan
from .security import is_trusted_internal_endpoint


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _group_id(document_id: str) -> str:
    return "source_" + hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:16]


def input_snapshot_identity(request: ReconciliationRequest) -> dict[str, Any]:
    """Stable binding for the exact extraction, Linking, and target context inputs."""
    extraction_hashes = [
        {"document_id": item["document_id"], "extraction_id": item["extraction_id"], "version": item["version"], "schema_version": item["schema_version"], "sha256": _hash(item)}
        for item in sorted(request.extraction_results, key=lambda entry: entry["document_id"])
    ]
    linking_hash = _hash(request.linking_result)
    context_hash = _hash(request.context.model_dump(mode="json"))
    snapshot_hash = _hash({"extractions": extraction_hashes, "linking_sha256": linking_hash, "context_sha256": context_hash})
    linking_documents = {item.get("document_id"): item for item in request.linking_result.get("input_documents", [])}
    extraction_versions = {}
    for item in sorted(request.extraction_results, key=lambda entry: entry["document_id"]):
        linked = linking_documents.get(item["document_id"], {})
        extraction_versions[item["document_id"]] = {
            "extraction_id": item.get("extraction_id"),
            "version": item.get("version"),
            "schema_version": item.get("schema_version"),
            "input_version": linked.get("input_version"),
            "input_hash": linked.get("input_hash"),
            "sha256": _hash(item),
        }
    return {
        "extraction_hashes": extraction_hashes,
        "linking_sha256": linking_hash,
        "context_sha256": context_hash,
        "snapshot_sha256": snapshot_hash,
        "extraction_versions": extraction_versions,
    }


def bind_decision_to_request(
    request: ReconciliationRequest, decision: Any, plan: CalculationPlan
) -> Any:
    """Return a decision carrying hashes for its snapshot, selected values, and links."""
    identity = input_snapshot_identity(request)
    facts_by_id = {fact.fact_id: fact for fact in extract_facts(request.extraction_results)}
    links_by_id = {item.get("link_id"): item for item in request.linking_result.get("links", [])}
    changes = {
        "snapshot_sha256": identity["snapshot_sha256"],
        "linking_sha256": identity["linking_sha256"],
        "extraction_versions": identity["extraction_versions"],
        "confirmed_fact_hashes": {
            item.fact_id: fact_input_hash(facts_by_id[item.fact_id])
            for item in plan.included if item.fact_id in facts_by_id
        },
        "accepted_fact_hashes": {
            fact_id: fact_input_hash(facts_by_id[fact_id])
            for fact_id in decision.accepted_fact_ids if fact_id in facts_by_id
        },
        "accepted_link_hashes": {
            link_id: _hash(links_by_id[link_id])
            for link_id in decision.accepted_link_ids if link_id in links_by_id
        },
    }
    bound = decision.model_copy(update=changes)
    decision_sha256 = _hash(bound.model_dump(mode="json", exclude={"decision_sha256"}))
    return bound.model_copy(update={"decision_sha256": decision_sha256})


def _decision_binding_diagnostics(
    request: ReconciliationRequest, decision: Any, plan: CalculationPlan
) -> list[Diagnostic]:
    expected = bind_decision_to_request(request, decision, plan)
    fields = (
        "snapshot_sha256", "linking_sha256", "extraction_versions",
        "confirmed_fact_hashes", "accepted_fact_hashes", "accepted_link_hashes", "decision_sha256",
    )
    mismatched = [name for name in fields if getattr(decision, name) != getattr(expected, name)]
    if not mismatched:
        return []
    return [Diagnostic(
        "stale_human_decision", f"$.prior_decisions[{decision.decision_id}]",
        "Human confirmation does not match the exact extraction and Linking snapshot or confirmed values",
        {"mismatched_bindings": mismatched, "expected_snapshot_sha256": expected.snapshot_sha256, "actual_snapshot_sha256": decision.snapshot_sha256},
    )]


def _target_fact(target: TargetIndicator, facts_by_id: dict[str, Fact]) -> Fact:
    if target.target_fact_id:
        fact = facts_by_id.get(target.target_fact_id)
        if fact is None:
            raise InputContractError([Diagnostic(
                "target_indicator_not_found", "$.context.targets", "The target fact ID is not present in the Extraction snapshot",
                {"target_id": target.target_id, "target_fact_id": target.target_fact_id},
            )])
        if fact.document_id != target.kfz_document_id or fact.source_path != target.kfz_source_path:
            raise InputContractError([Diagnostic(
                "target_indicator_locator_mismatch", "$.context.targets", "The target fact ID does not match the supplied KФЗ document and JSON Pointer",
                {"target_id": target.target_id, "target_fact_id": target.target_fact_id, "document_id": target.kfz_document_id, "source_path": target.kfz_source_path},
            )])
        return fact

    matches = [fact for fact in facts_by_id.values() if fact.document_id == target.kfz_document_id and fact.source_path == target.kfz_source_path]
    if target.kfz_row_id is not None:
        matches = [fact for fact in matches if fact.row_id == target.kfz_row_id]
    if len(matches) != 1:
        raise InputContractError([Diagnostic(
            "target_indicator_not_found", "$.context.targets", "The supplied KФЗ document and JSON Pointer must identify exactly one Extraction fact",
            {"target_id": target.target_id, "document_id": target.kfz_document_id, "source_path": target.kfz_source_path, "match_count": len(matches)},
        )])
    return matches[0]


def _target_origin(fact: Fact) -> dict[str, Any]:
    return {
        "document_id": fact.document_id,
        "extraction_id": fact.extraction_id,
        "fact_id": fact.fact_id,
        "row_id": fact.row_id,
        "source_path": fact.source_path,
        "source_ref": (fact.provenance or {}).get("source_ref"),
    }


def _source_record(fact: Fact, linking: dict[str, Any]) -> dict[str, Any]:
    links = related_links_for_fact(fact, linking)
    return {
        "fact_id": fact.fact_id,
        "document_id": fact.document_id,
        "extraction_id": fact.extraction_id,
        "document_type": fact.document_type,
        "row_id": fact.row_id,
        "source_path": fact.source_path,
        "role": fact.role,
        "key": fact.key,
        "label": fact.label,
        "value": fact.normalized_value,
        "numeric_value": str(fact.value) if fact.value is not None else None,
        "source_value": fact.source_value,
        "status": fact.status,
        "confidence": fact.confidence,
        "currency": fact.currency,
        "unit": fact.unit,
        "economic_measure": fact.economic_measure,
        "provenance": fact.provenance,
        "input_hash": fact_input_hash(fact),
        "related_links": [
            {
                "link_id": link.get("link_id"),
                "relationship_type": link.get("relationship_type"),
                "source_document_id": link.get("source_document_id"),
                "target_document_id": link.get("target_document_id"),
                "source_row_id": link.get("source_row_id"),
                "target_row_id": link.get("target_row_id"),
                "status": link.get("status"),
                "verification_status": link.get("verification_status"),
                "confidence": link.get("confidence"),
                "evidence": link.get("evidence", []),
            }
            for link in links
        ],
    }


def _format_formula(plan: CalculationPlan) -> str:
    labels: dict[str, str] = {}
    for item in plan.included:
        labels[item.fact_id] = item.fact_id
    expressions: dict[str, str] = {}
    for step in plan.steps:
        args = [expressions.get(value, labels.get(value, value)) for value in step.inputs]
        if step.operation == "sum":
            expression = " + ".join(args)
        elif step.operation == "add":
            expression = " + ".join(args)
        elif step.operation == "subtract":
            expression = f"({args[0]} - {args[1]})"
        elif step.operation == "multiply":
            expression = f"({args[0]} × {args[1]})"
        elif step.operation == "divide":
            expression = f"({args[0]} ÷ {args[1]})"
        else:
            expression = f"round({args[0]}, {step.scale})"
        expressions[step.step_id] = expression
    return expressions.get(plan.result_step_id, plan.result_step_id)


def _reason_for(fact: Fact, plan: CalculationPlan | None) -> str:
    if plan is None:
        return "No calculation plan was available or approved; this source was not used."
    if fact.fact_id in plan.unprocessed_fact_ids:
        return "The planner did not review this candidate; it was not used."
    fact_reasons = {item.fact_id: item.reason for item in plan.excluded if item.fact_id}
    group_reasons = {item.source_group_id: item.reason for item in plan.excluded if item.source_group_id}
    if plan and fact.fact_id in {item.fact_id for item in plan.included}:
        return "Selected by the plan but not used because validation or evidence checks require review."
    return fact_reasons.get(fact.fact_id) or group_reasons.get(fact.document_id) or "No reason was supplied by the plan."


def _link_review_diagnostics(target: TargetIndicator, selected: list[Fact], linking: dict[str, Any], facts_by_id: dict[str, Fact], human_confirmed_link_ids: set[str], human_confirmed_fact_ids: set[str]) -> list[Diagnostic]:
    selected_ids = {fact.fact_id for fact in selected}
    selected_rows = {(fact.document_id, fact.row_id) for fact in selected if fact.row_id}
    diagnostics: list[Diagnostic] = []
    target_docs = {target.kfz_document_id} if target.kfz_document_id else set()
    if target.target_fact_id and target.target_fact_id in facts_by_id:
        target_docs.add(facts_by_id[target.target_fact_id].document_id)
    for fact in selected:
        if fact.document_type == "kfz_report":
            target_docs.add(fact.document_id)
    for link in linking.get("links", []):
        if link.get("link_id") in human_confirmed_link_ids:
            continue
        source_row = (link.get("source_document_id"), link.get("source_row_id"))
        target_row = (link.get("target_document_id"), link.get("target_row_id"))
        touches_selected = source_row in selected_rows or target_row in selected_rows
        touches_target = bool(target_docs.intersection({link.get("source_document_id"), link.get("target_document_id")}))
        if touches_selected and touches_target and (link.get("status") in {"review", "proposed", "rejected"} or link.get("verification_status") != "human_confirmed"):
            diagnostics.append(Diagnostic("link_requires_human_review", "$.linking_result.links", "A relationship used to associate a selected source with the KФЗ row is not human-confirmed", {"link_id": link.get("link_id"), "status": link.get("status"), "verification_status": link.get("verification_status")}))
    for review in linking.get("review_required", []):
        link_id = review.get("link_id")
        if link_id in human_confirmed_link_ids:
            continue
        link = next((item for item in linking.get("links", []) if item.get("link_id") == link_id), None)
        if not link:
            continue
        endpoints = {link.get("source_document_id"), link.get("target_document_id")}
        selected_docs = {fact.document_id for fact in selected}
        if endpoints.intersection(selected_docs) and (not target_docs or endpoints.intersection(target_docs)):
            diagnostics.append(Diagnostic("link_marked_review_required", "$.linking_result.review_required", review.get("reason", "Linking requests manual review"), {"link_id": link_id, "candidate_document_ids": review.get("candidate_document_ids", [])}))
    for item in linking.get("link_validation_diagnostics", []):
        endpoints = {item.get("source_document_id"), item.get("target_document_id")}
        selected_docs = {fact.document_id for fact in selected}
        if endpoints.intersection(selected_docs) and (not target_docs or endpoints.intersection(target_docs)):
            diagnostics.append(Diagnostic("link_validation_requires_review", "$.linking_result.link_validation_diagnostics", "Linking has a validation diagnostic for a selected relationship", {"diagnostic": item}))
    selected_docs = {fact.document_id for fact in selected}
    if target_docs:
        for item in linking.get("unlinked_documents", []):
            manually_accepted_doc = any(fact.document_id == item.get("document_id") and fact.fact_id in human_confirmed_fact_ids for fact in selected)
            if item.get("document_id") in selected_docs and not manually_accepted_doc:
                diagnostics.append(Diagnostic("unlinked_source_requires_review", "$.linking_result.unlinked_documents", "A selected source is unlinked from the document set containing the target", {"document_id": item.get("document_id"), "reason": item.get("reason")}))
    return diagnostics


def _has_human_confirmed_path(fact: Fact, target: TargetIndicator, linking: dict[str, Any]) -> bool:
    """Require a row-aware, reviewed Linking path before an LLM-selected source is applicable."""
    target_fact_id = target.target_fact_id
    links = [
        item for item in linking.get("links", [])
        if item.get("status") == "confirmed"
        and item.get("verification_status") == "human_confirmed"
        and not item.get("conflicts")
    ]
    frontier = [(fact.document_id, fact.row_id, False)]
    seen: set[tuple[str, str | None]] = set()
    while frontier:
        document_id, row_id, left_source = frontier.pop(0)
        state = (document_id, row_id)
        if state in seen:
            continue
        seen.add(state)
        if document_id == target.kfz_document_id and (target.kfz_row_id is None or row_id == target.kfz_row_id):
            return left_source
        for link in links:
            endpoints = (
                (link.get("source_document_id"), link.get("source_row_id"), link.get("target_document_id"), link.get("target_row_id")),
                (link.get("target_document_id"), link.get("target_row_id"), link.get("source_document_id"), link.get("source_row_id")),
            )
            for from_document, from_row, to_document, to_row in endpoints:
                if from_document != document_id:
                    continue
                if row_id is not None and from_row != row_id:
                    continue
                if fact.row_id is not None and document_id == fact.document_id and from_row != fact.row_id:
                    continue
                frontier.append((to_document, to_row, True))
    return False


def _calculate_target(
    request: ReconciliationRequest,
    target: TargetIndicator,
    facts: list[Fact],
    settings: Settings,
    snapshot_sha256: str,
    planner: LLMPlanner | None = None,
) -> dict[str, Any]:
    linking = request.linking_result
    facts_by_id = {fact.fact_id: fact for fact in facts}
    target_fact = _target_fact(target, facts_by_id)
    origin = _target_origin(target_fact)
    decisions = [decision for decision in request.prior_decisions if decision.target_id == target.target_id]
    decision_diagnostics: list[Diagnostic] = []
    if len(decisions) > 1:
        decision_diagnostics.append(Diagnostic("duplicate_human_decision", "$.prior_decisions", "At most one confirmed decision is allowed per target", {"target_id": target.target_id}))
    plan: CalculationPlan | None = None
    plan_source = "none"
    planner_diagnostic: Diagnostic | None = None
    active_decision = None
    if decisions:
        try:
            plan = CalculationPlan.model_validate(decisions[0].plan)
        except ValidationError as exc:
            plan = None
            decision_diagnostics.append(Diagnostic("invalid_confirmed_plan", f"$.prior_decisions[{decisions[0].decision_id}].plan", "Confirmed calculation plan does not match the Reconciliation Engine plan schema", {"errors": exc.errors(include_url=False)}))
        if plan is not None:
            decision_diagnostics.extend(_decision_binding_diagnostics(request, decisions[0], plan))
            known_fact_ids = {fact.fact_id for fact in facts}
            known_link_ids = {link.get("link_id") for link in linking.get("links", [])}
            unknown_facts = sorted(set(decisions[0].accepted_fact_ids) - known_fact_ids)
            unknown_links = sorted(set(decisions[0].accepted_link_ids) - known_link_ids)
            if unknown_facts or unknown_links:
                decision_diagnostics.append(Diagnostic("unknown_human_confirmation_reference", f"$.prior_decisions[{decisions[0].decision_id}]", "Human decision references a fact or link outside this input snapshot", {"unknown_fact_ids": unknown_facts, "unknown_link_ids": unknown_links}))
            if not decision_diagnostics:
                active_decision = decisions[0]
                plan_source = "human_confirmed_decision"
            else:
                plan = None
    elif settings.llm_enabled and (
        (request.context.data_classification in {"open", "anonymized"} and request.context.external_llm_allowed)
        or (request.context.data_classification == "confidential" and settings.llm_trusted_local)
    ):
        try:
            groups = {fact.document_id: _group_id(fact.document_id) for fact in facts}
            plan = (planner or LLMPlanner(settings)).plan(
                target, facts, groups, linking,
                sensitive_data=request.context.data_classification == "confidential",
            )
            plan_source = "llm"
        except (PlannerUnavailable, httpx.HTTPError, ValueError) as exc:
            if request.context.data_classification == "confidential" and not is_trusted_internal_endpoint(settings.llm_base_url, settings.llm_trusted_hosts):
                planner_diagnostic = Diagnostic("trusted_llm_endpoint_not_local", "$.settings.llm_base_url", "Confidential data was not sent because the configured endpoint is not loopback or operator-allowlisted internal infrastructure")
            else:
                planner_diagnostic = Diagnostic("planner_unavailable", "$.planner", str(exc))
    elif settings.llm_enabled and request.context.data_classification == "confidential" and settings.llm_trusted_local:
        planner_diagnostic = Diagnostic("trusted_llm_endpoint_not_local", "$.settings.llm_base_url", "Confidential data was not sent because the configured endpoint is not loopback or operator-allowlisted internal infrastructure")
    elif settings.llm_enabled:
        planner_diagnostic = Diagnostic("external_llm_not_authorized", "$.context", "LLM call skipped: external models require open/anonymized data and explicit permission")
    else:
        planner_diagnostic = Diagnostic("planner_not_configured", "$.planner", "No approved plan exists and the OpenAI-compatible planner is disabled")

    relevant = [fact for fact in facts if numeric_value(fact) is not None or fact.status in {"review", "missing"}]
    selected = [facts_by_id[item.fact_id] for item in plan.included if item.fact_id in facts_by_id] if plan else []
    diagnostics = list(decision_diagnostics)
    if planner_diagnostic:
        diagnostics.append(planner_diagnostic)
    if (
        target.period_basis != "none"
        and target_fact.period_start is not None
        and target_fact.period_end is not None
        and request.context.period_start is not None
        and request.context.period_end is not None
        and (target_fact.period_start != request.context.period_start or target_fact.period_end != request.context.period_end)
    ):
        diagnostics.append(Diagnostic(
            "target_period_mismatch", "$.context.period_start", "The requested calculation period does not exactly match the KФЗ target indicator period",
            {"target_id": target.target_id, "target_period_start": target_fact.period_start.isoformat(), "target_period_end": target_fact.period_end.isoformat(), "requested_period_start": request.context.period_start.isoformat(), "requested_period_end": request.context.period_end.isoformat()},
        ))
    trace: list[dict[str, Any]] = []
    exact_value: Decimal | None = None
    result_value: str | None = None
    if plan:
        accepted_facts = set(active_decision.accepted_fact_ids) if active_decision else set()
        accepted_links = set(active_decision.accepted_link_ids) if active_decision else set()
        diagnostics.extend(validate_plan(
            plan, target, facts, linking, request.context.period_start, request.context.period_end,
            accepted_facts, active_decision.independence_confirmed if active_decision else False,
        ))
        diagnostics.extend(_link_review_diagnostics(target, selected, linking, facts_by_id, accepted_links, accepted_facts))
        if plan_source == "llm":
            for fact in selected:
                if not _has_human_confirmed_path(fact, target, linking):
                    diagnostics.append(Diagnostic("source_applicability_unverified", fact.source_path, "The selected source has no row-aware human-confirmed Linking path to this target indicator", {"fact_id": fact.fact_id, "target_id": target.target_id}))
        selected_types = {fact.document_type for fact in selected}
        for required_type in target.required_document_types:
            if required_type not in selected_types:
                diagnostics.append(Diagnostic("required_document_missing", "$.context.targets", "A target-required document type is not represented among the selected operation evidence", {"target_id": target.target_id, "document_type": required_type, "selected_document_types": sorted(selected_types)}))
        if plan.requires_manual_review:
            diagnostics.append(Diagnostic("plan_requires_manual_review", "$.plan.requires_manual_review", "The selected plan explicitly requests manual review"))
        if plan.information_gaps:
            diagnostics.append(Diagnostic("information_gap", "$.plan.information_gaps", "The plan identified missing or ambiguous evidence", {"gaps": plan.information_gaps}))
        if plan.unprocessed_fact_ids:
            diagnostics.append(Diagnostic("unprocessed_candidates", "$.plan.unprocessed_fact_ids", "Some candidates were not reviewed and cannot be treated as excluded", {"fact_ids": plan.unprocessed_fact_ids}))
        if plan.assumptions:
            diagnostics.append(Diagnostic("assumptions_require_review", "$.plan.assumptions", "The plan depends on assumptions that have not been verified", {"assumptions": plan.assumptions}))
        blocking_codes = {item.code for item in diagnostics if item.code != "information_gap"}
        if not blocking_codes:
            try:
                exact_value, trace = execute_plan(plan, facts)
                result_value = decimal_string(exact_value, target.rounding_scale)
            except ZeroDivisionError as exc:
                failed_step = next((step for step in plan.steps if step.step_id in str(exc)), None)
                step_index = plan.steps.index(failed_step) if failed_step else -1
                path = f"$.plan.steps[{step_index}]" if step_index >= 0 else "$.plan.steps"
                diagnostics.append(Diagnostic("division_by_zero", path, "A divide step has a zero denominator", {"error": str(exc)}))
            except Exception as exc:
                diagnostics.append(Diagnostic("calculation_execution_error", "$.plan.steps", "The calculation could not be executed safely", {"error_type": type(exc).__name__, "message": str(exc)}))

    if result_value is not None:
        status = "manual_review" if diagnostics or (plan and (plan.requires_manual_review or plan.information_gaps or plan.assumptions)) else "calculated"
    else:
        status = "insufficient_data" if any(item.code in {"required_document_missing", "planner_not_configured", "planner_unavailable", "external_llm_not_authorized"} for item in diagnostics) else "manual_review"
    if status != "calculated":
        # Never publish an unresolved or partially supported number as the expected value.
        result_value = None
        exact_value = None
        trace = []

    used_ids = {fact.fact_id for fact in selected} if status == "calculated" else set()
    included_records = []
    inclusion_reasons = {item.fact_id: item.reason for item in plan.included} if plan else {}
    for fact in selected:
        confirmation = None
        if active_decision and fact.fact_id in active_decision.accepted_fact_ids:
            confirmation = {"decision_id": active_decision.decision_id, "reviewer_id": active_decision.reviewer_id, "confirmed_at": active_decision.confirmed_at.isoformat(), "snapshot_sha256": active_decision.snapshot_sha256, "fact_sha256": active_decision.accepted_fact_hashes.get(fact.fact_id)}
        source_record = _source_record(fact, linking)
        if active_decision:
            for related_link in source_record["related_links"]:
                if related_link["link_id"] in active_decision.accepted_link_ids:
                    related_link["human_confirmation"] = {"decision_id": active_decision.decision_id, "reviewer_id": active_decision.reviewer_id, "confirmed_at": active_decision.confirmed_at.isoformat(), "link_sha256": active_decision.accepted_link_hashes.get(related_link["link_id"])}
        included_records.append({**source_record, "inclusion_reason": inclusion_reasons.get(fact.fact_id), "used_in_result": fact.fact_id in used_ids, "human_confirmation": confirmation})
    excluded = []
    for fact in relevant:
        if fact.fact_id not in used_ids:
            excluded.append({**_source_record(fact, linking), "exclusion_reason": _reason_for(fact, plan)})
    source_documents = {doc["document_id"]: doc for doc in linking.get("input_documents", [])}
    snapshot_groups: list[dict[str, Any]] = []
    for document_id, doc in sorted(source_documents.items()):
        extraction = next((item for item in request.extraction_results if item.get("document_id") == document_id), {})
        snapshot_groups.append({
            "document_id": document_id,
            "extraction_id": doc.get("extraction_id"),
            "document_type": doc.get("document_type"),
            "extraction_version": doc.get("version"),
            "schema_version": doc.get("schema_version"),
            "input_version": doc.get("input_version"),
            "linking_input_hash": doc.get("input_hash"),
            "reconciliation_input_hash": _hash(extraction) if extraction else None,
        })
    completeness = "sufficient" if status == "calculated" else ("partial" if selected or plan else "unknown")
    completeness_status = {"sufficient": "complete", "partial": "partial", "unknown": "unknown"}[completeness]
    uncertainty_status = "none" if status == "calculated" else ("unknown" if status == "insufficient_data" else "present")
    errors = [{**item.as_dict(), "severity": "error"} for item in diagnostics]
    formula = _format_formula(plan) if plan else None
    used_records = [item for item in included_records if item["used_in_result"]]
    excluded_fact_ids = [item["fact_id"] for item in excluded]
    period_start = request.context.period_start or target_fact.period_start
    period_end = request.context.period_end or target_fact.period_end
    period_basis = "explicit" if request.context.period_start or request.context.period_end else target.period_basis
    return {
        "target": {
            "target_id": target.target_id,
            "label": target.label,
            "description": target.description,
            "unit": target.unit,
            "currency": target.currency,
            "amount_basis": target.amount_basis,
            "economic_measure": target.economic_measure,
            "period_basis": target.period_basis,
            "kfz_origin": origin,
        },
        "status": status,
        "data_sufficiency": completeness,
        "completeness_status": completeness_status,
        "uncertainty_status": uncertainty_status,
        "expected_value": result_value,
        "exact_value_before_rounding": decimal_string(exact_value) if exact_value is not None else None,
        "currency": (plan.currency if plan and plan.currency else target.currency),
        "unit": (plan.unit if plan and plan.unit else target.unit),
        "period": {"start": period_start.isoformat() if period_start else None, "end": period_end.isoformat() if period_end else None, "basis": period_basis},
        "amount_basis": (plan.amount_basis if plan else target.amount_basis),
        "rounding": {"mode": request.context.rounding_mode, "scale": target.rounding_scale, "applied": status == "calculated"},
        "sign_convention": "preserve_source_sign; subtraction_is_explicit",
        "plan_source": plan_source,
        "method_description": plan.method_description if plan else None,
        "formula": formula,
        "formula_status": "executed" if status == "calculated" else ("proposed" if formula else "not_available"),
        "calculation_plan": plan.as_dict() if plan else None,
        "human_confirmations": [
            {"decision_id": decision.decision_id, "reviewer_id": decision.reviewer_id, "confirmed_at": decision.confirmed_at.isoformat(), "accepted_fact_ids": decision.accepted_fact_ids, "accepted_link_ids": decision.accepted_link_ids, "snapshot_sha256": decision.snapshot_sha256, "linking_sha256": decision.linking_sha256, "confirmed_fact_hashes": decision.confirmed_fact_hashes, "accepted_fact_hashes": decision.accepted_fact_hashes, "accepted_link_hashes": decision.accepted_link_hashes, "independence_confirmed": decision.independence_confirmed, "decision_sha256": decision.decision_sha256, "binding_status": "active" if decision is active_decision else "stale_or_invalid"}
            for decision in decisions
        ],
        "steps": trace,
        "included_sources": included_records,
        "used_sources": used_records,
        "excluded_sources": excluded,
        "provenance": {
            "input_snapshot_sha256": snapshot_sha256,
            "target_indicator": origin,
            "used_fact_ids": [item["fact_id"] for item in used_records],
            "excluded_fact_ids": excluded_fact_ids,
        },
        "errors": errors,
        "information_gaps": plan.information_gaps if plan else ["Calculation plan was not available; manual review is required."],
        "assumptions": plan.assumptions if plan else [],
        "diagnostics": errors,
        "manual_review_required": status != "calculated",
        "comparison_performed": False,
        "reliability_conclusion": None,
        "input_documents": snapshot_groups,
        "linking_context": {
            "review_required": linking.get("review_required", []),
            "unlinked_documents": linking.get("unlinked_documents", []),
            "link_validation_diagnostics": linking.get("link_validation_diagnostics", []),
            "warnings": linking.get("warnings", []),
        },
    }


def _failed_target_result(
    request: ReconciliationRequest,
    target: TargetIndicator,
    snapshot_sha256: str,
    diagnostics: list[Diagnostic],
) -> dict[str, Any]:
    errors = [{**item.as_dict(), "severity": "error"} for item in diagnostics]
    facts = extract_facts(request.extraction_results)
    target_fact = next((fact for fact in facts if fact.fact_id == target.target_fact_id), None)
    if target_fact is None:
        matches = [fact for fact in facts if fact.document_id == target.kfz_document_id and fact.source_path == target.kfz_source_path and (target.kfz_row_id is None or fact.row_id == target.kfz_row_id)]
        target_fact = matches[0] if len(matches) == 1 else None
    extraction = next((item for item in request.extraction_results if item.get("document_id") == target.kfz_document_id), {})
    origin = {
        "document_id": target.kfz_document_id,
        "extraction_id": extraction.get("extraction_id"),
        "fact_id": target_fact.fact_id if target_fact else target.target_fact_id,
        "row_id": target.kfz_row_id,
        "source_path": target.kfz_source_path,
        "source_ref": (target_fact.provenance or {}).get("source_ref") if target_fact else None,
    }
    linking_docs = {item.get("document_id"): item for item in request.linking_result.get("input_documents", [])}
    input_documents = []
    for document_id, doc in sorted(linking_docs.items()):
        source = next((item for item in request.extraction_results if item.get("document_id") == document_id), {})
        input_documents.append({"document_id": document_id, "extraction_id": doc.get("extraction_id"), "document_type": doc.get("document_type"), "extraction_version": doc.get("version"), "schema_version": doc.get("schema_version"), "input_version": doc.get("input_version"), "linking_input_hash": doc.get("input_hash"), "reconciliation_input_hash": _hash(source) if source else None})
    return {
        "target": {
            "target_id": target.target_id,
            "label": target.label,
            "description": target.description,
            "unit": target.unit,
            "currency": target.currency,
            "amount_basis": target.amount_basis,
            "economic_measure": target.economic_measure,
            "period_basis": target.period_basis,
            "kfz_origin": origin,
        },
        "status": "manual_review",
        "data_sufficiency": "unknown",
        "completeness_status": "unknown",
        "uncertainty_status": "present",
        "expected_value": None,
        "exact_value_before_rounding": None,
        "currency": target.currency,
        "unit": target.unit,
        "period": {"start": request.context.period_start.isoformat() if request.context.period_start else None, "end": request.context.period_end.isoformat() if request.context.period_end else None, "basis": "explicit" if request.context.period_start or request.context.period_end else target.period_basis},
        "amount_basis": target.amount_basis,
        "rounding": {"mode": request.context.rounding_mode, "scale": target.rounding_scale, "applied": False},
        "sign_convention": "preserve_source_sign; subtraction_is_explicit",
        "plan_source": "none",
        "method_description": None,
        "formula": None,
        "formula_status": "not_available",
        "calculation_plan": None,
        "human_confirmations": [],
        "steps": [],
        "included_sources": [],
        "used_sources": [],
        "excluded_sources": [],
        "provenance": {"input_snapshot_sha256": snapshot_sha256, "target_indicator": origin, "used_fact_ids": [], "excluded_fact_ids": []},
        "errors": errors,
        "information_gaps": ["The target could not be calculated; manual review is required."],
        "assumptions": [],
        "diagnostics": errors,
        "manual_review_required": True,
        "comparison_performed": False,
        "reliability_conclusion": None,
        "input_documents": input_documents,
        "linking_context": {"review_required": request.linking_result.get("review_required", []), "unlinked_documents": request.linking_result.get("unlinked_documents", []), "link_validation_diagnostics": request.linking_result.get("link_validation_diagnostics", []), "warnings": request.linking_result.get("warnings", [])},
    }


def reconcile(request: ReconciliationRequest, settings: Settings, planner: LLMPlanner | None = None) -> dict[str, Any]:
    validate_upstream_inputs(request.extraction_results, request.linking_result)
    facts = extract_facts(request.extraction_results)
    identity = input_snapshot_identity(request)
    snapshot_hash = identity["snapshot_sha256"]
    reconciliation_id = _hash({"snapshot_sha256": snapshot_hash, "decisions": [decision.model_dump(mode="json") for decision in request.prior_decisions]})[:32]
    calculations = []
    for target in request.context.targets:
        try:
            calculations.append(_calculate_target(request, target, facts, settings, snapshot_hash, planner))
        except InputContractError as exc:
            calculations.append(_failed_target_result(request, target, snapshot_hash, exc.diagnostics))
        except Exception as exc:
            calculations.append(_failed_target_result(request, target, snapshot_hash, [Diagnostic("target_calculation_failed", f"$.context.targets[target_id={target.target_id}]", "This indicator failed safely; other indicators were still processed", {"error_type": type(exc).__name__, "message": str(exc)})]))
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "reconciliation_id": reconciliation_id,
        "contract_version": "1.0.0",
        "engine_version": "0.1.0",
        "created_at": created_at,
        "input_snapshot": {
            "snapshot_sha256": snapshot_hash,
            "extraction_results": identity["extraction_hashes"],
            "linking_run_id": request.linking_result.get("linking_run_id"),
            "linking_contract_version": request.linking_result.get("contract_version"),
            "linking_sha256": identity["linking_sha256"],
            "fact_count": len(facts),
        },
        "calculations": calculations,
        "diagnostics": [diagnostic for calculation in calculations for diagnostic in calculation["errors"]],
        "scope": {"comparison_performed": False, "reliability_conclusion": None},
    }


