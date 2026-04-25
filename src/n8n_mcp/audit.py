"""Local JSONL audit logging for the internal API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_audit_log_path() -> Path:
    """Return the configured audit log path, creating parent directories."""
    raw_path = os.environ.get("N8N_MCP_AUDIT_LOG", "./audit_logs/audit.jsonl")
    path = Path(raw_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_audit_event(action: str, **payload: Any) -> dict[str, Any]:
    """Append an audit event to JSONL and return the event."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        **payload,
    }
    path = get_audit_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")
    return event


def read_audit_events(limit: int = 100) -> list[dict[str, Any]]:
    """Read recent audit events from disk."""
    path = get_audit_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events
