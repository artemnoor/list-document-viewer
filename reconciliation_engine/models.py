from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetIndicator(StrictModel):
    target_id: str = Field(min_length=1, description="Stable ID for this calculation target")
    target_fact_id: str | None = Field(default=None, description="Optional fact ID for the KФЗ indicator or row being reconciled")
    kfz_document_id: str = Field(min_length=1, description="Extraction document containing the exact KФЗ target indicator")
    kfz_source_path: str = Field(pattern=r"^#/(?:[^\s]*)$", description="Exact JSON Pointer to the target indicator wrapper")
    kfz_row_id: str | None = None
    label: str = Field(min_length=1)
    description: str = ""
    unit: str | None = None
    currency: str | None = None
    amount_basis: Literal["gross", "net", "unspecified"] = "unspecified"
    rounding_scale: int = Field(default=2, ge=0, le=8)
    period_basis: Literal["document_period", "operation_date", "none"] = "document_period"
    required_document_types: list[str] = Field(default_factory=list)


class ReconciliationContext(StrictModel):
    period_start: date | None = None
    period_end: date | None = None
    targets: list[TargetIndicator] = Field(min_length=1, max_length=100)
    data_classification: Literal["open", "anonymized", "confidential"] = "confidential"
    external_llm_allowed: bool = False
    rounding_mode: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"

    @model_validator(mode="after")
    def validate_period(self) -> "ReconciliationContext":
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        target_ids = [target.target_id for target in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("target_id values must be unique")
        if self.external_llm_allowed and self.data_classification == "confidential":
            raise ValueError("confidential data cannot be sent to an external LLM")
        return self


class ConfirmedDecision(StrictModel):
    decision_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    confirmed_at: datetime
    plan: dict[str, Any]
    accepted_fact_ids: list[str] = Field(default_factory=list)
    accepted_link_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_timezone(self) -> "ConfirmedDecision":
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("confirmed_at must include a timezone")
        if len(self.accepted_fact_ids) != len(set(self.accepted_fact_ids)):
            raise ValueError("accepted_fact_ids must be unique")
        if len(self.accepted_link_ids) != len(set(self.accepted_link_ids)):
            raise ValueError("accepted_link_ids must be unique")
        return self


class ReconciliationRequest(StrictModel):
    contract_version: Literal["1.0.0"]
    extraction_results: list[dict[str, Any]] = Field(min_length=1)
    linking_result: dict[str, Any]
    context: ReconciliationContext
    prior_decisions: list[ConfirmedDecision] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ResultSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    document_id: str
    extraction_id: str
    document_type: str
    row_id: str | None = None
    source_path: str
    role: str
    key: str
    label: str
    value: Any
    numeric_value: str | None = None
    source_value: Any
    status: str
    confidence: float | None
    currency: str | None
    unit: str | None
    provenance: dict[str, Any] | None
    input_hash: str
    related_links: list[dict[str, Any]]
    inclusion_reason: str | None = None
    exclusion_reason: str | None = None
    used_in_result: bool | None = None
    human_confirmation: dict[str, Any] | None = None


class CalculationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: dict[str, Any]
    status: Literal["calculated", "insufficient_data", "manual_review"]
    data_sufficiency: Literal["sufficient", "partial", "unknown"]
    completeness_status: Literal["complete", "partial", "unknown"]
    uncertainty_status: Literal["none", "present", "unknown"]
    expected_value: str | None
    exact_value_before_rounding: str | None
    currency: str | None
    unit: str | None
    period: dict[str, Any]
    amount_basis: str
    rounding: dict[str, Any]
    sign_convention: Literal["preserve_source_sign; subtraction_is_explicit"]
    plan_source: Literal["none", "llm", "human_confirmed_decision"]
    method_description: str | None = None
    formula: str | None
    formula_status: Literal["executed", "proposed", "not_available"]
    calculation_plan: dict[str, Any] | None
    steps: list[dict[str, Any]]
    human_confirmations: list[dict[str, Any]]
    included_sources: list[ResultSource]
    used_sources: list[ResultSource]
    excluded_sources: list[ResultSource]
    provenance: dict[str, Any]
    errors: list[dict[str, Any]]
    information_gaps: list[str]
    assumptions: list[str]
    diagnostics: list[dict[str, Any]]
    manual_review_required: bool
    comparison_performed: Literal[False]
    reliability_conclusion: None
    input_documents: list[dict[str, Any]]
    linking_context: dict[str, Any]


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_id: str
    contract_version: Literal["1.0.0"]
    engine_version: str
    created_at: str
    input_snapshot: dict[str, Any]
    calculations: list[CalculationResult]
    diagnostics: list[dict[str, Any]]
    scope: dict[str, Any]

