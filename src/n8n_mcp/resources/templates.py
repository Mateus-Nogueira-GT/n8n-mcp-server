"""MCP resources for n8n workflow templates."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def register_template_resources(mcp: FastMCP) -> None:
    """Register template resources."""

    @mcp.resource("n8n://templates")
    async def templates_list() -> str:
        templates = []
        for path in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                templates.append({
                    "id": path.stem,
                    "name": meta.get("name", path.stem),
                    "description": meta.get("description", ""),
                    "category": meta.get("category", "general"),
                })
            except (json.JSONDecodeError, OSError):
                continue
        by_category: dict[str, list[dict[str, str]]] = {}
        for template in templates:
            by_category.setdefault(template["category"], []).append(template)
        return json.dumps({"total": len(templates), "categories": by_category}, indent=2)

    @mcp.resource("n8n://templates/{template_id}")
    async def template_detail(template_id: str) -> str:
        path = TEMPLATES_DIR / f"{template_id}.json"
        if not path.exists():
            return json.dumps({"error": f"Template '{template_id}' not found."})
        return json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2)

