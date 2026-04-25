"""Workflow JSON manipulation helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class WorkflowPatchError(Exception):
    """Raised when a granular workflow patch cannot be applied."""


def find_unique_node(workflow: dict[str, Any], node_name: str) -> tuple[int, dict[str, Any]]:
    matches = [
        (index, node)
        for index, node in enumerate(workflow.get("nodes", []))
        if node.get("name") == node_name
    ]
    if not matches:
        raise WorkflowPatchError(f"Node '{node_name}' was not found in workflow.")
    if len(matches) > 1:
        raise WorkflowPatchError(f"Node name '{node_name}' is ambiguous. Use a unique node name.")
    return matches[0]


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def workflow_update_payload(workflow: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key in ("name", "nodes", "connections", "settings", "tags"):
        if key in workflow:
            body[key] = workflow[key]
    return body

