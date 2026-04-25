"""MCP tools for action-oriented n8n workflow failure analysis."""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from n8n_mcp.analysis import classify_failure, extract_failed_node, get_execution_for_analysis
from n8n_mcp.client import N8nClientError
from n8n_mcp.context import get_n8n_client


class AnalyzeWorkflowFailureInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    execution_id: Optional[str] = None


def _execution_time(full_execution: dict[str, Any], summary: dict[str, Any] | None) -> str | None:
    if summary:
        for key in ("startedAt", "stoppedAt", "createdAt"):
            if summary.get(key):
                return summary.get(key)
    for key in ("startedAt", "stoppedAt", "createdAt"):
        if full_execution.get(key):
            return full_execution.get(key)
    data = full_execution.get("data", {})
    if isinstance(data, dict):
        for key in ("startedAt", "stoppedAt", "createdAt"):
            if data.get(key):
                return data.get(key)
    return None


def register_diagnostic_tools(mcp: FastMCP) -> None:
    """Register diagnostic tools."""

    @mcp.tool(name="n8n_analyze_workflow_failure", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_analyze_workflow_failure(ctx: Context, params: AnalyzeWorkflowFailureInput) -> str:
        client = get_n8n_client(ctx)
        try:
            workflow = await client.get_workflow(params.workflow_id)
            workflow_name = workflow.get("name", "Unknown")
            execution, summary = await get_execution_for_analysis(client, params.workflow_id, params.execution_id)
            if execution is None:
                return json.dumps({
                    "workflow_id": params.workflow_id,
                    "workflow_name": workflow_name,
                    "message": "No failed execution found for this workflow.",
                    "failure_analysis": None,
                    "proposed_fix": None,
                }, indent=2)
            failed = extract_failed_node(execution)
            if failed is None:
                return json.dumps({
                    "workflow_id": params.workflow_id,
                    "workflow_name": workflow_name,
                    "execution_id": params.execution_id or (summary or {}).get("id"),
                    "execution_time": _execution_time(execution, summary),
                    "message": "Execution was fetched, but no failed node could be identified automatically.",
                    "failure_analysis": {
                        "failed_node": None,
                        "node_type": None,
                        "error_message": "unknown",
                        "probable_cause": "Causa nao determinada automaticamente. Requer analise manual.",
                        "severity": "medium",
                        "auto_fixable": False,
                        "recommended_action": "Review the execution data manually.",
                        "requires_human": True,
                        "human_reason": "The failed node could not be identified from execution data.",
                    },
                    "proposed_fix": None,
                }, indent=2)
            node_types = {node.get("name", ""): node.get("type", "") for node in workflow.get("nodes", [])}
            failed_node = failed.get("node_name")
            node_type = node_types.get(failed_node, "unknown")
            error_message = failed.get("error_message", "unknown")
            classification = classify_failure(error_message, node_type)
            proposed_fix = None
            if classification["auto_fixable"]:
                proposed_fix = {
                    "tool": "n8n_propose_fix",
                    "params": {
                        "workflow_id": params.workflow_id,
                        "execution_id": params.execution_id or (summary or {}).get("id"),
                    },
                }
            return json.dumps({
                "workflow_id": params.workflow_id,
                "workflow_name": workflow_name,
                "execution_id": params.execution_id or (summary or {}).get("id"),
                "execution_time": _execution_time(execution, summary),
                "failure_analysis": {
                    "failed_node": failed_node,
                    "node_type": node_type,
                    "error_message": error_message,
                    "probable_cause": classification["probable_cause"],
                    "severity": classification["severity"],
                    "auto_fixable": classification["auto_fixable"],
                    "recommended_action": classification["recommended_action"],
                    "requires_human": classification["requires_human"],
                    "human_reason": classification["human_reason"],
                },
                "proposed_fix": proposed_fix,
            }, indent=2, default=str)
        except N8nClientError as exc:
            return f"Error analyzing workflow failure: {exc}"
