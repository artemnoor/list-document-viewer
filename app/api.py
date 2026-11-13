from __future__ import annotations

import os
import hmac
import json
import asyncio
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path as PathParameter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

from app.contracts import ContractValidationError
from app.explanations import ReviewExplanationProvider, provider_from_environment
from app.artifact_adapter import ArtifactStoreError, FileArtifactAdapter
from app.models import ArtifactBundleRequest, VerificationHistory, VerificationRequest, VerificationResult
from app.storage import RunNotFound, SQLiteVerificationStore


class RequestSizeLimitMiddleware:
    def __init__(self, app, max_bytes: int, timeout_seconds: float):
        self.app = app
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            if int(headers.get(b"content-length", b"0")) > self.max_bytes:
                await self._too_large(scope, send)
                return
        except ValueError:
            await self._too_large(scope, send)
            return
        messages = []
        total = 0
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self._request_timeout(scope, send)
                return
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                await self._request_timeout(scope, send)
                return
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    await self._too_large(scope, send)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                current = messages[index]
                index += 1
                return current
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(scope, send):
        body = b'{"detail":"Request body is too large"}'
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _request_timeout(scope, send):
        body = b'{"detail":"Request receive time limit exceeded"}'
        await send({"type": "http.response.start", "status": 408, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class DiagnosticReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    diagnostics: list[dict[str, Any]]
    indicator_diagnostics: dict[str, list[dict[str, Any]]]


def create_app(
    storage_path: str | Path | None = None,
    explanation_provider: ReviewExplanationProvider | None = None,
    *,
    auth_mode: str | None = None,
    project_tokens: dict[str, str] | None = None,
    max_request_bytes: int | None = None,
    artifact_root: str | Path | None = None,
) -> FastAPI:
    resolved_auth_mode = (auth_mode or os.getenv("VERIFICATION_AUTH_MODE", "required")).strip().lower()
    if resolved_auth_mode not in {"required", "development", "disabled"}:
        raise ValueError("VERIFICATION_AUTH_MODE must be required, development, or disabled")
    if project_tokens is None:
        try:
            project_tokens = json.loads(os.getenv("VERIFICATION_PROJECT_TOKENS", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("VERIFICATION_PROJECT_TOKENS must be a JSON object") from exc
    if not isinstance(project_tokens, dict) or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in project_tokens.items()):
        raise ValueError("VERIFICATION_PROJECT_TOKENS must map project IDs to string tokens")
    size_limit = max_request_bytes if max_request_bytes is not None else int(os.getenv("VERIFICATION_MAX_REQUEST_BYTES", "16777216"))
    if size_limit < 1024 or size_limit > 67108864:
        raise ValueError("VERIFICATION_MAX_REQUEST_BYTES must be between 1024 and 67108864")
    configured_artifact_root = artifact_root or os.getenv("VERIFICATION_ARTIFACT_ROOT")
    artifact_max_bytes = int(os.getenv("VERIFICATION_MAX_ARTIFACT_BYTES", "16777216"))
    artifact_cache_bytes = int(os.getenv("VERIFICATION_ARTIFACT_CACHE_BYTES", "67108864"))
    if artifact_max_bytes < 1 or artifact_max_bytes > 67108864:
        raise ValueError("VERIFICATION_MAX_ARTIFACT_BYTES must be between 1 and 67108864")
    if artifact_cache_bytes < 0 or artifact_cache_bytes > 268435456:
        raise ValueError("VERIFICATION_ARTIFACT_CACHE_BYTES must be between 0 and 268435456")
    request_timeout = max(1.0, float(os.getenv("VERIFICATION_REQUEST_TIMEOUT_SECONDS", "30")))
    app = FastAPI(
        title="Phystech Trace Verification Engine",
        summary="Deterministic verification of KFZ metrics against Reconciliation outputs.",
        description=(
            "Compares values supplied by Structured Extraction and Reconciliation. "
            "It does not extract source data or plan Reconciliation; supported formal calculation proofs are independently checked."
        ),
        version="1.2.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    configured_path = storage_path or os.getenv("VERIFICATION_DB_PATH", "data/verification.sqlite3")
    app.state.store = SQLiteVerificationStore(configured_path, explanation_provider=explanation_provider)
    app.state.auth_mode = resolved_auth_mode
    app.state.project_tokens = project_tokens
    app.state.artifacts = FileArtifactAdapter(
        configured_artifact_root,
        max_artifact_bytes=artifact_max_bytes,
        cache_bytes=artifact_cache_bytes,
    ) if configured_artifact_root else None
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=size_limit, timeout_seconds=request_timeout)

    def authorize(project_id: str, token: str | None, request: Request) -> None:
        mode = request.app.state.auth_mode
        if mode == "disabled":
            return
        expected = request.app.state.project_tokens.get(project_id)
        if expected is None:
            if mode == "development" and not request.app.state.project_tokens:
                return
            if mode == "required" and not request.app.state.project_tokens:
                raise HTTPException(status_code=503, detail="Service authentication is not configured")
            raise HTTPException(status_code=404, detail="Project not found")
        if not token or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service credentials")

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo invalid values; requests can contain financial documents.
        errors = [{"loc": list(item.get("loc", ())), "type": item.get("type", "value_error"), "msg": "Invalid request data."} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(ContractValidationError)
    async def contract_validation_handler(_: Request, exc: ContractValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.as_list()})

    @app.exception_handler(TimeoutError)
    async def processing_timeout_handler(_: Request, __: TimeoutError) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": "Verification processing time limit exceeded"})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "Verification request failed"})

    @app.get("/health", tags=["service"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "verification-engine", "version": "1.2.0"}

    router = APIRouter(prefix="/api/v1/verifications", tags=["verification"])
    service_token_header = APIKeyHeader(name="X-Service-Token", auto_error=False)

    @router.post("", response_model=VerificationResult, summary="Run or retrieve an idempotent verification")
    def create_verification(
        payload: VerificationRequest,
        request: Request,
        token: str | None = Depends(service_token_header),
    ) -> VerificationResult:
        authorize(payload.project_id, token, request)
        return request.app.state.store.create(payload)

    @router.post("/from-artifacts", response_model=VerificationResult, summary="Run verification from immutable artifact references")
    def create_verification_from_artifacts(
        payload: ArtifactBundleRequest,
        request: Request,
        token: str | None = Depends(service_token_header),
    ) -> VerificationResult:
        authorize(payload.project_id, token, request)
        adapter: FileArtifactAdapter | None = request.app.state.artifacts
        if adapter is None:
            raise HTTPException(status_code=503, detail="Artifact storage is not configured")
        try:
            resolved = VerificationRequest(
                project_id=payload.project_id,
                extraction=adapter.resolve(payload.project_id, payload.extraction.artifact_id, payload.extraction.sha256),
                supporting_extractions=[
                    adapter.resolve(payload.project_id, item.artifact_id, item.sha256)
                    for item in payload.supporting_extractions
                ],
                reconciliation_result=adapter.resolve(
                    payload.project_id, payload.reconciliation_result.artifact_id, payload.reconciliation_result.sha256
                ),
                linking_result=(
                    adapter.resolve(payload.project_id, payload.linking_result.artifact_id, payload.linking_result.sha256)
                    if payload.linking_result else None
                ),
                context=payload.context,
            )
        except ArtifactStoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return request.app.state.store.create(resolved)

    @router.get("", response_model=VerificationHistory, summary="List verification runs")
    def list_verifications(
        request: Request,
        project_id: Annotated[str, Query(min_length=1)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        token: str | None = Depends(service_token_header),
    ) -> VerificationHistory:
        authorize(project_id, token, request)
        return request.app.state.store.history(project_id=project_id, limit=limit, offset=offset)

    @router.get("/{verification_id}", response_model=VerificationResult, summary="Get a verification result")
    def get_verification(
        verification_id: Annotated[str, PathParameter(min_length=1)],
        request: Request,
        project_id: Annotated[str, Query(min_length=1)],
        token: str | None = Depends(service_token_header),
    ) -> VerificationResult:
        try:
            authorize(project_id, token, request)
            return request.app.state.store.get_for_project(verification_id, project_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="Verification run not found") from exc

    @router.get("/{verification_id}/diagnostics", response_model=DiagnosticReport, summary="Get verification diagnostics")
    def get_diagnostics(
        verification_id: Annotated[str, PathParameter(min_length=1)],
        request: Request,
        project_id: Annotated[str, Query(min_length=1)],
        token: str | None = Depends(service_token_header),
    ) -> DiagnosticReport:
        try:
            authorize(project_id, token, request)
            result = request.app.state.store.get_for_project(verification_id, project_id)
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
