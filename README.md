# n8n-mcp-server

Servidor MCP que dá a um assistente de IA acesso operacional ao n8n: listar, montar,
validar, diagnosticar e executar workflows — conversando.

## Por que existe

Montar workflow no n8n é arrastar nó e preencher campo. A API REST existe, mas usá-la
direto significa escrever à mão o JSON de nós e conexões. Este servidor põe uma camada
MCP na frente: o modelo descreve a intenção, o servidor valida a estrutura e aplica.

## O que ele faz

- **Workflows** — listar (por tag, status, limite), criar, atualizar, apagar e
  restaurar de backup.
- **Builder** — montar do zero, adicionar, substituir e reparametrizar nós, validar a
  estrutura e propor correção quando ela não fecha.
- **Execuções** — listar, inspecionar e disparar.
- **Diagnóstico** — analisar a falha de um workflow e devolver a causa junto da ação
  sugerida, não só o stack trace.

## Como ele evita estrago

O servidor age sobre a sua instância de n8n de verdade, então as salvaguardas são parte
do design:

- Toda entrada passa por modelo Pydantic com `extra="forbid"` — campo desconhecido é
  rejeitado, não ignorado em silêncio.
- Operação destrutiva exige confirmação explícita (`confirm_delete`), aplicada pelo
  decorador `requires_confirmation`.
- Toda alteração faz backup do workflow antes de escrever.
- O que muda estado é registrado num log de auditoria em JSONL.

## Templates inclusos

Doze workflows prontos para servir de ponto de partida:

| Área | Templates |
| --- | --- |
| IA | `ai_classification`, `ai_rag_pipeline`, `ai_text_processing` |
| WhatsApp | `whatsapp_chatbot`, `whatsapp_crm_sync`, `chat_routing` |
| API e webhook | `api_error_retry`, `api_sync_bidirectional`, `api_webhook_transform`, `webhook_process_respond`, `webhook_validate_db` |
| Agendado | `cron_fetch_notify` |

## Rodando

Requer Python 3.11+ e uma instância de n8n com API habilitada.

```bash
uv sync
cp .env.example .env    # preencha N8N_URL e N8N_API_KEY
uv run n8n-mcp          # servidor MCP, fala por stdio
uv run n8n-api          # opcional: API HTTP + UI web
```

Variáveis de ambiente:

| Variável | Para quê |
| --- | --- |
| `N8N_URL` | Endereço da instância n8n |
| `N8N_API_KEY` | Chave de API do n8n |
| `N8N_MCP_BACKUP_DIR` | Onde guardar os backups de workflow |
| `N8N_MCP_AUDIT_LOG` | Arquivo JSONL do log de auditoria |
| `N8N_MCP_FOLDER_MAP` | Mapa de pastas para organizar workflows |

## Stack

Python 3.11 · MCP (FastMCP) · FastAPI · httpx · Pydantic v2
