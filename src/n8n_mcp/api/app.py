"""FastAPI MVP for the internal n8n AI Ops interface."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from n8n_mcp.audit import read_audit_events
from n8n_mcp.client import N8nClient, N8nClientError
from n8n_mcp.service import (
    ServiceError,
    analyze_workflow_failure,
    attempt_fix,
    apply_fix,
    create_backup,
    get_workflow,
    list_backups,
    list_executions,
    list_workflows,
    propose_fix,
    restore_backup,
)


STATIC_DIR = Path(__file__).parent / "static"


class AnalyzeFailureRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    execution_id: str | None = Field(default=None)


class ProposeFixRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    execution_id: str | None = Field(default=None)


class ApplyFixRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    execution_id: str | None = Field(default=None)
    approved_by: str = Field(default="human", min_length=1, max_length=100)
    allow_medium_risk: bool = Field(default=False)
    use_attempt: bool = Field(default=False)


class RestoreBackupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    backup_path: str = Field(..., min_length=1)
    approved_by: str = Field(default="human", min_length=1, max_length=100)


def get_client(request: Request) -> N8nClient:
    client = getattr(request.app.state, "n8n_client", None)
    if not isinstance(client, N8nClient):
        raise HTTPException(status_code=500, detail="n8n client is not initialized")
    return client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = N8nClient()
    app.state.n8n_client = client
    try:
        yield
    finally:
        await client.close()


app = FastAPI(
    title="n8n AI Ops Internal API",
    description="Internal FastAPI MVP for safe n8n workflow diagnostics and approved fixes.",
    version="0.1.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_model=None)
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "n8n AI Ops API is running. Open /docs for API docs."}


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    client = get_client(request)
    return {
        "ok": True,
        "n8n_url": client.base_url,
        "docs": "/docs",
    }


@app.get("/workflows")
async def api_list_workflows(request: Request, limit: int = Query(default=1000, ge=1, le=1000)) -> dict[str, Any]:
    try:
        return await list_workflows(get_client(request), limit=limit)
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/workflows/{workflow_id}")
async def api_get_workflow(request: Request, workflow_id: str) -> dict[str, Any]:
    try:
        return await get_workflow(get_client(request), workflow_id)
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/workflows/{workflow_id}/backup")
async def api_backup_workflow(request: Request, workflow_id: str) -> dict[str, Any]:
    try:
        return await create_backup(get_client(request), workflow_id)
    except (N8nClientError, ServiceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/workflows/{workflow_id}/executions")
async def api_list_executions(
    request: Request,
    workflow_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return await list_executions(get_client(request), workflow_id, status=status, limit=limit)
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/workflows/{workflow_id}/analyze-failure")
async def api_analyze_failure(
    request: Request,
    workflow_id: str,
    body: AnalyzeFailureRequest | None = None,
) -> dict[str, Any]:
    try:
        payload = body or AnalyzeFailureRequest()
        return await analyze_workflow_failure(get_client(request), workflow_id, execution_id=payload.execution_id)
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/workflows/{workflow_id}/propose-fix")
async def api_propose_fix(
    request: Request,
    workflow_id: str,
    body: ProposeFixRequest | None = None,
) -> dict[str, Any]:
    try:
        payload = body or ProposeFixRequest()
        return await propose_fix(get_client(request), workflow_id, execution_id=payload.execution_id)
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/workflows/{workflow_id}/attempt-fix")
async def api_attempt_fix(
    request: Request,
    workflow_id: str,
    body: ProposeFixRequest | None = None,
) -> dict[str, Any]:
    try:
        payload = body or ProposeFixRequest()
        return await attempt_fix(get_client(request), workflow_id, execution_id=payload.execution_id)
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/workflows/{workflow_id}/apply-fix")
async def api_apply_fix(
    request: Request,
    workflow_id: str,
    body: ApplyFixRequest,
) -> dict[str, Any]:
    try:
        return await apply_fix(
            get_client(request),
            workflow_id,
            execution_id=body.execution_id,
            approved_by=body.approved_by,
            allow_medium_risk=body.allow_medium_risk,
            use_attempt=body.use_attempt,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except N8nClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/backups")
async def api_list_backups() -> dict[str, Any]:
    return list_backups()


@app.post("/workflows/{workflow_id}/restore")
async def api_restore_backup(
    request: Request,
    workflow_id: str,
    body: RestoreBackupRequest,
) -> dict[str, Any]:
    try:
        return await restore_backup(
            get_client(request),
            workflow_id,
            body.backup_path,
            approved_by=body.approved_by,
        )
    except (N8nClientError, ServiceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/audit-log")
async def api_audit_log(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    events = read_audit_events(limit=limit)
    return {"total": len(events), "events": events}


def main() -> None:
    """Run the internal API on localhost only."""
    uvicorn.run("n8n_mcp.api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
