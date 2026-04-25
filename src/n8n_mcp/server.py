"""n8n MCP Server - main entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from n8n_mcp.client import N8nClient
from n8n_mcp.resources.nodes import register_node_resources
from n8n_mcp.resources.templates import register_template_resources
from n8n_mcp.resources.workflows import register_workflow_resources
from n8n_mcp.tools.builder import register_builder_tools
from n8n_mcp.tools.diagnostics import register_diagnostic_tools
from n8n_mcp.tools.executions import register_execution_tools
from n8n_mcp.tools.workflows import register_workflow_tools


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage the single n8n API client lifecycle."""
    client = N8nClient()
    try:
        yield {"n8n_client": client}
    finally:
        await client.close()


mcp = FastMCP(
    "n8n_mcp",
    instructions=(
        "MCP server for managing n8n workflows. "
        "Use n8n_list_workflows to see workflows. "
        "Use n8n_analyze_workflow_failure to analyze failures. "
        "Use n8n_propose_fix for dry-run repair proposals before applying changes."
    ),
    lifespan=app_lifespan,
)

register_workflow_tools(mcp)
register_execution_tools(mcp)
register_builder_tools(mcp)
register_diagnostic_tools(mcp)

register_node_resources(mcp)
register_template_resources(mcp)
register_workflow_resources(mcp)


def main() -> None:
    """Run the MCP server via stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
