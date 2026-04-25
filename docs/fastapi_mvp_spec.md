# FastAPI MVP Spec - Internal n8n AI Ops Interface

## 1. Contexto

Este projeto ja possui um MCP Server Python para operar workflows do n8n via API REST. O proximo passo e criar uma interface interna simples, apoiada por um backend FastAPI, para que humanos da operacao possam acionar diagnosticos e correcoes com aprovacao explicita.

A ferramenta sera usada internamente pela empresa, inicialmente por:

- Mateus
- Head de operacoes

Nao sera produtizada para clientes neste momento.

## 2. Objetivo Do MVP

Construir uma interface interna para:

1. Conectar ao n8n self-hosted em VPS.
2. Listar workflows.
3. Analisar falhas recentes.
4. Gerar proposta de correcao em dry-run.
5. Exibir a proposta para aprovacao humana.
6. Aplicar correcao somente apos aprovacao humana.
7. Salvar backup antes de qualquer alteracao.
8. Registrar auditoria local das acoes.

Fluxo esperado:

```text
Humano seleciona workflow
IA/backend analisa falha real
IA/backend propoe correcao
Humano revisa
Humano aprova ou recusa
Sistema aplica somente se aprovado
Sistema valida e registra auditoria
```

## 3. Decisoes Confirmadas

- Uso interno apenas.
- Sem login no primeiro MVP.
- Rodar localmente no Mac, preferencialmente em `127.0.0.1`.
- O n8n roda em VPS self-hosted.
- Frontend aprovado para MVP.
- MVP deve permitir aplicar correcoes, desde que haja aprovacao humana.
- O humano sempre da o comando final para aplicar.
- A IA/sistema e proibida de inventar solucoes ou assumir contexto de negocio.
- Se a IA/sistema nao tiver evidencia suficiente, deve escalar para humano.
- Correcoes de alto risco nao devem ser aplicadas automaticamente.

## 4. Arquitetura

Arquitetura recomendada:

```text
Frontend web simples
  -> Backend FastAPI local
    -> Service layer compartilhada
      -> N8nClient
      -> backup.py
      -> analysis.py
      -> workflow_utils.py
      -> API REST do n8n na VPS
```

O MCP Server deve continuar existindo para agentes de IA, mas a interface web nao deve falar diretamente com MCP stdio. A interface deve falar com FastAPI por HTTP.

## 5. Organizacao Recomendada Do Codigo

```text
src/n8n_mcp/
  client.py              # Cliente HTTP do n8n
  backup.py              # Backup/restore local
  analysis.py            # Classificacao e proposta de falhas
  workflow_utils.py      # Merge, patch e manipulacao de workflow
  service.py             # Casos de uso compartilhados
  tools/                 # Tools MCP chamam service.py
  api/                   # FastAPI chama service.py
```

Regra importante: evitar duplicacao de regra entre MCP e FastAPI. A logica de negocio deve ficar em `service.py` ou helpers compartilhados. MCP tools e endpoints FastAPI devem ser apenas adaptadores.

## 6. Escopo Do MVP

### In Scope

- Backend FastAPI.
- Frontend basico.
- Configuracao por variaveis de ambiente.
- Listagem de workflows.
- Detalhe de workflow.
- Backup manual.
- Analise de falha.
- Proposta de correcao em dry-run.
- Aplicacao de correcao com aprovacao humana.
- Restore de backup.
- Audit log local.

### Out Of Scope

- Login/autenticacao.
- Multiusuario.
- Multicliente.
- SaaS/produtizacao.
- Deploy publico.
- Edicao de credenciais do n8n.
- Correcoes sem evidencia de execucao real.
- Delete de workflow pela interface no MVP.

## 7. Regras De Seguranca E Negocio

### RN-001 - Execucao Local

O MVP deve rodar localmente, preferencialmente em:

```text
127.0.0.1
```

Sem login, nao expor a interface publicamente.

### RN-002 - Backup Obrigatorio

Antes de qualquer alteracao no n8n, salvar backup local do workflow atual.

Se o backup falhar, abortar a alteracao.

### RN-003 - Dry-Run Obrigatorio Para Correcao

Toda correcao automatica deve primeiro gerar proposta em dry-run.

Sem aprovacao humana explicita, nenhuma correcao deve ser aplicada.

### RN-004 - Aprovacao Humana

O botao ou endpoint de aplicar correcao deve representar uma aprovacao humana explicita.

O sistema deve registrar essa aprovacao no audit log.

### RN-005 - Nao Inventar

Se nao houver evidencia suficiente na execucao com falha, retornar:

```text
requires_human=true
auto_fixable=false
```

Nao inventar causa, URL, credencial, payload, schema ou regra de negocio.

### RN-006 - Escalar Para Humano

Escalar para humano quando:

- credencial expirada;
- permissao negada;
- URL ambigua;
- erro de logica de negocio;
- schema/payload incerto;
- node corrompido;
- erro desconhecido;
- multiplas interpretacoes possiveis.

### RN-007 - Aplicacao Permitida No MVP

O MVP pode aplicar correcoes apenas quando:

- ha execucao real com erro;
- o node com erro foi identificado;
- a causa foi classificada com seguranca;
- a proposta e de baixo risco;
- backup foi salvo;
- humano aprovou.

### RN-008 - Bloqueio De Alto Risco

Correcoes `high` ou `critical` nao devem ser aplicadas automaticamente.

### RN-009 - Credenciais

Erros de credencial sempre exigem humano.

O sistema nao deve editar secrets ou credenciais do n8n.

### RN-010 - Audit Log

Toda acao relevante deve ser registrada:

- timestamp;
- workflow_id;
- workflow_name quando disponivel;
- acao;
- payload resumido;
- proposta;
- aprovacao;
- backup gerado;
- resultado;
- erro, se houver.

Formato recomendado no MVP:

```text
audit_logs/audit.jsonl
```

## 8. Classificacao De Risco

### Low Risk

Permitido aplicar com aprovacao humana:

- aumentar timeout;
- habilitar retry;
- ajustar parametro numerico;
- ajustar delay tecnico simples quando evidenciado.

### Medium Risk

Exige revisao humana cuidadosa. Aplicacao automatica deve ser evitada no MVP, salvo decisao explicita futura:

- alterar URL;
- alterar headers;
- alterar endpoint;
- alterar payload.

### High Risk

Nao aplicar automaticamente:

- credencial;
- permissao;
- certificado SSL;
- logica condicional;
- adicao/remocao de node;
- mudanca de fluxo;
- schema incerto.

### Critical

Nao aplicar automaticamente:

- workflow corrompido;
- node inexistente;
- erro estrutural grave;
- erro que impeça validar workflow com seguranca.

## 9. Endpoints FastAPI MVP

### Health

```http
GET /health
```

Retorna status do backend.

### Workflows

```http
GET /workflows
GET /workflows/{workflow_id}
```

Lista workflows e retorna detalhes de um workflow.

### Backup

```http
POST /workflows/{workflow_id}/backup
GET /backups
POST /workflows/{workflow_id}/restore
```

Cria backup, lista backups locais e restaura workflow a partir de backup aprovado.

### Execucoes

```http
GET /workflows/{workflow_id}/executions
```

Lista execucoes recentes, com filtro opcional por status.

### Analise E Correcao

```http
POST /workflows/{workflow_id}/analyze-failure
POST /workflows/{workflow_id}/propose-fix
POST /workflows/{workflow_id}/apply-fix
```

`propose-fix` deve ser dry-run.

`apply-fix` deve aplicar somente proposta aprovada e somente se risco permitido.

### Auditoria

```http
GET /audit-log
```

Retorna eventos recentes do audit log.

## 10. Tela MVP

### Area 1 - Workflows

Mostrar:

- nome;
- id;
- ativo/inativo;
- ultima atualizacao;
- acoes: ver detalhes, analisar falha, backup.

### Area 2 - Diagnostico

Mostrar:

- execucao analisada;
- node com falha;
- tipo do node;
- mensagem de erro;
- causa provavel;
- severidade;
- auto_fixable;
- requires_human;
- motivo humano, se houver.

### Area 3 - Correcao Proposta

Mostrar diff/plano:

```json
{
  "node": "API Request",
  "field": "parameters.timeout",
  "from": 30000,
  "to": 90000,
  "reason": "Latest failed execution timed out."
}
```

### Area 4 - Aprovacao

Botoes:

- Aprovar e aplicar;
- Recusar;
- Escalar para humano;
- Gerar backup;
- Restaurar backup.

## 11. Variaveis De Ambiente

```bash
N8N_URL="https://seu-n8n-na-vps.com"
N8N_API_KEY="sua-api-key"
N8N_MCP_BACKUP_DIR="./backups"
N8N_MCP_AUDIT_LOG="./audit_logs/audit.jsonl"
```

## 12. Criterios De Aceite

O MVP esta pronto quando:

1. FastAPI sobe localmente.
2. `/health` retorna OK.
3. Backend conecta ao n8n da VPS.
4. Interface lista workflows reais.
5. Usuario seleciona workflow.
6. Sistema analisa falha real ou retorna mensagem clara se nao houver falha.
7. Sistema gera proposta em dry-run sem alterar workflow.
8. Sistema bloqueia proposta sem evidencia suficiente.
9. Sistema bloqueia credenciais/permissoes como requires_human.
10. Usuario aprova proposta low risk.
11. Sistema salva backup antes de aplicar.
12. Sistema aplica correcao.
13. Sistema registra auditoria.
14. Usuario consegue ver backup salvo.
15. Restore funciona em workflow de teste.

## 13. Primeiro Fluxo De Teste Recomendado

1. Rodar FastAPI local.
2. Abrir `/docs`.
3. Testar `GET /health`.
4. Testar `GET /workflows`.
5. Escolher workflow descartavel.
6. Rodar `POST /workflows/{id}/backup`.
7. Simular ou escolher execucao com timeout.
8. Rodar `POST /workflows/{id}/analyze-failure`.
9. Rodar `POST /workflows/{id}/propose-fix`.
10. Revisar proposta.
11. Rodar `POST /workflows/{id}/apply-fix`.
12. Conferir backup e audit log.

## 14. Observacoes Para Agentes Futuros

- Nao implementar login no MVP.
- Nao expor em host publico sem login.
- Nao duplicar regra entre MCP tools e FastAPI.
- Nao permitir correcao sem backup.
- Nao aplicar high risk.
- Nao editar credenciais.
- Nao inventar causa quando a execucao nao der evidencia.
- Preferir implementar service layer antes de endpoints para manter MCP e FastAPI alinhados.
