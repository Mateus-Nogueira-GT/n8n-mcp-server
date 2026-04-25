"""Local workflow backup helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from n8n_mcp.client import N8nClient


class BackupError(Exception):
    """Raised when a workflow backup cannot be created or read."""


def get_backup_dir() -> Path:
    raw_path = os.environ.get("N8N_MCP_BACKUP_DIR", "./backups")
    backup_dir = Path(raw_path).expanduser()
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


async def backup_workflow(client: N8nClient, workflow_id: str) -> tuple[str, str]:
    timestamp = backup_timestamp()
    try:
        workflow = await client.get_workflow(workflow_id)
        backup_path = get_backup_dir() / f"{workflow_id}_{timestamp}.json"
        backup_path.write_text(json.dumps(workflow, indent=2, default=str), encoding="utf-8")
        return str(backup_path), timestamp
    except Exception as exc:
        raise BackupError(f"Failed to backup workflow {workflow_id}: {exc}") from exc


def load_backup(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except Exception as exc:
        raise BackupError(f"Failed to read backup file '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise BackupError(f"Backup file '{path}' does not contain a workflow object.")
    return data

