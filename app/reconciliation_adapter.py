from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import unquote


@dataclass(frozen=True)
class ReconciliationTarget:
    """Engine-facing view over a target; source values remain owned upstream."""

    target_id: str
    target: dict[str, Any]
    result: dict[str, Any]
    array_index: int
    native_calculation: dict[str, Any] | None = None
    reference_pointer: str | None = None


class ReconciliationAdapter(Protocol):
    contract_version: str

    def adapt(self, reconciliation_result: dict[str, Any]) -> list[ReconciliationTarget]: ...


class ProvisionalReconciliationAdapter:
    """Adapter for the Verification project's original provisional 1.0.0 shape."""

    contract_version = "1.0.0"

    def adapt(self, reconciliation_result: dict[str, Any]) -> list[ReconciliationTarget]:
        if reconciliation_result.get("contract_version") != self.contract_version:
            raise ValueError(f"No provisional Reconciliation adapter for {reconciliation_result.get('contract_version')!r}")
        return [
            ReconciliationTarget(
                target_id=item["target_id"],
                target=item["target"],
                result=item["result"],
                array_index=index,
                reference_pointer=f"/targets/{index}/result",
            )
            for index, item in enumerate(reconciliation_result.get("targets", []))
        ]


def _fragment_to_value_pointer(source_path: str | None) -> str | None:
    if not isinstance(source_path, str) or not source_path.startswith("#/"):
        return None
    pointer = unquote(source_path[1:])
    return pointer if pointer.endswith("/value") else pointer + "/value"


def _period(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    start, end = value.get("start"), value.get("end")
    if isinstance(start, str) and isinstance(end, str):
        return {"start": start, "end": end}
    return None


def _value_type(currency: Any, unit: Any, value: Any) -> str:
    if isinstance(currency, str) and currency:
        return "money"
    if isinstance(unit, str) and unit:
        return "quantity"
    try:
        Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "string"
    return "decimal"


def _normalized_source(source: dict[str, Any], calculation: dict[str, Any]) -> dict[str, Any]:
    source_path = source.get("source_path")
    pointer = _fragment_to_value_pointer(source_path)
    plan = calculation.get("calculation_plan") or {}
    fact_id = source.get("fact_id")
    operation_ids = [
        step.get("step_id")
        for step in plan.get("steps", [])
        if isinstance(step, dict) and fact_id in step.get("inputs", []) and isinstance(step.get("step_id"), str)
    ]
    related_links = source.get("related_links") if isinstance(source.get("related_links"), list) else []
    link = next((item for item in related_links if isinstance(item, dict) and isinstance(item.get("link_id"), str)), None)
    confirmation = source.get("human_confirmation")
    target_document_id = ((calculation.get("target") or {}).get("kfz_origin") or {}).get("document_id")
    needs_link = source.get("document_id") != target_document_id
    if source.get("status") != "extracted":
        evidence_status = "rejected" if source.get("status") in {"rejected", "conflict"} else "unconfirmed"
    elif needs_link and link is None:
        evidence_status = "unconfirmed"
    elif isinstance(confirmation, dict) and confirmation.get("binding_status", "active") == "active":
        evidence_status = "human_confirmed"
    else:
        evidence_status = "system_validated"
    return {
        "source_id": fact_id,
        "document_id": source.get("document_id"),
        "extraction_id": source.get("extraction_id"),
        "row_id": source.get("row_id"),
        "json_pointer": pointer,
        "link_id": link.get("link_id") if link else None,
        "evidence_index": link.get("evidence_index") if link else None,
        "evidence_status": evidence_status,
        "operation_ids": operation_ids,
        "reason": source.get("inclusion_reason"),
        "currency": source.get("currency"),
        "unit": source.get("unit"),
        "native_fact_id": fact_id,
        "native_source_path": source_path,
        "native_input_hash": source.get("input_hash"),
    }


class ReconciliationEngine10Adapter:
    """Adapter for the published Reconciliation Engine result 1.0.0 contract."""

    contract_version = "1.0.0"

    def adapt(self, reconciliation_result: dict[str, Any]) -> list[ReconciliationTarget]:
        if reconciliation_result.get("contract_version") != self.contract_version or not isinstance(reconciliation_result.get("input_snapshot"), dict):
            raise ValueError("Payload does not match the published Reconciliation Engine 1.0.0 result shape")
        targets: list[ReconciliationTarget] = []
        for index, calculation in enumerate(reconciliation_result.get("calculations", [])):
            native_target = calculation.get("target", {})
            origin = native_target.get("kfz_origin", {})
            target_pointer = _fragment_to_value_pointer(origin.get("source_path"))
            currency = calculation.get("currency") or native_target.get("currency")
            unit = calculation.get("unit") or native_target.get("unit")
            expected_value = calculation.get("expected_value")
            value_type = _value_type(currency, unit, expected_value)
            period = _period(calculation.get("period"))
            amount_basis = calculation.get("amount_basis") or native_target.get("amount_basis")
            economic_measure = native_target.get("economic_measure")
            comparison_basis = {
                "planned": "plan",
                "actual": "actual",
                "accrued": "other",
                "paid": "other",
            }.get(economic_measure, "unknown")
            target = {
                "source_document_id": origin.get("document_id"),
                "extraction_id": origin.get("extraction_id"),
                "row_id": origin.get("row_id"),
                "json_pointer": target_pointer,
                "semantic_key": native_target.get("target_id"),
                "label": native_target.get("label"),
                "value_type": value_type,
                "period": period,
                "unit": unit,
                "currency": currency,
                "vat_basis": amount_basis if amount_basis in {"gross", "net"} else "unknown",
                "comparison_basis": comparison_basis,
            }
            used_sources = [
                _normalized_source(source, calculation)
                for source in calculation.get("used_sources", [])
                if isinstance(source, dict)
            ]
            excluded_sources = [
                _normalized_source(source, calculation)
                for source in calculation.get("excluded_sources", [])
                if isinstance(source, dict)
            ]
            if expected_value is not None and currency:
                expected_value = {"amount": str(expected_value), "currency": currency}
            calculation_status = "complete" if calculation.get("status") == "calculated" else "incomplete"
            trace = calculation.get("steps", [])
            trace_by_id = {step.get("step_id"): step for step in trace if isinstance(step, dict)}
            operations = []
            for step in (calculation.get("calculation_plan") or {}).get("steps", []):
                if not isinstance(step, dict):
                    continue
                recorded = trace_by_id.get(step.get("step_id"), {})
                operations.append({
                    "operation_id": step.get("step_id"),
                    "operation_type": step.get("operation"),
                    "formula": calculation.get("formula") or "",
                    "input_source_ids": step.get("inputs", []),
                    "output_value": recorded.get("value"),
                })
            diagnostics = calculation.get("errors", calculation.get("diagnostics", []))
            if not isinstance(diagnostics, list):
                diagnostics = []
            result = {
                "expected_value": expected_value,
                "value_type": value_type,
                "semantic_key": target["semantic_key"],
                "period": period,
                "unit": unit,
                "currency": currency,
                "vat_basis": target["vat_basis"],
                "comparison_basis": comparison_basis,
                "calculation_status": calculation_status,
                "comparison_eligible": calculation.get("status") == "calculated",
                "formula": calculation.get("formula"),
                "applied_rules": [calculation.get("method_description")] if calculation.get("method_description") else [],
                "used_sources": used_sources,
                "excluded_sources": excluded_sources,
                "operations": operations,
                "diagnostics": diagnostics,
                "warnings": [],
                "provenance": calculation.get("provenance", {}),
                "calculation_id": reconciliation_result.get("reconciliation_id"),
            }
            targets.append(ReconciliationTarget(
                target_id=str(native_target.get("target_id") or f"calculation-{index}"),
                target=target,
                result=result,
                array_index=index,
                native_calculation=calculation,
                reference_pointer=f"/calculations/{index}",
            ))
        return targets


def is_reconciliation_engine_result(result: dict[str, Any]) -> bool:
    return result.get("contract_version") == "1.0.0" and isinstance(result.get("input_snapshot"), dict) and isinstance(result.get("calculations"), list)


def get_reconciliation_adapter(contract_or_result: str | dict[str, Any]) -> ReconciliationAdapter:
    if isinstance(contract_or_result, dict):
        if is_reconciliation_engine_result(contract_or_result):
            return ReconciliationEngine10Adapter()
        contract_version = contract_or_result.get("contract_version")
    else:
        contract_version = contract_or_result
    if contract_version == ProvisionalReconciliationAdapter.contract_version:
        return ProvisionalReconciliationAdapter()
    raise ValueError(f"No Reconciliation adapter registered for contract {contract_version!r}")


def reconciliation_identity(reconciliation_result: dict[str, Any]) -> dict[str, str | None]:
    if is_reconciliation_engine_result(reconciliation_result):
        reconciliation_id = reconciliation_result.get("reconciliation_id")
        return {
            "contract_version": reconciliation_result.get("contract_version"),
            "run_id": reconciliation_id,
            "calculation_id": reconciliation_id,
            "engine_version": reconciliation_result.get("engine_version"),
        }
    metadata = reconciliation_result.get("run_metadata", {})
    return {
        "contract_version": reconciliation_result.get("contract_version"),
        "run_id": metadata.get("run_id"),
        "calculation_id": metadata.get("calculation_id"),
        "engine_version": metadata.get("reconciliation_engine_version"),
    }
