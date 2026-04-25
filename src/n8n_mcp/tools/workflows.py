"""MCP tools for n8n workflow operations."""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from n8n_mcp.backup import BackupError, backup_workflow, load_backup
from n8n_mcp.client import N8nClientError
from n8n_mcp.confirmation import requires_confirmation
from n8n_mcp.context import get_n8n_client
from n8n_mcp.workflow_utils import workflow_update_payload


class ListWorkflowsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    active: Optional[bool] = None
    tags: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=250)


class WorkflowIdInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)


class DeleteWorkflowInput(WorkflowIdInput):
    confirm_delete: bool = Field(default=False)


class CreateWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1, max_length=200)
    nodes: list[dict[str, Any]]
    connections: dict[str, Any] = Field(default_factory=dict)
    settings: Optional[dict[str, Any]] = None


class UpdateWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    name: Optional[str] = Field(default=None, max_length=200)
    nodes: Optional[list[dict[str, Any]]] = None
    connections: Optional[dict[str, Any]] = None
    settings: Optional[dict[str, Any]] = None


class RestoreWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    backup_path: str = Field(..., min_length=1)


def register_workflow_tools(mcp: FastMCP) -> None:
    """Register workflow CRUD and backup tools."""

    @mcp.tool(name="n8n_list_workflows", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_list_workflows(ctx: Context, params: ListWorkflowsInput) -> str:
        client = get_n8n_client(ctx)
        try:
            data = await client.list_workflows(active=params.active, tags=params.tags, limit=params.limit)
            workflows = [{
                "id": wf.get("id"),
                "name": wf.get("name"),
                "active": wf.get("active"),
                "tags": [t.get("name", "") for t in wf.get("tags", [])],
                "updatedAt": wf.get("updatedAt"),
                "createdAt": wf.get("createdAt"),
            } for wf in data.get("data", [])]
            return json.dumps({"total": len(workflows), "workflows": workflows}, indent=2)
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_get_workflow", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_get_workflow(ctx: Context, params: WorkflowIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            return json.dumps(await client.get_workflow(params.workflow_id), indent=2, default=str)
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_export_workflow", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_export_workflow(ctx: Context, params: WorkflowIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            return json.dumps(await client.get_workflow(params.workflow_id), indent=2, default=str)
        except N8nClientError as exc:
            return f"Error exporting workflow: {exc}"

    @mcp.tool(name="n8n_backup_workflow", annotations={"readOnlyHint": True, "idempotentHint": False})
    async def n8n_backup_workflow(ctx: Context, params: WorkflowIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, timestamp = await backup_workflow(client, params.workflow_id)
            return json.dumps({"success": True, "workflow_id": params.workflow_id, "backup": backup_path, "timestamp": timestamp}, indent=2)
        except (BackupError, N8nClientError) as exc:
            return f"Error backing up workflow: {exc}"

    @mcp.tool(name="n8n_restore_workflow", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_restore_workflow(ctx: Context, params: RestoreWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            pre_restore_backup, _ = await backup_workflow(client, params.workflow_id)
            backup_data = load_backup(params.backup_path)
            result = await client.update_workflow(params.workflow_id, workflow_update_payload(backup_data))
            return json.dumps({"success": True, "workflow_id": params.workflow_id, "workflow": result, "backup": pre_restore_backup, "restored_from": params.backup_path}, indent=2, default=str)
        except BackupError as exc:
            return f"Error restoring workflow: {exc}"
        except N8nClientError as exc:
            return f"Error restoring workflow: {exc}"

    @mcp.tool(name="n8n_create_workflow", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_create_workflow(ctx: Context, params: CreateWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            body: dict[str, Any] = {"name": params.name, "nodes": params.nodes, "connections": params.connections}
            if params.settings:
                body["settings"] = params.settings
            result = await client.create_workflow(body)
            return json.dumps({"success": True, "workflow": result}, indent=2, default=str)
        except N8nClientError as exc:
            return f"Error creating workflow: {exc}"

    @mcp.tool(name="n8n_update_workflow", annotations={"readOnlyHint": False, "idempotentHint": True})
    async def n8n_update_workflow(ctx: Context, params: UpdateWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            current = await client.get_workflow(params.workflow_id)
            body = workflow_update_payload(current)
            if params.name is not None:
                body["name"] = params.name
            if params.nodes is not None:
                body["nodes"] = params.nodes
            if params.connections is not None:
                body["connections"] = params.connections
            if params.settings is not None:
                body["settings"] = params.settings
            result = await client.update_workflow(params.workflow_id, body)
            return json.dumps({"success": True, "workflow": result, "backup": backup_path}, indent=2, default=str)
        except BackupError as exc:
            return f"Error updating workflow: backup failed, operation aborted. {exc}"
        except N8nClientError as exc:
            return f"Error updating workflow: {exc}"

    @requires_confirmation(param_name="confirm_delete", action_description="Delete workflow")
    @mcp.tool(name="n8n_delete_workflow", annotations={"readOnlyHint": False, "destructiveHint": True})
    async def n8n_delete_workflow(ctx: Context, params: DeleteWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            workflow_name = "Unknown"
            try:
                workflow_name = (await client.get_workflow(params.workflow_id)).get("name", workflow_name)
            except N8nClientError:
                pass
            if not params.confirm_delete:
                return json.dumps({
                    "error": "OPERACAO BLOQUEADA",
                    "message": "Delete de workflow requer confirmacao explicita. Chame novamente com confirm_delete=true para confirmar. Esta acao e IRREVERSIVEL.",
                    "workflow_id": params.workflow_id,
                    "workflow_name": workflow_name,
                    "blocked": True,
                }, indent=2)
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            await client.delete_workflow(params.workflow_id)
            return json.dumps({
                "deleted": True,
                "workflow_id": params.workflow_id,
                "backup": backup_path,
                "message": f"Workflow deletado. Backup salvo em {backup_path}. Use n8n_restore_workflow para restaurar se necessario.",
            }, indent=2)
        except BackupError as exc:
            return f"Error deleting workflow: backup failed, operation aborted. {exc}"
        except N8nClientError as exc:
            return f"Error deleting workflow: {exc}"

    @mcp.tool(name="n8n_activate_workflow", annotations={"readOnlyHint": False, "idempotentHint": True})
    async def n8n_activate_workflow(ctx: Context, params: WorkflowIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            result = await client.activate_workflow(params.workflow_id)
            return json.dumps({"success": True, "active": result.get("active", True), "id": params.workflow_id, "backup": backup_path})
        except BackupError as exc:
            return f"Error activating workflow: backup failed, operation aborted. {exc}"
        except N8nClientError as exc:
            return f"Error activating workflow: {exc}"

    @mcp.tool(name="n8n_deactivate_workflow", annotations={"readOnlyHint": False, "idempotentHint": True})
    async def n8n_deactivate_workflow(ctx: Context, params: WorkflowIdInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            result = await client.deactivate_workflow(params.workflow_id)
            return json.dumps({"success": True, "active": result.get("active", False), "id": params.workflow_id, "backup": backup_path})
        except BackupError as exc:
            return f"Error deactivating workflow: backup failed, operation aborted. {exc}"
        except N8nClientError as exc:
            return f"Error deactivating workflow: {exc}"
