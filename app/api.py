from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, HTTPException, Path as PathParameter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.contracts import ContractValidationError
from app.explanations import ReviewExplanationProvider, provider_from_environment
from app.models import VerificationHistory, VerificationRequest, VerificationResult
from app.storage import RunNotFound, SQLiteVerificationStore


class DiagnosticReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    diagnostics: list[dict[str, Any]]
    indicator_diagnostics: dict[str, list[dict[str, Any]]]


def create_app(
    storage_path: str | Path | None = None,
    explanation_provider: ReviewExplanationProvider | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Phystech Trace Verification Engine",
        summary="Deterministic verification of KFZ metrics against Reconciliation outputs.",
        description=(
            "Compares values supplied by Structured Extraction and Reconciliation. "
            "It does not extract source data or recalculate Reconciliation results."
        ),
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    configured_path = storage_path or os.getenv("VERIFICATION_DB_PATH", "data/verification.sqlite3")
    app.state.store = SQLiteVerificationStore(configured_path, explanation_provider=explanation_provider)

    @app.exception_handler(ContractValidationError)
    async def contract_validation_handler(_: Request, exc: ContractValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.as_list()})

    @app.get("/health", tags=["service"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "verification-engine", "version": "1.0.0"}

    router = APIRouter(prefix="/api/v1/verifications", tags=["verification"])

    @router.post("", response_model=VerificationResult, summary="Run or retrieve an idempotent verification")
    def create_verification(payload: VerificationRequest, request: Request) -> VerificationResult:
        return request.app.state.store.create(payload)

    @router.get("", response_model=VerificationHistory, summary="List verification runs")
    def list_verifications(
        request: Request,
        project_id: Annotated[str | None, Query(min_length=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> VerificationHistory:
        return request.app.state.store.history(project_id=project_id, limit=limit, offset=offset)

    @router.get("/{verification_id}", response_model=VerificationResult, summary="Get a verification result")
    def get_verification(
        verification_id: Annotated[str, PathParameter(min_length=1)], request: Request
    ) -> VerificationResult:
        try:
            return request.app.state.store.get(verification_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="Verification run not found") from exc

    @router.get("/{verification_id}/diagnostics", response_model=DiagnosticReport, summary="Get verification diagnostics")
    def get_diagnostics(
        verification_id: Annotated[str, PathParameter(min_length=1)], request: Request
    ) -> DiagnosticReport:
        try:
            result = request.app.state.store.get(verification_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="Verification run not found") from exc
        return DiagnosticReport(
            verification_id=verification_id,
            diagnostics=result.diagnostics,
            indicator_diagnostics={
                indicator.target_id: indicator.diagnostics
                for indicator in result.indicators
                if indicator.diagnostics
            },
        )

    app.include_router(router)
    return app


app = create_app(explanation_provider=provider_from_environment())
