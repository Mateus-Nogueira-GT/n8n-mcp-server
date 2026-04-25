"""n8n REST API client using httpx."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx


def _load_dotenv() -> None:
    """Load simple KEY=VALUE pairs from .env without overriding real env vars."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class N8nClientError(Exception):
    """Raised when an n8n API call fails."""


class N8nClient:
    """Async HTTP client for the n8n REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        _load_dotenv()
        self.base_url = (base_url or os.environ.get("N8N_URL", "http://localhost:5678")).rstrip("/")
        self.api_key = api_key or os.environ.get("N8N_API_KEY", "")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/api/v1",
                headers={"X-N8N-API-KEY": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._get_client()
        try:
            resp = await client.request(method, path, params=params, json=json_body)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {"success": True}
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
                msg = body.get("message", exc.response.text)
            except Exception:
                msg = exc.response.text
            raise N8nClientError(f"n8n API error {status}: {msg}") from exc
        except httpx.TimeoutException as exc:
            raise N8nClientError("n8n API request timed out. Check N8N_URL and connectivity.") from exc
        except httpx.ConnectError as exc:
            raise N8nClientError(f"Cannot connect to n8n at {self.base_url}. Is n8n running?") from exc

    async def list_workflows(
        self,
        *,
        active: bool | None = None,
        tags: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if active is not None:
            params["active"] = str(active).lower()
        if tags:
            params["tags"] = tags
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/workflows", params=params)

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/workflows/{workflow_id}")

    async def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/workflows", json_body=data)

    async def update_workflow(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", f"/workflows/{workflow_id}", json_body=data)

    async def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/workflows/{workflow_id}")

    async def activate_workflow(self, workflow_id: str) -> dict[str, Any]:
        return await self._request("PATCH", f"/workflows/{workflow_id}/activate")

    async def deactivate_workflow(self, workflow_id: str) -> dict[str, Any]:
        return await self._request("PATCH", f"/workflows/{workflow_id}/deactivate")

    async def list_executions(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/executions", params=params)

    async def get_execution(self, execution_id: str, *, include_data: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if include_data:
            params["includeData"] = "true"
        return await self._request("GET", f"/executions/{execution_id}", params=params)

    async def retry_execution(self, execution_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/executions/{execution_id}/retry")

    async def delete_execution(self, execution_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/executions/{execution_id}")

    async def list_credentials(self, *, type_filter: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if type_filter:
            params["type"] = type_filter
        return await self._request("GET", "/credentials", params=params)

    async def list_tags(self) -> dict[str, Any]:
        return await self._request("GET", "/tags")

    async def execute_workflow(self, workflow_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if data:
            body["data"] = data
        return await self._request("POST", f"/workflows/{workflow_id}/run", json_body=body)
