"""Shared use cases for MCP tools and the FastAPI MVP."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from n8n_mcp.analysis import classify_failure, extract_failed_node, get_execution_for_analysis, propose_changes_for_failure
from n8n_mcp.audit import append_audit_event
from n8n_mcp.backup import backup_workflow, get_backup_dir, load_backup
from n8n_mcp.client import N8nClient
from n8n_mcp.workflow_utils import find_unique_node, workflow_update_payload


LOW_RISK = "low"

CLIENT_ALIASES = {
    "ACADI-TI": ("ACADI-TI", "ACADI TI", "ACADI"),
    "PROTEFORT": ("PROTEFORT",),
    "VIOTTO": ("VIOTTO",),
    "LIRA ADVOCACIA": ("LIRA ADVOCACIA", "LIRA"),
    "VOLCAN": ("VOLCAN",),
    "SHARKS": ("SHARKS",),
    "VIDA NOVA": ("VIDA NOVA",),
    "IMPACTO MILIONÁRIO": ("IMPACTO MILIONARIO", "IMPACTO MILIONÁRIO"),
    "KAIO": ("KAIO",),
    "SMI CONTABILIDADE": ("SMI CONTABILIDADE", "SMI"),
    "MAIS GESTÃO CONTÁBIL": ("MAIS GESTAO CONTABIL", "MAIS GESTÃO CONTÁBIL"),
    "ALIMENTE REFS": ("ALIMENTE REFS",),
    "VAGAS AGORA": ("VAGAS AGORA",),
    "ANÁPOLIS SEGUROS": ("ANAPOLIS SEGUROS", "ANÁPOLIS SEGUROS"),
    "HDL": ("HDL",),
    "GOBBO": ("GOBBO",),
    "GUSTAVO": ("GUSTAVO",),
    "PROF BETO": ("PROF BETO",),
    "ADILIO JEANS": ("ADILIO JEANS", "ADÍLIO JEANS"),
    "CAMILA ADVOCACIA": ("CAMILA ADVOCACIA",),
    "CARLA NUTRIÇÃO": ("CARLA NUTRICAO", "CARLA NUTRIÇÃO"),
    "BITE AI": ("BITE AI", "BITEAI"),
}


class ServiceError(Exception):
    """Raised when a service operation cannot be completed safely."""


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


async def list_workflows(client: N8nClient, *, limit: int = 100) -> dict[str, Any]:
    raw_workflows = await _list_all_workflows(client, limit=limit)
    folder_map = load_folder_map()
    workflows = []
    for workflow in raw_workflows:
        folder = _workflow_folder_info(workflow, folder_map)
        group = _workflow_group_info(workflow, folder)
        workflows.append({
            "id": workflow.get("id"),
            "name": workflow.get("name"),
            "active": workflow.get("active"),
            "isArchived": workflow.get("isArchived"),
            "updatedAt": workflow.get("updatedAt"),
            "createdAt": workflow.get("createdAt"),
            "tags": [tag.get("name", "") for tag in workflow.get("tags", [])],
            "folder": folder,
            "folder_id": folder["id"],
            "folder_name": folder["name"],
            "group": group,
            "category_id": group["category_id"],
            "category_name": group["category_name"],
            "subgroup_id": group["subgroup_id"],
            "subgroup_name": group["subgroup_name"],
        })
    return {"total": len(workflows), "workflows": workflows}


async def _list_all_workflows(client: N8nClient, *, limit: int) -> list[dict[str, Any]]:
    """Fetch workflows across n8n cursor pages up to the requested limit."""
    workflows: list[dict[str, Any]] = []
    cursor: str | None = None
    page_size = min(max(limit, 1), 250)

    while len(workflows) < limit:
        remaining = limit - len(workflows)
        data = await client.list_workflows(limit=min(page_size, remaining), cursor=cursor)
        page = data.get("data", [])
        if not isinstance(page, list) or not page:
            break
        workflows.extend(item for item in page if isinstance(item, dict))
        cursor = data.get("nextCursor")
        if not cursor:
            break

    return workflows


def load_folder_map() -> dict[str, str]:
    """Load optional local workflow_id -> folder_name mapping."""
    path = Path(os.environ.get("N8N_MCP_FOLDER_MAP", "./workflow_folders.json")).expanduser()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    mapping: dict[str, str] = {}
    workflows = raw.get("workflows")
    if isinstance(workflows, dict):
        for workflow_id, folder_name in workflows.items():
            if isinstance(folder_name, str) and folder_name.strip():
                mapping[str(workflow_id)] = folder_name.strip()

    folders = raw.get("folders")
    if isinstance(folders, dict):
        for folder_name, workflow_ids in folders.items():
            if not isinstance(folder_name, str) or not isinstance(workflow_ids, list):
                continue
            for workflow_id in workflow_ids:
                mapping[str(workflow_id)] = folder_name.strip()

    return mapping


def _workflow_folder_info(workflow: dict[str, Any], folder_map: dict[str, str] | None = None) -> dict[str, str]:
    """Infer a display folder/project for a workflow from n8n API metadata."""
    workflow_id = str(workflow.get("id") or "")
    if folder_map and workflow_id in folder_map:
        name = folder_map[workflow_id]
        return {"id": f"manual:{name}", "name": name, "source": "manual"}

    for key in ("folder", "parentFolder"):
        value = workflow.get(key)
        if isinstance(value, dict):
            raw_id = value.get("id") or value.get("projectId") or value.get("folderId")
            raw_name = value.get("name") or value.get("title")
            if raw_id or raw_name:
                folder_id = str(raw_id or raw_name)
                return {"id": folder_id, "name": str(raw_name or f"Folder {folder_id[:8]}"), "source": key}

    for key in ("folderId", "parentFolderId"):
        value = workflow.get(key)
        if value:
            folder_id = str(value)
            return {"id": folder_id, "name": f"Folder {folder_id[:8]}", "source": key}

    if workflow.get("isArchived"):
        return {"id": "archived", "name": "Arquivados", "source": "archive"}

    inferred = _infer_folder_from_name(str(workflow.get("name") or ""))
    if inferred:
        return {"id": f"name:{inferred}", "name": inferred, "source": "name"}

    tags = workflow.get("tags", [])
    if isinstance(tags, list) and tags:
        first_tag = tags[0]
        if isinstance(first_tag, dict) and first_tag.get("name"):
            tag_name = str(first_tag["name"])
            return {"id": f"tag:{tag_name}", "name": tag_name, "source": "tag"}

    if os.environ.get("N8N_MCP_USE_PROJECT_AS_FOLDER", "").lower() == "true":
        shared = workflow.get("shared", [])
        if isinstance(shared, list):
            for item in shared:
                if isinstance(item, dict) and item.get("projectId"):
                    folder_id = str(item["projectId"])
                    return {"id": folder_id, "name": f"Project {folder_id[:8]}", "source": "projectId"}

    return {"id": "unmapped", "name": "Sem pasta / não mapeados", "source": "fallback"}


def _workflow_group_info(workflow: dict[str, Any], folder: dict[str, str]) -> dict[str, str]:
    """Classify workflows into operational buckets for the internal UI."""
    name = str(workflow.get("name") or "")
    text = _searchable_text(name)

    if workflow.get("isArchived"):
        return _group("archived", "Arquivados", "archived", "Arquivados", folder["source"])

    technical_subgroup = _technical_subgroup(text)
    if technical_subgroup:
        return _group(
            "internal",
            "Operação interna",
            f"internal:{_slug(technical_subgroup)}",
            technical_subgroup,
            "technical-rule",
        )

    client = _client_from_text(text)
    if client:
        return _group("clients", "Clientes", f"client:{_slug(client)}", client, "client-rule")

    if folder["source"] in {"manual", "folder", "parentFolder", "tag"} and folder["id"] not in {"unmapped", "archived"}:
        return _group("clients", "Clientes", f"client:{_slug(folder['name'])}", folder["name"], folder["source"])

    if folder["source"] == "name" and not _is_low_value_folder_candidate(folder["name"]):
        return _group(
            "potential-clients",
            "Possíveis clientes",
            f"potential:{_slug(folder['name'])}",
            folder["name"],
            "name",
        )

    return _group("unclassified", "Sem classificação", "unclassified", "Revisar manualmente", "fallback")


def _group(category_id: str, category_name: str, subgroup_id: str, subgroup_name: str, source: str) -> dict[str, str]:
    return {
        "category_id": category_id,
        "category_name": category_name,
        "subgroup_id": subgroup_id,
        "subgroup_name": subgroup_name,
        "source": source,
    }


def _technical_subgroup(text: str) -> str | None:
    if "AVISO DE ERRO" in text or "ERROR WORKFLOW" in text or "ERRO" in text and "AVISO" in text:
        return "Avisos de erro"
    if "SUB WORKFLOW" in text or "SUB-WORKFLOW" in text:
        return "Sub-workflows"
    if "TOOL " in text or text.startswith("TOOL") or " AGENDAMENTO" in text:
        return "Tools e agendamentos"
    if "MODELO" in text or "TESTE" in text or "COPY" in text or "PROTOTIPO" in text:
        return "Testes e modelos"
    if "DASHBOARD" in text or "CALENDLY" in text or "CHATWOOT" in text:
        return "Integrações internas"
    return None


def _client_from_text(text: str) -> str | None:
    for client, aliases in CLIENT_ALIASES.items():
        for alias in aliases:
            if _contains_tokenish(text, _searchable_text(alias)):
                return client
    return None


def _contains_tokenish(text: str, needle: str) -> bool:
    pattern = rf"(^|[^A-Z0-9]){re.escape(needle)}([^A-Z0-9]|$)"
    return re.search(pattern, text) is not None


def _searchable_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_text.upper().replace("|", " ").replace("[", " ").replace("]", " ").split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _searchable_text(value).lower()).strip("-") or "item"


def _infer_folder_from_name(name: str) -> str | None:
    """Best-effort visual grouping when n8n folders are not exposed by API."""
    cleaned = " ".join(name.split())
    if not cleaned:
        return None

    lower = cleaned.lower()
    if "sub-workflow" in lower:
        return "Sub-workflows"
    if "aviso de erro" in lower or "aviso de erros" in lower:
        return "Avisos de erro"

    bracketed = [part.strip() for part in cleaned.replace("][", "] [").split("[") if "]" in part]
    bracketed = [part.split("]", 1)[0].strip() for part in bracketed]
    for candidate in reversed(bracketed):
        normalized = _normalize_folder_candidate(candidate)
        if normalized and not _is_low_value_folder_candidate(normalized):
            return normalized

    separators = [" | ", "|", " l ", " L "]
    for separator in separators:
        if separator in cleaned:
            parts = [part.strip(" -_/") for part in cleaned.split(separator) if part.strip(" -_/")]
            if len(parts) >= 2:
                for candidate in reversed(parts[1:]):
                    normalized = _normalize_folder_candidate(candidate)
                    if normalized and not _is_low_value_folder_candidate(normalized):
                        return normalized

    return None


def _normalize_folder_candidate(candidate: str) -> str | None:
    cleaned = " ".join(candidate.replace("_", " ").split()).strip(" -_/[]")
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0].strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    if not 2 <= len(cleaned) <= 48:
        return None
    return cleaned


def _is_low_value_folder_candidate(candidate: str) -> bool:
    lower = candidate.lower()
    exact = {
        "api oficial",
        "novo",
        "novo v.2",
        "copy",
        "prospect",
        "falta imagem",
        "imagem",
        "disparo",
        "follow up",
        "uazapi",
        "z-api",
        "api oficial",
        "active",
        "sdr",
        "rj",
    }
    prefixes = ("d+", "wpp", "whatsapp", "prospect ", "fluxo ", "tool ", "api ", "novo ", "uazapi", "z-api")
    if lower in exact:
        return True
    return any(lower.startswith(prefix) for prefix in prefixes)


async def get_workflow(client: N8nClient, workflow_id: str) -> dict[str, Any]:
    return await client.get_workflow(workflow_id)


async def list_executions(
    client: N8nClient,
    workflow_id: str,
    *,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    data = await client.list_executions(workflow_id=workflow_id, status=status, limit=limit)
    executions = []
    for execution in data.get("data", []):
        executions.append({
            "id": execution.get("id"),
            "workflowId": execution.get("workflowId"),
            "status": execution.get("status"),
            "startedAt": execution.get("startedAt"),
            "stoppedAt": execution.get("stoppedAt"),
            "mode": execution.get("mode"),
            "finished": execution.get("finished"),
        })
    return {"total": len(executions), "executions": executions}


async def create_backup(client: N8nClient, workflow_id: str) -> dict[str, Any]:
    workflow = await client.get_workflow(workflow_id)
    backup_path, timestamp = await backup_workflow(client, workflow_id)
    event = append_audit_event(
        "backup_created",
        workflow_id=workflow_id,
        workflow_name=workflow.get("name"),
        backup=backup_path,
    )
    return {
        "success": True,
        "workflow_id": workflow_id,
        "workflow_name": workflow.get("name"),
        "backup": backup_path,
        "timestamp": timestamp,
        "audit_event": event,
    }


def list_backups() -> dict[str, Any]:
    backup_dir = get_backup_dir()
    backups = []
    for path in sorted(backup_dir.glob("*.json"), reverse=True):
        parts = path.stem.rsplit("_", 2)
        workflow_id = parts[0] if parts else path.stem
        backups.append({
            "path": str(path),
            "name": path.name,
            "workflow_id": workflow_id,
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
        })
    return {"total": len(backups), "backups": backups}


async def restore_backup(client: N8nClient, workflow_id: str, backup_path: str, *, approved_by: str = "human") -> dict[str, Any]:
    workflow = await client.get_workflow(workflow_id)
    pre_restore_backup, _timestamp = await backup_workflow(client, workflow_id)
    backup_data = load_backup(backup_path)
    result = await client.update_workflow(workflow_id, workflow_update_payload(backup_data))
    event = append_audit_event(
        "workflow_restored",
        workflow_id=workflow_id,
        workflow_name=workflow.get("name"),
        approved_by=approved_by,
        backup_before_restore=pre_restore_backup,
        restored_from=backup_path,
        result_id=result.get("id"),
    )
    return {
        "success": True,
        "workflow_id": workflow_id,
        "workflow": result,
        "backup": pre_restore_backup,
        "restored_from": backup_path,
        "audit_event": event,
    }


def _execution_time(full_execution: dict[str, Any], summary: dict[str, Any] | None) -> str | None:
    if summary:
        for key in ("startedAt", "stoppedAt", "createdAt"):
            if summary.get(key):
                return summary.get(key)
    for key in ("startedAt", "stoppedAt", "createdAt"):
        if full_execution.get(key):
            return full_execution.get(key)
    data = full_execution.get("data", {})
    if isinstance(data, dict):
        for key in ("startedAt", "stoppedAt", "createdAt"):
            if data.get(key):
                return data.get(key)
    return None


async def analyze_workflow_failure(
    client: N8nClient,
    workflow_id: str,
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    workflow = await client.get_workflow(workflow_id)
    workflow_name = workflow.get("name", "Unknown")
    execution, summary = await get_execution_for_analysis(client, workflow_id, execution_id)
    if execution is None:
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "message": "No failed execution found for this workflow.",
            "failure_analysis": None,
            "proposed_fix": None,
        }

    failed = extract_failed_node(execution)
    if failed is None:
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "execution_id": execution_id or (summary or {}).get("id"),
            "execution_time": _execution_time(execution, summary),
            "message": "Execution was fetched, but no failed node could be identified automatically.",
            "failure_analysis": {
                "failed_node": None,
                "node_type": None,
                "error_message": "unknown",
                "probable_cause": "Causa nao determinada automaticamente. Requer analise manual.",
                "severity": "medium",
                "auto_fixable": False,
                "recommended_action": "Review the execution data manually.",
                "requires_human": True,
                "human_reason": "The failed node could not be identified from execution data.",
            },
            "proposed_fix": None,
        }

    node_types = {node.get("name", ""): node.get("type", "") for node in workflow.get("nodes", [])}
    failed_node = failed.get("node_name")
    node_type = node_types.get(failed_node, "unknown")
    error_message = failed.get("error_message", "unknown")
    classification = classify_failure(error_message, node_type)
    proposed_fix = None
    if classification["auto_fixable"]:
        proposed_fix = {
            "tool": "propose_fix",
            "params": {
                "workflow_id": workflow_id,
                "execution_id": execution_id or (summary or {}).get("id"),
            },
        }

    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "execution_id": execution_id or (summary or {}).get("id"),
        "execution_time": _execution_time(execution, summary),
        "failure_analysis": {
            "failed_node": failed_node,
            "node_type": node_type,
            "error_message": error_message,
            "probable_cause": classification["probable_cause"],
            "severity": classification["severity"],
            "auto_fixable": classification["auto_fixable"],
            "recommended_action": classification["recommended_action"],
            "requires_human": classification["requires_human"],
            "human_reason": classification["human_reason"],
        },
        "proposed_fix": proposed_fix,
    }


async def propose_fix(
    client: N8nClient,
    workflow_id: str,
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    workflow = await client.get_workflow(workflow_id)
    execution, summary = await get_execution_for_analysis(client, workflow_id, execution_id)
    failed_node = None
    detected_error = "unknown"

    if execution:
        failed = extract_failed_node(execution)
        if failed:
            failed_node = failed.get("node_name")
            detected_error = failed.get("error_message") or "unknown"

    proposed_changes: list[dict[str, Any]] = []
    risk = "medium"
    apply_available = False

    if failed_node and detected_error != "unknown":
        proposed_changes, risk, apply_available = propose_changes_for_failure(workflow, failed_node, detected_error)

    if risk != LOW_RISK:
        apply_available = False

    response = {
        "workflow_id": workflow_id,
        "workflow_name": workflow.get("name"),
        "execution_id": execution_id or (summary or {}).get("id"),
        "failed_node": failed_node,
        "detected_error": detected_error,
        "proposed_changes": proposed_changes,
        "risk": risk,
        "apply_available": apply_available,
    }
    response["briefing"] = _proposal_briefing(response)
    append_audit_event("fix_proposed", **response)
    return response


async def attempt_fix(
    client: N8nClient,
    workflow_id: str,
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    proposal = await propose_fix(client, workflow_id, execution_id=execution_id)
    if proposal.get("proposed_changes"):
        proposal["attempted_auto_patch"] = True
        proposal["attempt_result"] = "A proposta já continha mudanças executáveis."
        proposal["briefing"] = _proposal_briefing(proposal)
        append_audit_event("fix_attempted", **proposal)
        return proposal

    workflow = await client.get_workflow(workflow_id)
    failed_node = proposal.get("failed_node")
    detected_error = str(proposal.get("detected_error") or "")

    changes: list[dict[str, Any]] = []
    if isinstance(failed_node, str) and "column names were updated" in detected_error.lower():
        changes = _attempt_google_sheets_schema_refresh(workflow, failed_node)

    response = {
        **proposal,
        "proposed_changes": changes,
        "risk": "medium" if changes else proposal.get("risk", "medium"),
        "apply_available": False,
        "attempted_auto_patch": True,
        "attempt_result": (
            "A IA montou uma tentativa de ajuste a partir do JSON atual do node."
            if changes
            else "A IA tentou montar um ajuste, mas não encontrou patch objetivo no JSON do workflow."
        ),
    }
    response["briefing"] = _proposal_briefing(response)
    append_audit_event("fix_attempted", **response)
    return response


def _attempt_google_sheets_schema_refresh(workflow: dict[str, Any], failed_node: str) -> list[dict[str, Any]]:
    node = next((item for item in workflow.get("nodes", []) if item.get("name") == failed_node), None)
    if not isinstance(node, dict) or node.get("type") != "n8n-nodes-base.googleSheets":
        return []

    columns = node.get("parameters", {}).get("columns")
    if not isinstance(columns, dict):
        return []
    value = columns.get("value")
    current_schema = columns.get("schema")
    if not isinstance(value, dict) or not value:
        return []

    rebuilt_schema = []
    for column_name in value.keys():
        rebuilt_schema.append({
            "id": column_name,
            "displayName": column_name,
            "required": False,
            "defaultMatch": False,
            "display": True,
            "type": "string",
            "canBeUsedToMatch": True,
        })

    if current_schema == rebuilt_schema:
        return []

    return [{
        "node": failed_node,
        "field": "parameters.columns.schema",
        "from": current_schema,
        "to": rebuilt_schema,
        "reason": (
            "O Google Sheets informou que os nomes das colunas mudaram após o setup do node. "
            "A tentativa reconstrói o schema local usando apenas as colunas já mapeadas em columns.value."
        ),
    }]


def _proposal_briefing(proposal: dict[str, Any]) -> dict[str, Any]:
    changes = proposal.get("proposed_changes")
    proposed_changes = changes if isinstance(changes, list) else []
    failed_node = proposal.get("failed_node") or "node não identificado"
    detected_error = proposal.get("detected_error") or "unknown"
    risk = proposal.get("risk") or "unknown"

    if proposed_changes:
        change_descriptions = []
        for change in proposed_changes:
            if not isinstance(change, dict):
                continue
            field = change.get("field", "campo")
            before = change.get("from")
            after = change.get("to")
            reason = change.get("reason", "Correção proposta pela análise da execução.")
            change_descriptions.append(f"Alterar {field} de {before!r} para {after!r}. Motivo: {reason}")
        return {
            "summary": f"A falha ocorreu no node {failed_node}.",
            "error": str(detected_error),
            "suggested_execution": "Aplicar os patches listados em proposed_changes após revisão humana.",
            "why": "A proposta contém alterações específicas e auditáveis no JSON do workflow.",
            "can_execute": risk in {LOW_RISK, "medium"},
            "execution_blocker": None if risk in {LOW_RISK, "medium"} else "Risco alto exige intervenção manual no n8n.",
            "changes_brief": change_descriptions,
        }

    blocker = "A IA não encontrou um patch objetivo no JSON do workflow para aplicar via API."
    suggestion = "Não há execução automática segura disponível para esta proposta."
    if "column names were updated" in str(detected_error).lower():
        blocker = (
            "O erro indica que as colunas da planilha mudaram depois da configuração do node. "
            "Use o botão de tentativa para a IA tentar reconstruir o schema local a partir do mapeamento atual do node. "
            "Se isso não gerar patch, será necessário revisar/remapear as colunas no n8n."
        )
        suggestion = "Pedir para a IA tentar montar um ajuste de schema; aplicar somente se ela gerar proposed_changes."
    return {
        "summary": f"A falha ocorreu no node {failed_node}.",
        "error": str(detected_error),
        "suggested_execution": suggestion,
        "why": "Sem proposed_changes, o sistema não tem um patch concreto para aplicar com backup e auditoria.",
        "can_execute": False,
        "execution_blocker": blocker,
        "changes_brief": [],
    }


async def apply_fix(
    client: N8nClient,
    workflow_id: str,
    *,
    execution_id: str | None = None,
    approved_by: str = "human",
    allow_medium_risk: bool = False,
    use_attempt: bool = False,
) -> dict[str, Any]:
    proposal = await attempt_fix(client, workflow_id, execution_id=execution_id) if use_attempt else await propose_fix(client, workflow_id, execution_id=execution_id)
    if proposal["risk"] == "high":
        append_audit_event("fix_apply_blocked", reason="risk_high", approved_by=approved_by, **proposal)
        raise ServiceError("High-risk fixes require manual intervention in n8n.")
    if proposal["risk"] == "medium" and not allow_medium_risk:
        append_audit_event("fix_apply_blocked", reason="medium_risk_requires_human_override", approved_by=approved_by, **proposal)
        raise ServiceError("Medium-risk fixes require explicit human approval.")
    if proposal["risk"] not in {LOW_RISK, "medium"}:
        append_audit_event("fix_apply_blocked", reason="unsupported_risk", approved_by=approved_by, **proposal)
        raise ServiceError("This risk level is not supported for automatic application.")
    if not proposal["proposed_changes"]:
        append_audit_event("fix_apply_blocked", reason="no_safe_fix_available", approved_by=approved_by, **proposal)
        raise ServiceError("No executable proposed changes are available.")

    workflow = await client.get_workflow(workflow_id)
    backup_path, _timestamp = await backup_workflow(client, workflow_id)
    for change in proposal["proposed_changes"]:
        node_name = change.get("node")
        field = change.get("field")
        if not isinstance(node_name, str) or not isinstance(field, str):
            continue
        _index, node = find_unique_node(workflow, node_name)
        _set_nested_field(node, field, change.get("to"))

    result = await client.update_workflow(workflow_id, workflow_update_payload(workflow))
    response = {
        **proposal,
        "applied": True,
        "approved_by": approved_by,
        "human_approved_medium_risk": proposal["risk"] == "medium" and allow_medium_risk,
        "backup": backup_path,
        "workflow": result,
    }
    event = append_audit_event("fix_applied", **response)
    response["audit_event"] = event
    return response
