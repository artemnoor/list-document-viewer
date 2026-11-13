from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VerificationStatus(StrEnum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    INSUFFICIENT_DATA = "insufficient_data"
    NEEDS_REVIEW = "needs_review"
    NOT_APPLICABLE = "not_applicable"


class DiscrepancyCategory(StrEnum):
    AMOUNT_DIFFERENCE = "amount_difference"
    WRONG_PERIOD = "wrong_period"
    DUPLICATE_OPERATION = "duplicate_operation"
    MISSING_SUPPORTING_DOCUMENT = "missing_supporting_document"
    INCORRECT_DOCUMENT_LINK = "incorrect_document_link"
    INDICATOR_DIFFERENCE = "quantity_or_indicator_difference"
    INCOMPATIBLE_UNIT = "incompatible_unit"
    ROUNDING_PROBLEM = "rounding_problem"
    CONFLICTING_PRIMARY_DOCUMENTS = "conflicting_primary_documents"
    UNSUBSTANTIATED_CAUSE = "unsubstantiated_cause"
    ECONOMIC_MEANING_MISMATCH = "economic_meaning_mismatch"


class PeriodRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str


class TolerancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    absolute: str | None = None
    absolute_unit: str | None = None
    relative: str | None = None
    rounding_scale: int | None = Field(default=None, ge=0, le=12)
    rounding_mode: Literal["HALF_UP", "HALF_EVEN", "DOWN", "UP"] = "HALF_UP"

    @field_validator("absolute", "relative")
    @classmethod
    def validate_decimal_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from decimal import Decimal, InvalidOperation

        try:
            parsed = Decimal(value)
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Tolerance must be a decimal string") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("Tolerance must be a finite non-negative decimal")
        return value


class VerificationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: PeriodRange | None = None
    tolerance: TolerancePolicy = Field(default_factory=TolerancePolicy)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def tolerance_requires_measure(self) -> VerificationContext:
        if self.tolerance.absolute is not None and not self.tolerance.absolute_unit:
            raise ValueError("absolute_unit is required when an absolute tolerance is supplied")
        return self


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    extraction: dict[str, Any]
    reconciliation_result: dict[str, Any]
    linking_result: dict[str, Any] | None = None
    supporting_extractions: list[dict[str, Any]] = Field(default_factory=list)
    context: VerificationContext = Field(default_factory=VerificationContext)


class ValueEvidence(BaseModel):
    source_value: Any = None
    normalized_value: Any = None
    value_type: str
    currency: str | None = None
    unit: str | None = None
    period: PeriodRange | None = None
    extraction_status: str | None = None
    json_pointer: str | None = None
    document_id: str | None = None
    extraction_id: str | None = None
    row_id: str | None = None
    provenance: dict[str, Any] | None = None


class Difference(BaseModel):
    absolute: str | None = None
    relative: str | None = None
    formula: str | None = None
    evaluated_actual: str | None = None
    evaluated_expected: str | None = None
    accepted_by: Literal["exact", "absolute_tolerance", "relative_tolerance", "rounding", "none"] = "none"


class Discrepancy(BaseModel):
    category: DiscrepancyCategory
    established: bool
    hypothesis: bool = False
    description: str
    evidence_references: list[str] = Field(default_factory=list)


class EvidenceTrace(BaseModel):
    actual_reference: dict[str, Any] | None = None
    reconciliation_reference: dict[str, Any] | None = None
    used_sources: list[dict[str, Any]] = Field(default_factory=list)
    excluded_sources: list[dict[str, Any]] = Field(default_factory=list)
    linking_references: list[dict[str, Any]] = Field(default_factory=list)
    provenance_chain: list[dict[str, Any]] = Field(default_factory=list)


class Uncertainty(BaseModel):
    level: Literal["none", "low", "medium", "high"]
    reasons: list[str] = Field(default_factory=list)
    manual_review_required: bool
    status_reason: str


class EvidenceTrust(BaseModel):
    """Independent trust dimensions; a declared status alone is never proof."""

    technical_validity: Literal["valid", "invalid", "incomplete", "not_checked"]
    automatic_link_confirmation: Literal["not_required", "confirmed", "unconfirmed", "rejected"]
    human_confirmation: Literal["not_required", "confirmed", "unconfirmed", "rejected"]
    calculation_trust: Literal["proven", "unproven", "invalid", "not_applicable"]


class VerificationCompleteness(BaseModel):
    total_indicators: int = Field(ge=0)
    applicable_indicators: int = Field(ge=0)
    verified_indicators: int = Field(ge=0)
    matched_indicators: int = Field(ge=0)
    mismatched_indicators: int = Field(ge=0)
    not_applicable_indicators: int = Field(ge=0)
    unresolved_indicators: int = Field(ge=0)
    complete: bool


class IndicatorResult(BaseModel):
    target_id: str
    semantic_key: str | None = None
    label: str | None = None
    value_type: str
    status: VerificationStatus
    actual: ValueEvidence | None = None
    expected: ValueEvidence | None = None
    difference: Difference = Field(default_factory=Difference)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    evidence: EvidenceTrace = Field(default_factory=EvidenceTrace)
    trust: EvidenceTrust = Field(default_factory=lambda: EvidenceTrust(
        technical_validity="not_checked",
        automatic_link_confirmation="not_required",
        human_confirmation="not_required",
        calculation_trust="unproven",
    ))
    comparison_rules: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    uncertainty: Uncertainty


class VerificationSummary(BaseModel):
    verification_id: str
    project_id: str
    calculation_id: str
    created_at: str
    overall_status: VerificationStatus
    indicator_count: int
    status_counts: dict[str, int]


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1.0"] = "1.1.0"
    verification_id: str
    project_id: str
    calculation_id: str
    created_at: str
    input_fingerprint: str
    input_metadata: dict[str, Any]
    overall_status: VerificationStatus
    summary: dict[str, int]
    completeness: VerificationCompleteness
    indicators: list[IndicatorResult]
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class VerificationHistory(BaseModel):
    items: list[VerificationSummary]
    limit: int
    offset: int
