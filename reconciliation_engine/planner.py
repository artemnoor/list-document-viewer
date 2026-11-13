import hashlib
import json
import re
from pathlib import Path
import time
from typing import Any

import httpx

from .config import Settings
from .facts import Fact, numeric_value
from .models import TargetIndicator
from .plans import CalculationPlan, PlanExclusion, PlanStep
from .security import is_trusted_internal_endpoint

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "calculation-plan.v1.0.2.txt"


class PlannerUnavailable(Exception):
    pass


class IncompatibleChunkPlans(ValueError):
    """Chunk plans cannot be combined without mixing measurement dimensions."""


def _dimension_mismatch(fact: Fact, target: TargetIndicator) -> list[str]:
    mismatches = []
    if target.currency and fact.currency and fact.currency != target.currency:
        mismatches.append(f"currency {fact.currency} does not match target currency {target.currency}")
    if fact.unit is not None and fact.unit != target.unit and (target.unit is not None or target.currency is not None):
        target_unit = target.unit if target.unit is not None else "unspecified"
        mismatches.append(f"unit {fact.unit} does not match target unit {target_unit}")
    return mismatches


def _json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    return json.loads(text)


def _validated_plan(content: str, request_payload: dict[str, Any]) -> CalculationPlan:
    decoded = _json_content(content)
    if not isinstance(decoded, dict):
        raise ValueError("LLM plan response must be a JSON object")
    plan_fields = set(CalculationPlan.model_fields)
    # Models sometimes echo request-only context into their answer. Remove only
    # exact echoes of fields outside the response contract; do not forgive
    # invented or altered fields that could change calculation semantics.
    for key in set(request_payload) - plan_fields:
        if key in decoded and decoded[key] == request_payload[key]:
            del decoded[key]
    return CalculationPlan.model_validate(decoded)


class LLMPlanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.call_records: list[dict[str, Any]] = []

    @staticmethod
    def _row_alias(document_id: str, row_id: str | None) -> str | None:
        if not row_id:
            return None
        raw = f"{document_id}|{row_id}".encode("utf-8")
        return "row_" + hashlib.sha256(raw).hexdigest()[:12]

    @staticmethod
    def _aliases(
        facts: list[Fact], source_groups: dict[str, str], candidates: list[Fact]
    ) -> tuple[dict[str, str], dict[str, str]]:
        document_ids = {fact.document_id for fact in facts}
        for key, value in source_groups.items():
            document_ids.add(key if key in document_ids else value)
        document_order = sorted(document_ids, key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())
        group_by_document = {document_id: f"source_{index:03d}" for index, document_id in enumerate(document_order, start=1)}
        fact_order = sorted(
            candidates,
            key=lambda fact: (group_by_document.get(fact.document_id, "source_unknown"), fact.source_path, fact.key, fact.fact_id),
        )
        fact_aliases = {fact.fact_id: f"candidate_{index:05d}" for index, fact in enumerate(fact_order, start=1)}
        return group_by_document, fact_aliases

    def build_payload(
        self,
        target: TargetIndicator,
        facts: list[Fact],
        source_groups: dict[str, str],
        linking: dict[str, Any],
        candidate_facts: list[Fact] | None = None,
        fact_aliases: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        candidates = candidate_facts if candidate_facts is not None else [
            fact for fact in facts
            if fact.document_type != "kfz_report"
            and fact.document_id != target.kfz_document_id
            and numeric_value(fact) is not None
        ]
        group_by_document, locally_assigned_fact_aliases = self._aliases(facts, source_groups, candidates)
        fact_aliases = fact_aliases or locally_assigned_fact_aliases
        row_descriptions = {
            (fact.document_id, fact.row_id): str(fact.normalized_value)
            for fact in facts
            if fact.row_id and fact.key == "description" and isinstance(fact.normalized_value, str)
        }
        candidate_documents = {fact.document_id for fact in candidates}
        target_documents = {target.kfz_document_id}
        relevant_documents = candidate_documents | target_documents
        compact_facts = []
        for fact in candidates:
            compact_facts.append({
                "fact_id": fact_aliases[fact.fact_id],
                "source_group_id": group_by_document.get(fact.document_id, "source_unknown"),
                "document_type": fact.document_type,
                "role": fact.role,
                "key": fact.key,
                "label": fact.label,
                "value_available": numeric_value(fact) is not None,
                "currency": fact.currency,
                "unit": fact.unit,
                "amount_basis": fact.amount_basis,
                "economic_measure": fact.economic_measure,
                "status": fact.status,
                "period_start": fact.period_start.isoformat() if fact.period_start else None,
                "period_end": fact.period_end.isoformat() if fact.period_end else None,
                "source_row_ref": self._row_alias(fact.document_id, fact.row_id),
                "operation_description": row_descriptions.get((fact.document_id, fact.row_id)),
            })
        date_facts = [
            {
                "source_group_id": group_by_document[fact.document_id],
                "key": fact.key,
                "label": fact.label,
                "date": str(fact.value),
            }
            for fact in facts
            if fact.document_id in relevant_documents
            and fact.document_id in group_by_document
            and fact.role in {"field", "indicator"}
            and fact.status == "extracted"
            and isinstance(fact.value, str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact.value)
        ]
        links = sorted(linking.get("links", []), key=lambda item: str(item.get("link_id", "")))
        link_aliases = {link.get("link_id"): f"link_{index + 1:05d}" for index, link in enumerate(links)}
        safe_links = []
        for link in links:
            source_document = link.get("source_document_id")
            target_document = link.get("target_document_id")
            if not ({source_document, target_document} & relevant_documents):
                continue
            evidence = []
            for item in link.get("evidence", []):
                source = item.get("source") or {}
                target_evidence = item.get("target") or {}
                source_doc = source.get("document_id") or link.get("source_document_id")
                target_doc = target_evidence.get("document_id") or link.get("target_document_id")
                evidence.append({
                    "source_group_id": group_by_document.get(source_doc, "source_unknown"),
                    "target_group_id": group_by_document.get(target_doc, "source_unknown"),
                    "source_row_ref": self._row_alias(source_doc or "", link.get("source_row_id")),
                    "target_row_ref": self._row_alias(target_doc or "", link.get("target_row_id")),
                    "signal": item.get("signal"),
                })
            safe_links.append({
                "link_ref": link_aliases.get(link.get("link_id")),
                "relationship_type": link.get("relationship_type"),
                "source_group_id": group_by_document.get(source_document, "source_unknown"),
                "target_group_id": group_by_document.get(target_document, "source_unknown"),
                "source_row_ref": self._row_alias(link.get("source_document_id", ""), link.get("source_row_id")),
                "target_row_ref": self._row_alias(link.get("target_document_id", ""), link.get("target_row_id")),
                "status": link.get("status"),
                "verification_status": link.get("verification_status"),
                "confidence": link.get("confidence"),
                "evidence": evidence,
            })
        safe_review = [
            {
                "link_ref": link_aliases.get(item.get("link_id")),
                "candidate_source_groups": [group_by_document.get(doc_id, "source_unknown") for doc_id in item.get("candidate_document_ids", [])],
            }
            for item in linking.get("review_required", [])
            if any(doc_id in relevant_documents for doc_id in item.get("candidate_document_ids", []))
        ]
        safe_diagnostics = [
            {
                "relationship_type": item.get("relationship_type"),
                "source_group_id": group_by_document.get(item.get("source_document_id"), "source_unknown"),
                "target_group_id": group_by_document.get(item.get("target_document_id"), "source_unknown"),
                "reason_codes": item.get("reason_codes", []),
                "candidate_status": item.get("candidate_status"),
            }
            for item in linking.get("link_validation_diagnostics", [])
            if {item.get("source_document_id"), item.get("target_document_id")} & relevant_documents
        ]
        safe_unlinked = [
            {"source_group_id": group_by_document.get(item.get("document_id"), "source_unknown")}
            for item in linking.get("unlinked_documents", [])
            if item.get("document_id") in relevant_documents
        ]
        target_payload = target.model_dump(mode="json")
        for private_locator in ("target_fact_id", "kfz_document_id", "kfz_row_id"):
            target_payload.pop(private_locator, None)
        target_payload["target_id"] = "target_001"
        return {
            "target": target_payload,
            "candidates": compact_facts,
            "source_groups": sorted({item["source_group_id"] for item in compact_facts}),
            "candidate_count": len(compact_facts),
            "document_date_facts": date_facts,
            "linking_graph": {
                "relationships": safe_links,
                "review_required": safe_review,
                "unlinked_source_groups": safe_unlinked,
                "validation_diagnostics": safe_diagnostics,
            },
            "output_contract": CalculationPlan.model_json_schema(),
        }

    def _request_plan(self, payload: dict[str, Any], sensitive_data: bool) -> CalculationPlan:
        if sensitive_data:
            if not self.settings.llm_trusted_local:
                raise PlannerUnavailable("Confidential inputs require LLM_TRUSTED_LOCAL=true")
            if not is_trusted_internal_endpoint(self.settings.llm_base_url, self.settings.llm_trusted_hosts):
                raise PlannerUnavailable("Confidential inputs cannot be sent to an endpoint outside localhost or the configured internal host allowlist")
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        prompt_sha256 = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        payload_sha256 = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {}
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds, follow_redirects=False) as client:
                response = client.post(
                    url,
                    headers=headers,
                    json={
                        "model": self.settings.llm_model,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                    },
                )
                response.raise_for_status()
                result = response.json()
        except Exception as exc:
            self.call_records.append({
                "model_requested": self.settings.llm_model,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "error_type": type(exc).__name__,
                "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                "prompt_sha256": prompt_sha256,
                "payload_sha256": payload_sha256,
                "assistant_content": None,
                "usage": None,
            })
            raise
        try:
            choice = result["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            self.call_records.append({
                "model_requested": self.settings.llm_model,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "prompt_sha256": prompt_sha256,
                "payload_sha256": payload_sha256,
                "usage": result.get("usage") if isinstance(result, dict) else None,
                "assistant_content": None,
                "error_type": type(exc).__name__,
                "http_status": response.status_code,
            })
            raise PlannerUnavailable(f"LLM returned an invalid response envelope: {exc}") from exc
        self.call_records.append({
            "response_id": result.get("id"),
            "model_requested": self.settings.llm_model,
            "model_returned": result.get("model"),
            "finish_reason": choice.get("finish_reason"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "prompt_sha256": prompt_sha256,
            "payload_sha256": payload_sha256,
            "usage": result.get("usage"),
            "provider_cost": (
                (result.get("usage") or {}).get("cost_rub", (result.get("usage") or {}).get("cost"))
                if isinstance(result.get("usage"), dict) else None
            ),
            "provider_cost_currency": (
                "RUB" if isinstance(result.get("usage"), dict) and "cost_rub" in result["usage"]
                else (result.get("usage") or {}).get("cost_currency") if isinstance(result.get("usage"), dict)
                else None
            ),
            "assistant_content": content,
            "error_type": None,
            "http_status": response.status_code,
        })
        try:
            return _validated_plan(content, payload)
        except (TypeError, ValueError) as exc:
            self.call_records[-1]["error_type"] = type(exc).__name__
            raise PlannerUnavailable(f"LLM returned an invalid plan: {exc}") from exc

    def plan(
        self,
        target: TargetIndicator,
        facts: list[Fact],
        source_groups: dict[str, str],
        linking: dict[str, Any],
        *,
        sensitive_data: bool = False,
    ) -> CalculationPlan:
        if not self.settings.llm_enabled or (not self.settings.llm_api_key and not self.settings.llm_trusted_local):
            raise PlannerUnavailable("LLM planner is not configured")
        candidates = [
            fact for fact in facts
            if fact.document_type != "kfz_report"
            and fact.document_id != target.kfz_document_id
            and numeric_value(fact) is not None
        ]
        dimension_exclusions = [
            PlanExclusion(
                fact_id=fact.fact_id,
                reason="; ".join(_dimension_mismatch(fact, target)) + "; no unit or currency conversion was supplied.",
            )
            for fact in candidates
            if _dimension_mismatch(fact, target)
        ]
        dimension_excluded_ids = {item.fact_id for item in dimension_exclusions}
        compatible_candidates = [fact for fact in candidates if fact.fact_id not in dimension_excluded_ids]
        if not compatible_candidates:
            return CalculationPlan(
                target_id=target.target_id,
                method_description="No candidate has dimensions compatible with the target indicator.",
                excluded=dimension_exclusions,
                rounding_scale=target.rounding_scale,
                information_gaps=["No dimension-compatible source candidate remains after deterministic currency and unit checks."],
                requires_manual_review=True,
            )
        group_by_document, fact_aliases = self._aliases(facts, source_groups, compatible_candidates)
        alias_to_fact = {alias: fact_id for fact_id, alias in fact_aliases.items()}
        alias_to_document = {alias: document_id for document_id, alias in group_by_document.items()}
        candidate_limit = max(1, self.settings.llm_max_candidates)

        terms = set(re.findall(r"[\w-]+", f"{target.label} {target.description}".casefold()))
        row_descriptions = {
            (fact.document_id, fact.row_id): str(fact.normalized_value)
            for fact in facts
            if fact.row_id and fact.key == "description" and isinstance(fact.normalized_value, str)
        }

        def relevance(fact: Fact) -> tuple[int, str, str]:
            text = " ".join((fact.key, fact.label, row_descriptions.get((fact.document_id, fact.row_id), ""))).casefold()
            score = sum(1 for term in terms if term and term in text)
            return (-score, group_by_document.get(fact.document_id, "source_unknown"), fact.source_path)

        # Fix batch boundaries in Extraction order so relevance ranking cannot
        # pull a later source into an earlier batch. Rank only within each batch.
        chunks = [
            sorted(compatible_candidates[index:index + candidate_limit], key=relevance)
            for index in range(0, len(compatible_candidates), candidate_limit)
        ]
        plans: list[tuple[int, CalculationPlan]] = []
        failed_fact_ids: list[str] = []
        failed_batch_gaps: list[str] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            payload = self.build_payload(target, facts, source_groups, linking, chunk, fact_aliases)
            payload["candidate_batch"] = {
                "index": chunk_index,
                "total_batches": len(chunks),
                "batch_candidate_count": len(chunk),
                "total_candidate_count": len(candidates),
                "all_batches_will_be_reviewed": True,
            }
            try:
                plan = self._request_plan(payload, sensitive_data)
            except (PlannerUnavailable, httpx.HTTPError, ValueError) as exc:
                if len(chunks) == 1:
                    raise
                failed_fact_ids.extend(fact.fact_id for fact in chunk)
                failed_batch_gaps.append(
                    f"Candidate batch {chunk_index} of {len(chunks)} could not be reviewed; its candidates remain unprocessed ({type(exc).__name__})."
                )
                continue
            decoded = plan.model_dump(mode="python")
            decoded["target_id"] = target.target_id
            for inclusion in decoded.get("included", []):
                inclusion["fact_id"] = alias_to_fact.get(inclusion.get("fact_id"), inclusion.get("fact_id"))
            for step in decoded.get("steps", []):
                step["inputs"] = [alias_to_fact.get(value, value) for value in step.get("inputs", [])]
            for exclusion in decoded.get("excluded", []):
                exclusion["fact_id"] = alias_to_fact.get(exclusion.get("fact_id"), exclusion.get("fact_id"))
                alias = exclusion.get("source_group_id")
                if alias in alias_to_document:
                    exclusion["source_group_id"] = alias_to_document[alias]
            decoded["unprocessed_fact_ids"] = [alias_to_fact.get(value, value) for value in decoded.get("unprocessed_fact_ids", [])]
            plans.append((chunk_index, CalculationPlan.model_validate(decoded)))

        reviewed_candidate_count = len(candidates) - len(failed_fact_ids)
        if plans:
            merged = self._merge_chunk_plans(target, plans, reviewed_candidate_count, compatible_candidates)
        else:
            merged = CalculationPlan(
                target_id=target.target_id,
                method_description="No candidate batch produced a usable plan.",
                rounding_scale=target.rounding_scale,
                currency=target.currency,
                unit=target.unit,
                amount_basis=target.amount_basis,
                requires_manual_review=True,
            )
        merged.unprocessed_fact_ids = list(dict.fromkeys([*merged.unprocessed_fact_ids, *failed_fact_ids]))
        merged.information_gaps = list(dict.fromkeys([*merged.information_gaps, *failed_batch_gaps]))
        merged.requires_manual_review = merged.requires_manual_review or bool(failed_fact_ids)
        merged.excluded.extend(dimension_exclusions)
        if dimension_exclusions:
            merged.method_description += f" Deterministically excluded {len(dimension_exclusions)} candidates with incompatible currency or unit metadata."
        return merged

    @staticmethod
    def _merge_chunk_plans(
        target: TargetIndicator,
        plans: list[tuple[int, CalculationPlan]],
        candidate_count: int,
        candidates: list[Fact] | None = None,
    ) -> CalculationPlan:
        if len(plans) == 1:
            return plans[0][1]
        included = []
        excluded = []
        unprocessed: list[str] = []
        steps: list[PlanStep] = []
        roots: list[str] = []
        assumptions: list[str] = []
        gaps: list[str] = []
        for chunk_index, plan in plans:
            step_ids = {step.step_id: f"chunk_{chunk_index}_{step.step_id}" for step in plan.steps}
            included.extend(plan.included)
            excluded.extend(plan.excluded)
            unprocessed.extend(plan.unprocessed_fact_ids)
            assumptions.extend(plan.assumptions)
            gaps.extend(plan.information_gaps)
            for step in plan.steps:
                steps.append(step.model_copy(update={"step_id": step_ids[step.step_id], "inputs": [step_ids.get(item, item) for item in step.inputs]}))
            if plan.result_step_id and plan.result_step_id in step_ids:
                roots.append(step_ids[plan.result_step_id])
        result_step_id: str | None = None
        signatures = {(plan.currency, plan.unit, plan.amount_basis) for _, plan in plans}
        if len(signatures) > 1:
            raise IncompatibleChunkPlans("Cannot merge chunk plans with incompatible currency, unit, or amount basis")
        if candidates is not None:
            facts_by_id = {fact.fact_id: fact for fact in candidates}
            selected_ids = {item.fact_id for _, plan in plans for item in plan.included}
            fact_signatures = {
                (fact.currency, fact.unit, fact.amount_basis)
                for fact_id in selected_ids
                if (fact := facts_by_id.get(fact_id)) is not None
            }
            if len(fact_signatures) > 1:
                raise IncompatibleChunkPlans("Cannot merge chunk plans that select facts with incompatible currency, unit, or amount basis")
        if len(roots) == 1:
            result_step_id = roots[0]
        elif roots:
            result_step_id = "combined_result"
            steps.append(PlanStep(step_id=result_step_id, operation="sum", inputs=roots))
        first = plans[0][1] if plans else None
        return CalculationPlan(
            target_id=target.target_id,
            method_description=(first.method_description if first else "No calculation plan was produced.") + f" Reviewed {candidate_count} candidates across {len(plans)} batches.",
            included=included,
            excluded=excluded,
            unprocessed_fact_ids=list(dict.fromkeys(unprocessed)),
            steps=steps,
            result_step_id=result_step_id,
            currency=first.currency if first else None,
            unit=first.unit if first else None,
            amount_basis=first.amount_basis if first else "unspecified",
            rounding_scale=target.rounding_scale,
            assumptions=list(dict.fromkeys(assumptions)),
            information_gaps=list(dict.fromkeys(gaps)),
            requires_manual_review=any(plan.requires_manual_review for _, plan in plans) or not roots or bool(unprocessed),
        )

