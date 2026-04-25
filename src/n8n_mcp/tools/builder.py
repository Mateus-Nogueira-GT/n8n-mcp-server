"""MCP tools for building, validating, and patching n8n workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from n8n_mcp.analysis import extract_failed_node, get_execution_for_analysis, propose_changes_for_failure
from n8n_mcp.backup import BackupError, backup_workflow
from n8n_mcp.client import N8nClientError
from n8n_mcp.context import get_n8n_client
from n8n_mcp.workflow_utils import WorkflowPatchError, deep_merge, find_unique_node, workflow_update_payload

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

NODE_KEYWORD_MAP: dict[str, str] = {
    "webhook": "n8n-nodes-base.webhook",
    "cron": "n8n-nodes-base.scheduleTrigger",
    "schedule": "n8n-nodes-base.scheduleTrigger",
    "manual": "n8n-nodes-base.manualTrigger",
    "http": "n8n-nodes-base.httpRequest",
    "request": "n8n-nodes-base.httpRequest",
    "api": "n8n-nodes-base.httpRequest",
    "set": "n8n-nodes-base.set",
    "transform": "n8n-nodes-base.set",
    "code": "n8n-nodes-base.code",
    "if": "n8n-nodes-base.if",
    "condition": "n8n-nodes-base.if",
    "switch": "n8n-nodes-base.switch",
    "route": "n8n-nodes-base.switch",
    "respond": "n8n-nodes-base.respondToWebhook",
    "wait": "n8n-nodes-base.wait",
    "delay": "n8n-nodes-base.wait",
    "merge": "n8n-nodes-base.merge",
    "slack": "n8n-nodes-base.slack",
    "email": "n8n-nodes-base.emailSend",
}

NODE_DEFAULTS: dict[str, dict[str, Any]] = {
    "n8n-nodes-base.webhook": {"httpMethod": "POST", "path": "webhook", "responseMode": "responseNode"},
    "n8n-nodes-base.httpRequest": {"method": "GET", "url": "https://api.example.com"},
    "n8n-nodes-base.scheduleTrigger": {"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}},
    "n8n-nodes-base.manualTrigger": {},
    "n8n-nodes-base.set": {"mode": "manual", "duplicateItem": False, "assignments": {"assignments": []}},
    "n8n-nodes-base.if": {"conditions": {"options": {"caseSensitive": True, "leftValue": ""}, "conditions": []}},
    "n8n-nodes-base.switch": {"rules": {"values": []}},
    "n8n-nodes-base.respondToWebhook": {"respondWith": "json"},
    "n8n-nodes-base.code": {"jsCode": "// Add your code here\nreturn items;"},
    "n8n-nodes-base.wait": {"amount": 1, "unit": "seconds"},
}


def _resolve_node_type(keyword: str) -> str:
    kw = keyword.lower().strip()
    if kw in NODE_KEYWORD_MAP:
        return NODE_KEYWORD_MAP[kw]
    for key, node_type in NODE_KEYWORD_MAP.items():
        if key in kw or kw in key:
            return node_type
    return "n8n-nodes-base.httpRequest"


def _build_node(name: str, node_type: str, position: list[int], params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "type": node_type,
        "position": position,
        "parameters": {**NODE_DEFAULTS.get(node_type, {}), **(params or {})},
        "typeVersion": 1,
    }


def _build_connections(node_names: list[str]) -> dict[str, Any]:
    return {
        node_names[i]: {"main": [[{"node": node_names[i + 1], "type": "main", "index": 0}]]}
        for i in range(len(node_names) - 1)
    }


def _load_template(template_id: str) -> dict[str, Any] | None:
    path = TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _list_templates() -> list[dict[str, str]]:
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
    return templates


def _set_nested_field(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = target
    for part in parts[:-1]:
        nested = current.setdefault(part, {})
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = value


class BuildWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    description: str = Field(..., min_length=10, max_length=2000)
    name: str = Field(default="New Workflow", max_length=200)
    template_id: Optional[str] = None
    deploy: bool = False


class AddNodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    node_type: str
    node_name: str = Field(..., min_length=1, max_length=100)
    parameters: Optional[dict[str, Any]] = None
    connect_after: Optional[str] = None


class ValidateWorkflowInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: Optional[str] = None
    workflow_json: Optional[dict[str, Any]] = None


class ProposeFixInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    execution_id: Optional[str] = None
    apply: bool = False


class GetNodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    node_name: str = Field(..., min_length=1)


class UpdateNodeParametersInput(GetNodeInput):
    parameters: dict[str, Any]


class ReplaceNodeInput(GetNodeInput):
    new_node_json: dict[str, Any]


class UpdateConnectionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    workflow_id: str = Field(..., min_length=1)
    source_node: str = Field(..., min_length=1)
    target_node: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(add|remove)$")


def register_builder_tools(mcp: FastMCP) -> None:
    """Register builder and patch tools."""

    @mcp.tool(name="n8n_build_workflow", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_build_workflow(ctx: Context, params: BuildWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            if params.template_id:
                template = _load_template(params.template_id)
                if not template:
                    return f"Error: Template '{params.template_id}' not found."
                template["name"] = params.name
                template.pop("meta", None)
                if params.deploy:
                    return json.dumps({"success": True, "source": f"template:{params.template_id}", "workflow": await client.create_workflow(template)}, indent=2, default=str)
                return json.dumps({"source": f"template:{params.template_id}", "workflow": template}, indent=2)
            desc = params.description.lower()
            keywords = [kw for kw in NODE_KEYWORD_MAP if kw in desc] or ["manual", "code"]
            seen_types: set[str] = set()
            ordered: list[str] = []
            for kw in sorted(keywords, key=lambda item: desc.find(item)):
                node_type = _resolve_node_type(kw)
                if node_type not in seen_types:
                    seen_types.add(node_type)
                    ordered.append(kw)
            nodes = []
            names = []
            x_pos = 250
            for index, kw in enumerate(ordered):
                node_type = _resolve_node_type(kw)
                name = kw.replace("_", " ").title()
                if name in names:
                    name = f"{name} {index + 1}"
                nodes.append(_build_node(name, node_type, [x_pos, 300]))
                names.append(name)
                x_pos += 250
            workflow = {"name": params.name, "nodes": nodes, "connections": _build_connections(names)}
            if params.deploy:
                return json.dumps({"success": True, "source": "generated", "keywords_detected": ordered, "workflow": await client.create_workflow(workflow)}, indent=2, default=str)
            return json.dumps({"source": "generated", "keywords_detected": ordered, "workflow": workflow, "hint": "Review generated JSON before deploy."}, indent=2)
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_add_node", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_add_node(ctx: Context, params: AddNodeInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            workflow = await client.get_workflow(params.workflow_id)
            nodes = workflow.setdefault("nodes", [])
            connections = workflow.setdefault("connections", {})
            node_type = params.node_type if params.node_type.startswith(("n8n-nodes-", "@")) else _resolve_node_type(params.node_type)
            max_x = max((n.get("position", [0])[0] for n in nodes), default=0)
            nodes.append(_build_node(params.node_name, node_type, [max_x + 250, 300], params.parameters))
            if params.connect_after:
                old = connections.get(params.connect_after, {}).get("main", [[]])
                next_nodes = old[0] if old else []
                connections[params.connect_after] = {"main": [[{"node": params.node_name, "type": "main", "index": 0}]]}
                if next_nodes:
                    connections[params.node_name] = {"main": [next_nodes]}
            result = await client.update_workflow(params.workflow_id, workflow_update_payload(workflow))
            return json.dumps({"success": True, "workflow": result, "backup": backup_path}, indent=2, default=str)
        except BackupError as exc:
            return f"Error: backup failed, operation aborted. {exc}"
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_validate_workflow", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_validate_workflow(ctx: Context, params: ValidateWorkflowInput) -> str:
        client = get_n8n_client(ctx)
        try:
            workflow = await client.get_workflow(params.workflow_id) if params.workflow_id else params.workflow_json
            if not workflow:
                return "Error: Provide either workflow_id or workflow_json."
            nodes = workflow.get("nodes", [])
            connections = workflow.get("connections", {})
            issues: list[dict[str, str]] = []
            if not nodes:
                return json.dumps({"valid": False, "issues": [{"severity": "error", "message": "Workflow has no nodes."}]}, indent=2)
            node_names = {n.get("name", "") for n in nodes}
            trigger_types = {"webhook", "scheduleTrigger", "manualTrigger", "emailTrigger", "mcpTrigger"}
            if not any(any(t in n.get("type", "") for t in trigger_types) for n in nodes):
                issues.append({"severity": "warning", "message": "No trigger node found."})
            connected_sources: set[str] = set()
            connected_targets: set[str] = set()
            for source, data in connections.items():
                if source not in node_names:
                    issues.append({"severity": "error", "message": f"Connection source references non-existent node: '{source}'"})
                connected_sources.add(source)
                for group in data.get("main", []):
                    for conn in group:
                        target = conn.get("node", "")
                        connected_targets.add(target)
                        if target not in node_names:
                            issues.append({"severity": "error", "message": f"Connection references non-existent node: '{target}'"})
            for node in nodes:
                name = node.get("name", "")
                is_trigger = any(t in node.get("type", "") for t in trigger_types)
                if name not in connected_sources and name not in connected_targets and not is_trigger:
                    issues.append({"severity": "warning", "message": f"Node '{name}' is disconnected."})
            return json.dumps({"valid": not any(i["severity"] == "error" for i in issues), "node_count": len(nodes), "connection_count": len(connections), "issues": issues or "No issues found."}, indent=2)
        except N8nClientError as exc:
            return f"Error: {exc}"

    @mcp.tool(name="n8n_list_templates", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_list_templates() -> str:
        templates = _list_templates()
        by_category: dict[str, list[dict[str, str]]] = {}
        for template in templates:
            by_category.setdefault(template["category"], []).append(template)
        return json.dumps({"total": len(templates), "categories": by_category}, indent=2)

    @mcp.tool(name="n8n_propose_fix", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_propose_fix(ctx: Context, params: ProposeFixInput) -> str:
        client = get_n8n_client(ctx)
        try:
            workflow = await client.get_workflow(params.workflow_id)
            execution, _summary = await get_execution_for_analysis(client, params.workflow_id, params.execution_id)
            failed_node = None
            detected_error = "unknown"
            if execution:
                failed = extract_failed_node(execution)
                if failed:
                    failed_node = failed.get("node_name")
                    detected_error = failed.get("error_message") or "unknown"
            changes: list[dict[str, Any]] = []
            risk = "medium"
            apply_available = False
            if failed_node and detected_error != "unknown":
                changes, risk, apply_available = propose_changes_for_failure(workflow, failed_node, detected_error)
            if risk == "high":
                apply_available = False
            response: dict[str, Any] = {"workflow_id": params.workflow_id, "failed_node": failed_node, "detected_error": detected_error, "proposed_changes": changes, "risk": risk, "apply_available": apply_available}
            if not params.apply:
                return json.dumps(response, indent=2, default=str)
            if risk == "high":
                response.update({"applied": False, "message": "High-risk fixes require human intervention."})
                return json.dumps(response, indent=2, default=str)
            if not apply_available or not changes:
                response.update({"applied": False, "message": "No evidence-based automatic fix is available."})
                return json.dumps(response, indent=2, default=str)
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            for change in changes:
                node_name = change.get("node")
                field = change.get("field")
                if isinstance(node_name, str) and isinstance(field, str):
                    _index, node = find_unique_node(workflow, node_name)
                    _set_nested_field(node, field, change.get("to"))
            result = await client.update_workflow(params.workflow_id, workflow_update_payload(workflow))
            response.update({"applied": True, "backup": backup_path, "workflow": result})
            return json.dumps(response, indent=2, default=str)
        except BackupError as exc:
            return f"Error proposing fix: backup failed, operation aborted. {exc}"
        except (N8nClientError, WorkflowPatchError) as exc:
            return f"Error proposing fix: {exc}"

    @mcp.tool(name="n8n_get_node", annotations={"readOnlyHint": True, "idempotentHint": True})
    async def n8n_get_node(ctx: Context, params: GetNodeInput) -> str:
        client = get_n8n_client(ctx)
        try:
            workflow = await client.get_workflow(params.workflow_id)
            _index, node = find_unique_node(workflow, params.node_name)
            return json.dumps({"workflow_id": params.workflow_id, "node": node}, indent=2, default=str)
        except (N8nClientError, WorkflowPatchError) as exc:
            return f"Error getting node: {exc}"

    @mcp.tool(name="n8n_update_node_parameters", annotations={"readOnlyHint": False, "idempotentHint": True})
    async def n8n_update_node_parameters(ctx: Context, params: UpdateNodeParametersInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            workflow = await client.get_workflow(params.workflow_id)
            _index, node = find_unique_node(workflow, params.node_name)
            current = node.get("parameters", {})
            node["parameters"] = deep_merge(current if isinstance(current, dict) else {}, params.parameters)
            result = await client.update_workflow(params.workflow_id, workflow_update_payload(workflow))
            return json.dumps({"success": True, "workflow_id": params.workflow_id, "node": node, "workflow": result, "backup": backup_path}, indent=2, default=str)
        except BackupError as exc:
            return f"Error updating node parameters: backup failed, operation aborted. {exc}"
        except (N8nClientError, WorkflowPatchError) as exc:
            return f"Error updating node parameters: {exc}"

    @mcp.tool(name="n8n_replace_node", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_replace_node(ctx: Context, params: ReplaceNodeInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            workflow = await client.get_workflow(params.workflow_id)
            index, _old = find_unique_node(workflow, params.node_name)
            replacement = dict(params.new_node_json)
            replacement["name"] = params.node_name
            workflow["nodes"][index] = replacement
            result = await client.update_workflow(params.workflow_id, workflow_update_payload(workflow))
            return json.dumps({"success": True, "workflow_id": params.workflow_id, "node": replacement, "workflow": result, "backup": backup_path}, indent=2, default=str)
        except BackupError as exc:
            return f"Error replacing node: backup failed, operation aborted. {exc}"
        except (N8nClientError, WorkflowPatchError) as exc:
            return f"Error replacing node: {exc}"

    @mcp.tool(name="n8n_update_connections", annotations={"readOnlyHint": False, "idempotentHint": False})
    async def n8n_update_connections(ctx: Context, params: UpdateConnectionsInput) -> str:
        client = get_n8n_client(ctx)
        try:
            backup_path, _ = await backup_workflow(client, params.workflow_id)
            workflow = await client.get_workflow(params.workflow_id)
            find_unique_node(workflow, params.source_node)
            find_unique_node(workflow, params.target_node)
            connections = workflow.setdefault("connections", {})
            source = connections.setdefault(params.source_node, {"main": [[]]})
            main_outputs = source.setdefault("main", [[]])
            if not main_outputs:
                main_outputs.append([])
            first_output = main_outputs[0]
            if params.action == "add":
                if not any(conn.get("node") == params.target_node for conn in first_output):
                    first_output.append({"node": params.target_node, "type": "main", "index": 0})
            else:
                main_outputs[0] = [conn for conn in first_output if conn.get("node") != params.target_node]
                if not main_outputs[0] and len(main_outputs) == 1:
                    connections.pop(params.source_node, None)
            result = await client.update_workflow(params.workflow_id, workflow_update_payload(workflow))
            return json.dumps({"success": True, "workflow_id": params.workflow_id, "connections": workflow.get("connections", {}), "workflow": result, "backup": backup_path}, indent=2, default=str)
        except BackupError as exc:
            return f"Error updating connections: backup failed, operation aborted. {exc}"
        except (N8nClientError, WorkflowPatchError) as exc:
            return f"Error updating connections: {exc}"
