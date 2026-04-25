"""Helpers for accessing MCP lifespan state."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from n8n_mcp.client import N8nClient


def get_n8n_client(ctx: Context) -> N8nClient:
    """Return the single n8n client created by the MCP lifespan."""
    lifespan_context: Any = ctx.request_context.lifespan_context
    if isinstance(lifespan_context, dict):
        client = lifespan_context.get("n8n_client")
    else:
        client = getattr(lifespan_context, "n8n_client", None)

    if not isinstance(client, N8nClient):
        raise RuntimeError("n8n client is not available in MCP lifespan context.")
    return client

