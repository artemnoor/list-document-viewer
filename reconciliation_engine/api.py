from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Request

from . import __version__
from .config import get_settings
from .errors import InputContractError
from .models import HealthResponse, ReconciliationRequest, ReconciliationResult
from .service import reconcile
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


@app.post("/api/v1/reconciliations", status_code=201, response_model=ReconciliationResult, tags=["reconciliations"])
def create_reconciliation(payload: ReconciliationRequest, request: Request) -> ReconciliationResult:
    try:
        result = reconcile(payload, get_settings())
    except InputContractError as exc:
        raise HTTPException(status_code=422, detail={"code": "input_contract_error", "diagnostics": [item.as_dict() for item in exc.diagnostics]}) from exc
    store_instance: ResultStore = request.app.state.result_store
    store_instance.save(result)
    return ReconciliationResult.model_validate(result)


@app.get("/api/v1/reconciliations/{reconciliation_id}", tags=["reconciliations"])
def get_reconciliation(
    reconciliation_id: Annotated[str, Path(min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")],
    request: Request,
) -> ReconciliationResult:
    store_instance: ResultStore = request.app.state.result_store
    result = store_instance.get(reconciliation_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "reconciliation_not_found", "reconciliation_id": reconciliation_id})
    return ReconciliationResult.model_validate(result)


app.state.result_store = store

