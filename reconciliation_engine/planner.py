import json
import hashlib
import re
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .facts import Fact, numeric_value
from .models import TargetIndicator
from .plans import CalculationPlan

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "calculation-plan.v1.0.0.txt"


class PlannerUnavailable(Exception):
    pass


def _json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    return json.loads(text)


class LLMPlanner:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _row_alias(document_id: str, row_id: str | None) -> str | None:
        if not row_id:
            return None
        raw = f"{document_id}|{row_id}".encode("utf-8")
        return "row_" + hashlib.sha256(raw).hexdigest()[:12]

    def build_payload(
        self,
        target: TargetIndicator,
        facts: list[Fact],
        source_groups: dict[str, str],
        linking: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = [fact for fact in facts if numeric_value(fact) is not None or fact.status in {"review", "missing"}]
        candidate_limit = self.settings.llm_max_candidates
        if len(candidates) > candidate_limit:
            raise PlannerUnavailable(f"Candidate limit exceeded ({len(candidates)} > {candidate_limit})")

        group_aliases: dict[str, str] = {}
        for group_id, document_id in source_groups.items():
            group_aliases[group_id] = f"source_{len(group_aliases) + 1:03d}"
        group_by_document = {document_id: alias for group_id, alias in group_aliases.items() for document_id in [source_groups[group_id]]}
        row_descriptions = {
            (fact.document_id, fact.row_id): str(fact.normalized_value)
            for fact in facts
            if fact.row_id and fact.key == "description" and isinstance(fact.normalized_value, str)
        }
        compact_facts = []
        for fact in candidates:
            compact_facts.append({
                "fact_id": fact.fact_id,
                "source_group_id": group_aliases.get(fact.document_id, "unknown"),
                "document_type": fact.document_type,
                "role": fact.role,
                "key": fact.key,
                "label": fact.label,
                "value": str(fact.value) if numeric_value(fact) is not None else None,
                "currency": fact.currency,
                "unit": fact.unit,
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
            if fact.document_id in group_by_document
            and fact.role in {"field", "indicator"}
            and fact.status == "extracted"
            and isinstance(fact.value, str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact.value)
        ]
        link_aliases = {link.get("link_id"): f"link_{index + 1:03d}" for index, link in enumerate(linking.get("links", []))}
        safe_links = []
        for link in linking.get("links", []):
            evidence = []
            for item in link.get("evidence", []):
                source = item.get("source") or {}
                target_evidence = item.get("target") or {}
                source_doc = source.get("document_id") or link.get("source_document_id")
                target_doc = target_evidence.get("document_id") or link.get("target_document_id")

                def safe_path(value: Any, document_id: str | None, row_id: str | None) -> Any:
                    if not isinstance(value, str):
                        return value
                    if document_id:
                        value = value.replace(document_id, group_by_document.get(document_id, "source_unknown"))
                    if document_id and row_id:
                        value = value.replace(row_id, self._row_alias(document_id, row_id) or "row_unknown")
                    return value

                evidence.append({
                    "source_path": safe_path(source.get("path"), source_doc, link.get("source_row_id")),
                    "target_path": safe_path(target_evidence.get("path"), target_doc, link.get("target_row_id")),
                    "signal": item.get("signal"),
                    "source_normalized_value": source.get("normalized_value"),
                    "target_normalized_value": target_evidence.get("normalized_value"),
                })
            safe_links.append({
                "link_ref": link_aliases.get(link.get("link_id")),
                "relationship_type": link.get("relationship_type"),
                "source_group_id": group_by_document.get(link.get("source_document_id"), "unknown"),
                "target_group_id": group_by_document.get(link.get("target_document_id"), "unknown"),
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
                "candidate_source_groups": [group_by_document.get(doc_id, "unknown") for doc_id in item.get("candidate_document_ids", [])],
            }
            for item in linking.get("review_required", [])
        ]
        safe_diagnostics = [
            {
                "relationship_type": item.get("relationship_type"),
                "source_group_id": group_by_document.get(item.get("source_document_id"), "unknown"),
                "target_group_id": group_by_document.get(item.get("target_document_id"), "unknown"),
                "reason_codes": item.get("reason_codes", []),
                "candidate_status": item.get("candidate_status"),
            }
            for item in linking.get("link_validation_diagnostics", [])
        ]
        safe_unlinked = [
            {"source_group_id": group_by_document.get(item.get("document_id"), "unknown")}
            for item in linking.get("unlinked_documents", [])
        ]
        target_payload = target.model_dump(mode="json")
        for private_locator in ("target_fact_id", "kfz_document_id", "kfz_row_id"):
            target_payload.pop(private_locator, None)
        return {
            "target": target_payload,
            "candidates": compact_facts,
            "source_groups": list(group_aliases.values()),
            "document_date_facts": date_facts,
            "linking_graph": {
                "relationships": safe_links,
                "review_required": safe_review,
                "unlinked_source_groups": safe_unlinked,
                "validation_diagnostics": safe_diagnostics,
                "warning_count": len(linking.get("warnings", [])),
            },
            "output_contract": CalculationPlan.model_json_schema(),
        }

    def plan(self, target: TargetIndicator, facts: list[Fact], source_groups: dict[str, str], linking: dict[str, Any]) -> CalculationPlan:
        if not self.settings.llm_enabled or (not self.settings.llm_api_key and not self.settings.llm_trusted_local):
            raise PlannerUnavailable("LLM planner is not configured")
        payload = self.build_payload(target, facts, source_groups, linking)
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {}
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
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
        try:
            content = result["choices"][0]["message"]["content"]
            parsed = _json_content(content)
            for exclusion in parsed.get("excluded", []):
                alias = exclusion.get("source_group_id")
                if alias in {f"source_{index:03d}" for index in range(1, len(payload["source_groups"]) + 1)}:
                    reverse_groups = {f"source_{index:03d}": document_id for index, document_id in enumerate(source_groups.values(), start=1)}
                    exclusion["source_group_id"] = reverse_groups[alias]
            return CalculationPlan.model_validate(parsed)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise PlannerUnavailable(f"LLM returned an invalid plan: {exc}") from exc

