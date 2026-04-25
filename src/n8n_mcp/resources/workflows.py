"""MCP resources for n8n workflow summaries."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from n8n_mcp.client import N8nClientError
from n8n_mcp.context import get_n8n_client


def register_workflow_resources(mcp: FastMCP) -> None:
    """Register workflow summary resources."""

    @mcp.resource("n8n://workflows/summary")
    async def workflows_summary() -> str:
        ctx = mcp.get_context()
        client = get_n8n_client(ctx)
        try:
            data = await client.list_workflows(limit=250)
            summary = []
            for wf in data.get("data", []):
                summary.append({
                    "id": wf.get("id"),
                    "name": wf.get("name"),
                    "active": wf.get("active"),
                    "tags": [t.get("name", "") for t in wf.get("tags", [])],
                    "createdAt": wf.get("createdAt"),
                    "updatedAt": wf.get("updatedAt"),
                })
            return json.dumps({
                "total": len(summary),
                "active": sum(1 for w in summary if w["active"]),
                "inactive": sum(1 for w in summary if not w["active"]),
                "workflows": summary,
            }, indent=2)
        except N8nClientError as exc:
            return json.dumps({"error": str(exc)})
