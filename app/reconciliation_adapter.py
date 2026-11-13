from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ReconciliationTarget:
    """Engine-facing view over a target; values remain owned by Reconciliation."""

    target_id: str
    target: dict[str, Any]
    result: dict[str, Any]
    array_index: int


class ReconciliationAdapter(Protocol):
    contract_version: str

    def adapt(self, reconciliation_result: dict[str, Any]) -> list[ReconciliationTarget]: ...


class ProvisionalReconciliationAdapter:
    """Adapter for reconciliation-result-1.0.0; performs no arithmetic."""

    contract_version = "1.0.0"

    def adapt(self, reconciliation_result: dict[str, Any]) -> list[ReconciliationTarget]:
        if reconciliation_result.get("contract_version") != self.contract_version:
            raise ValueError(f"No Reconciliation adapter for contract {reconciliation_result.get('contract_version')!r}")
        return [
            ReconciliationTarget(
                target_id=item["target_id"],
                target=item["target"],
                result=item["result"],
                array_index=index,
            )
            for index, item in enumerate(reconciliation_result.get("targets", []))
        ]


def get_reconciliation_adapter(contract_version: str) -> ReconciliationAdapter:
    if contract_version == ProvisionalReconciliationAdapter.contract_version:
        return ProvisionalReconciliationAdapter()
    raise ValueError(f"No Reconciliation adapter registered for contract {contract_version!r}")
