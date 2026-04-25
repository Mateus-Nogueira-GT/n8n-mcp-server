"""MCP resources for n8n node catalog."""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

_node_cache: dict[str, Any] = {}
_cache_time: float = 0.0
CACHE_TTL = 3600

BUILTIN_NODES: list[dict[str, str]] = [
    {"type": "n8n-nodes-base.webhook", "name": "Webhook", "category": "Triggers", "description": "Starts workflow via HTTP webhook"},
    {"type": "n8n-nodes-base.scheduleTrigger", "name": "Schedule Trigger", "category": "Triggers", "description": "Starts workflow on a schedule"},
    {"type": "n8n-nodes-base.manualTrigger", "name": "Manual Trigger", "category": "Triggers", "description": "Starts workflow manually"},
    {"type": "n8n-nodes-base.httpRequest", "name": "HTTP Request", "category": "Network", "description": "Make HTTP requests to any API"},
    {"type": "n8n-nodes-base.respondToWebhook", "name": "Respond to Webhook", "category": "Network", "description": "Send response to webhook caller"},
    {"type": "n8n-nodes-base.set", "name": "Set", "category": "Data", "description": "Set or modify item fields"},
    {"type": "n8n-nodes-base.code", "name": "Code", "category": "Data", "description": "Run custom code"},
    {"type": "n8n-nodes-base.if", "name": "IF", "category": "Logic", "description": "Conditional branching"},
    {"type": "n8n-nodes-base.switch", "name": "Switch", "category": "Logic", "description": "Route items to different outputs"},
    {"type": "n8n-nodes-base.wait", "name": "Wait", "category": "Logic", "description": "Pause execution"},
    {"type": "n8n-nodes-base.merge", "name": "Merge", "category": "Logic", "description": "Merge multiple inputs"},
    {"type": "n8n-nodes-base.slack", "name": "Slack", "category": "Communication", "description": "Interact with Slack"},
    {"type": "n8n-nodes-base.telegram", "name": "Telegram", "category": "Communication", "description": "Send Telegram messages"},
    {"type": "n8n-nodes-base.postgres", "name": "PostgreSQL", "category": "Database", "description": "Query PostgreSQL databases"},
    {"type": "n8n-nodes-base.googleSheets", "name": "Google Sheets", "category": "Productivity", "description": "Read/write Google Sheets"},
    {"type": "n8n-nodes-base.openAi", "name": "OpenAI", "category": "AI", "description": "Call OpenAI APIs"},
    {"type": "@n8n/n8n-nodes-langchain.agent", "name": "AI Agent", "category": "AI", "description": "AI agent with tools"},
]


def register_node_resources(mcp: FastMCP) -> None:
    """Register node catalog resources."""

    @mcp.resource("n8n://nodes/catalog")
    async def nodes_catalog() -> str:
        global _node_cache, _cache_time
        if _node_cache and (time.time() - _cache_time) < CACHE_TTL:
            return json.dumps(_node_cache, indent=2)
        by_category: dict[str, list[dict[str, str]]] = {}
        for node in BUILTIN_NODES:
            by_category.setdefault(node["category"], []).append({
                "type": node["type"],
                "name": node["name"],
                "description": node["description"],
            })
        result = {"total": len(BUILTIN_NODES), "categories": by_category}
        _node_cache = result
        _cache_time = time.time()
        return json.dumps(result, indent=2)

    @mcp.resource("n8n://nodes/{node_type}")
    async def node_details(node_type: str) -> str:
        for node in BUILTIN_NODES:
            if node["type"] == node_type:
                return json.dumps(node, indent=2)
        return json.dumps({"error": f"Node type '{node_type}' not found in catalog."})

