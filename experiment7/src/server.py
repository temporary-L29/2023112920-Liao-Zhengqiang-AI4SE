"""
FastAPI server — HTTP API for the code review service.

Endpoints:
  GET  /health           — service health and model status
  GET  /v1/models        — list all models with status
  POST /v1/reviews       — execute a code review
  GET  /v1/history       — list review history
  GET  /v1/history/{id}  — get review detail
"""

from __future__ import annotations

import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from src.schemas import (
    ReviewRequest, ReviewResponse, ErrorResponse, ErrorDetail,
    HealthResponse, HistoryListResponse, HistoryEntry,
)
from src.review_service import execute_review, get_registry
from src.history_store import list_entries, get_detail
from src.config import HOST, PORT, logger

app = FastAPI(
    title="Code Review Service",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)

STARTED_AT = datetime.datetime.now(datetime.timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════
# Exception handlers
# ═══════════════════════════════════════════════════════════════

@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(code="BAD_REQUEST", message=str(exc)),
        ).model_dump(),
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request, exc: RuntimeError):
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(code="MODEL_ERROR", message=str(exc)),
        ).model_dump(),
    )


# ═══════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
async def health():
    registry = get_registry()
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        started_at=STARTED_AT,
        models=registry.list_models(),
    )


@app.get("/v1/models")
async def list_models():
    registry = get_registry()
    return {"models": [m.model_dump() for m in registry.list_models()]}


@app.post("/v1/reviews", response_model=ReviewResponse)
async def create_review(request: ReviewRequest):
    try:
        response = await execute_review(request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/history", response_model=HistoryListResponse)
async def get_history(limit: int = Query(default=20, ge=1, le=100)):
    return list_entries(limit=limit)


@app.get("/v1/history/{history_id}")
async def get_history_detail(history_id: str):
    record = get_detail(history_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"History entry not found: {history_id}")
    return record


# ═══════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════

def run_server():
    import uvicorn
    logger.info(f"Starting code review server on {HOST}:{PORT}")
    uvicorn.run(
        "src.server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run_server()
