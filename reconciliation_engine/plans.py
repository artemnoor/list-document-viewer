from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanStep(PlanModel):
    step_id: str = Field(min_length=1)
    operation: Literal["sum", "add", "subtract", "multiply", "divide", "round"]
    inputs: list[str] = Field(min_length=1)
    scale: int | None = Field(default=None, ge=0, le=8)


class PlanInclusion(PlanModel):
    fact_id: str
    reason: str = Field(min_length=1)


class PlanExclusion(PlanModel):
    reason: str = Field(min_length=1)
    fact_id: str | None = None
    source_group_id: str | None = None


class CalculationPlan(PlanModel):
    plan_version: Literal["1.0.0"] = "1.0.0"
    target_id: str
    method_description: str = Field(min_length=1)
    included: list[PlanInclusion] = Field(min_length=1)
    excluded: list[PlanExclusion] = Field(default_factory=list)
    steps: list[PlanStep] = Field(min_length=1, max_length=50)
    result_step_id: str
    currency: str | None = None
    unit: str | None = None
    amount_basis: Literal["gross", "net", "unspecified"] = "unspecified"
    rounding_scale: int = Field(default=2, ge=0, le=8)
    assumptions: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    requires_manual_review: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

