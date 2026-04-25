"""Failure analysis and fix proposal helpers."""

from __future__ import annotations

from typing import Any

from n8n_mcp.client import N8nClient


def extract_failed_node(execution_data: dict[str, Any]) -> dict[str, Any] | None:
    data = execution_data.get("data", {})
    result_data = data.get("resultData", data.get("data", {}).get("resultData", {}))

    for node_name, node_runs in result_data.get("runData", {}).items():
        for run in node_runs:
            if run.get("error"):
                error = run["error"]
                return {
                    "node_name": node_name,
                    "error_message": error.get("message", str(error)),
                    "error_description": error.get("description", ""),
                    "error_stack": error.get("stack", ""),
                    "input_data": run.get("inputData", {}),
                }

    error = result_data.get("error", data.get("resultData", {}).get("error"))
    if error:
        return {
            "node_name": error.get("node", "Unknown"),
            "error_message": error.get("message", str(error)),
            "error_description": error.get("description", ""),
            "error_stack": error.get("stack", ""),
            "input_data": {},
        }
    return None


async def get_execution_for_analysis(
    client: N8nClient,
    workflow_id: str,
    execution_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if execution_id:
        return await client.get_execution(execution_id, include_data=True), {"id": execution_id}
    data = await client.list_executions(workflow_id=workflow_id, status="error", limit=1)
    executions = data.get("data", [])
    if not executions:
        return None, None
    summary = executions[0]
    return await client.get_execution(str(summary.get("id")), include_data=True), summary


def classify_failure(error_message: str, node_type: str = "") -> dict[str, Any]:
    msg = error_message.lower()
    if any(p in msg for p in ("credential", "401", "unauthorized", "forbidden", "403", "permission")):
        return {
            "probable_cause": "Credential or permission failure detected for this node.",
            "severity": "high",
            "auto_fixable": False,
            "recommended_action": "Update or re-authorize the credential manually in n8n.",
            "requires_human": True,
            "human_reason": "Credential and permission issues require manual validation in n8n.",
        }
    if any(p in msg for p in ("ssl", "certificate", "cert")):
        return {
            "probable_cause": "The request failed because of an SSL or certificate issue.",
            "severity": "high",
            "auto_fixable": False,
            "recommended_action": "Inspect the endpoint certificate and node SSL configuration.",
            "requires_human": True,
            "human_reason": "SSL changes can affect security and require human review.",
        }
    if "timeout" in msg or "timed out" in msg:
        return {
            "probable_cause": "The external endpoint is taking longer than the configured timeout.",
            "severity": "low",
            "auto_fixable": True,
            "recommended_action": "Increase the request timeout to 90000ms.",
            "requires_human": False,
            "human_reason": None,
        }
    if "429" in msg or "rate limit" in msg:
        return {
            "probable_cause": "The external service is rate limiting requests.",
            "severity": "low",
            "auto_fixable": True,
            "recommended_action": "Enable retry configuration or add delay before retrying.",
            "requires_human": False,
            "human_reason": None,
        }
    if "retry" in msg and ("exhausted" in msg or "failed" in msg):
        return {
            "probable_cause": "The node exhausted retry attempts before succeeding.",
            "severity": "low",
            "auto_fixable": True,
            "recommended_action": "Increase retry count or delay between retries.",
            "requires_human": False,
            "human_reason": None,
        }
    if any(p in msg for p in ("404", "not found", "invalid url", "enotfound", "econnrefused")):
        return {
            "probable_cause": "The target URL or resource appears to be unavailable or invalid.",
            "severity": "medium",
            "auto_fixable": False,
            "recommended_action": "Review the URL, endpoint, hostname, and resource identifiers.",
            "requires_human": True,
            "human_reason": "URL or resource fixes often depend on business context.",
        }
    if any(p in msg for p in ("invalid json", "payload", "schema", "node does not exist", "unknown node")):
        severity = "critical" if any(p in msg for p in ("schema", "node does not exist", "unknown node")) else "medium"
        return {
            "probable_cause": "The node data, payload, or workflow schema is invalid.",
            "severity": severity,
            "auto_fixable": False,
            "recommended_action": "Review the node schema and input payload manually.",
            "requires_human": True,
            "human_reason": "Schema and payload fixes need manual validation.",
        }
    return {
        "probable_cause": "Causa nao determinada automaticamente. Requer analise manual.",
        "severity": "medium",
        "auto_fixable": False,
        "recommended_action": "Review the execution error and node configuration manually.",
        "requires_human": True,
        "human_reason": "The failure pattern is not specific enough for a safe automatic fix.",
    }


def propose_changes_for_failure(
    workflow: dict[str, Any],
    failed_node: str,
    error_message: str,
) -> tuple[list[dict[str, Any]], str, bool]:
    msg = error_message.lower()
    node = next((n for n in workflow.get("nodes", []) if n.get("name") == failed_node), None)
    if not node:
        return [], "high", False
    params = node.get("parameters", {})
    if any(p in msg for p in ("credential", "401", "403", "permission")):
        return [], "high", False
    if "timeout" in msg or "timed out" in msg:
        current = params.get("timeout", params.get("requestTimeout", 30000))
        target = 90000 if isinstance(current, int) and current < 90000 else current
        if target == current:
            return [], "low", False
        return [{
            "node": failed_node,
            "field": "parameters.timeout",
            "from": current,
            "to": target,
            "reason": "Latest failed execution timed out.",
        }], "low", True
    if "429" in msg or "rate limit" in msg:
        return [{
            "node": failed_node,
            "field": "parameters.retryOnFail",
            "from": params.get("retryOnFail", False),
            "to": True,
            "reason": "Latest failed execution indicates rate limiting.",
        }], "low", True
    return [], "medium", False
