from typing import Annotated

import hmac
from fastapi import FastAPI, HTTPException, Path, Request, Response, Header

from . import __version__
from .config import get_settings
from .errors import InputContractError
from .models import HealthResponse, ReconciliationRequest, ReconciliationResult
from .planner import LLMPlanner
from .service import reconcile, reconciliation_id_for
from .storage import ResultStore

settings = get_settings()
store = ResultStore(settings.result_store_dir)
app = FastAPI(
    title="Phystech Trace — Reconciliation Engine",
    version=__version__,
    description=(
        "Builds reproducible expected-value calculations from Structured Extraction "
        "1.2.0 and Document Linking 1.2.0 inputs. It does not compare results with "
        "KФЗ values and does not make a reliability conclusion."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name, version=__version__)


def _project_scope(authorization: str | None, project_id: str | None) -> str:
    if not settings.api_auth_enabled:
        return "local"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "authentication_required"}, headers={"WWW-Authenticate": "Bearer"})
    if not project_id:
        raise HTTPException(status_code=400, detail={"code": "project_id_required"})
    token = authorization[7:]
    authorized_project = None
    for configured_token, configured_project in settings.api_project_tokens.items():
        if hmac.compare_digest(configured_token, token):
            authorized_project = configured_project
    if authorized_project is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials"}, headers={"WWW-Authenticate": "Bearer"})
    if not hmac.compare_digest(authorized_project, project_id):
        raise HTTPException(status_code=403, detail={"code": "project_scope_forbidden"})
    return authorized_project


@app.post("/api/v1/reconciliations", status_code=201, response_model=ReconciliationResult, responses={200: {"model": ReconciliationResult, "description": "Existing idempotent result"}}, tags=["reconciliations"])
def create_reconciliation(
    payload: ReconciliationRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None, alias="Authorization", description="Bearer token when API_AUTH_ENABLED is enabled"),
    project_id: str | None = Header(default=None, alias="X-Project-ID", description="Project scope assigned to the bearer token"),
) -> ReconciliationResult:
    project_scope = _project_scope(authorization, project_id)
    store_instance: ResultStore = request.app.state.result_store
    expected_id = reconciliation_id_for(payload, settings)
    existing = store_instance.get(expected_id, project_scope)
    if existing is not None:
        response.status_code = 200
        return ReconciliationResult.model_validate(existing)
    planner = LLMPlanner(settings) if settings.llm_enabled else None
    try:
        result = reconcile(payload, settings, planner)
    except InputContractError as exc:
        raise HTTPException(status_code=422, detail={"code": "input_contract_error", "diagnostics": [item.as_dict() for item in exc.diagnostics]}) from exc
    if result["reconciliation_id"] != expected_id:
        raise HTTPException(status_code=500, detail={"code": "reconciliation_identity_mismatch"})
    store_instance.save(result, project_scope)
    store_instance.save_llm_audit(result["reconciliation_id"], planner.call_records if planner is not None else [], project_scope)
    return ReconciliationResult.model_validate(result)


@app.get("/api/v1/reconciliations/{reconciliation_id}/llm-audit", tags=["reconciliations"])
def get_llm_audit(
    reconciliation_id: Annotated[str, Path(min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")],
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    project_id: str | None = Header(default=None, alias="X-Project-ID"),
) -> dict:
    project_scope = _project_scope(authorization, project_id)
    store_instance: ResultStore = request.app.state.result_store
    if store_instance.get(reconciliation_id, project_scope) is None:
        raise HTTPException(status_code=404, detail={"code": "reconciliation_not_found", "reconciliation_id": reconciliation_id})
    return store_instance.get_llm_audit(reconciliation_id, project_scope) or {"reconciliation_id": reconciliation_id, "calls": []}


@app.get("/api/v1/reconciliations/{reconciliation_id}", tags=["reconciliations"])
def get_reconciliation(
    reconciliation_id: Annotated[str, Path(min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")],
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization", description="Bearer token when API_AUTH_ENABLED is enabled"),
    project_id: str | None = Header(default=None, alias="X-Project-ID", description="Project scope assigned to the bearer token"),
) -> ReconciliationResult:
    project_scope = _project_scope(authorization, project_id)
    store_instance: ResultStore = request.app.state.result_store
    result = store_instance.get(reconciliation_id, project_scope)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "reconciliation_not_found", "reconciliation_id": reconciliation_id})
    return ReconciliationResult.model_validate(result)


app.state.result_store = store

