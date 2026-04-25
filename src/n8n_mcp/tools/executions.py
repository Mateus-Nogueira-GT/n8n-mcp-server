"""MCP tools for n8n execution operations."""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from n8n_mcp.client import N8nClientError
from n8n_mcp.context import get_n8n_client


class ListExecutionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class ExecutionIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    execution_id: str = Field(..., min_length=1)


class ExecuteWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    input_data: Optional[dict[str, Any]] = None


def register_execution_tools(mcp: FastMCP) -> None:
    """Register execution tools."""

    @mcp.tool(name="n8n_list_executions", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_list_executions(ctx: Context, params: ListExecutionsInput) -> str:
        client = get_n8n_client(ctx)
        try:
            data = await client.list_executions(workflow_id=params.workflow_id, status=params.status, limit=params.limit)
            executions = [{
                "id": ex.get("id"),
                "workflowId": ex.get("workflowId"),
                "status": ex.get("status"),
                "startedAt": ex.get("startedAt"),
                "stoppedAt": ex.get("stoppedAt"),
                "mode": ex.get("mode"),
                "finished": ex.get("finished"),
            } for ex in data.get("data", [])]
            return json.dumps({"total": len(executions), "executions": executions}, indent=2)
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_get_execution", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_get_execution(ctx: Context, params: ExecutionIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            return json.dumps(await client.get_execution(params.execution_id, include_data=True), indent=2, default=str)
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_retry_execution", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_retry_execution(ctx: Context, params: ExecutionIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            return json.dumps({"success": True, "execution": await client.retry_execution(params.execution_id)}, indent=2, default=str)
        except N8nClientError as exc:
            return f"Error retrying execution: {exc}"

    @mcp.tool(name="n8n_execute_workflow", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_execute_workflow(ctx: Context, params: ExecuteWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            result = await client.execute_workflow(params.workflow_id, params.input_data)
            return json.dumps({"success": True, "result": result}, indent=2, default=str)
        except N8nClientError as exc:
            return f"Error executing workflow: {exc}"
