let selectedWorkflow = null;
let lastProposal = null;
let allWorkflows = [];

const el = (id) => document.getElementById(id);

function show(target, value) {
  target.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return body;
}

function setSelected(workflow) {
  selectedWorkflow = workflow;
  lastProposal = null;
  el("selectedTitle").textContent = workflow.name || workflow.id;
  const status = workflow.isArchived ? "arquivado" : workflow.active ? "ativo" : "inativo";
  el("selectedStatus").textContent = status;
  el("selectedStatus").className = workflow.active && !workflow.isArchived ? "ok" : "off";
  for (const id of ["backupBtn", "executionsBtn", "analyzeBtn", "proposeBtn"]) {
    el(id).disabled = false;
  }
  setApplyState(false, "Gere uma proposta antes de aplicar qualquer correção.");
  show(el("analysisOutput"), {
    workflow_id: workflow.id,
    workflow_name: workflow.name,
    status,
    grupo: workflow.subgroup_name || workflow.folder_name,
    mensagem: "Carregando execucoes recentes...",
  });
  showProposalMessage("Workflow selecionado. Clique em Propor correção para gerar uma sugestão segura.");
  document.querySelectorAll(".workflow-item").forEach((node) => {
    node.classList.toggle("active", node.dataset.id === String(workflow.id));
  });
  void loadExecutions(workflow);
}

function setApplyState(enabled, message) {
  const button = el("applyBtn");
  const proposalButton = el("proposalApplyBtn");
  const hint = el("applyHint");
  button.disabled = !enabled;
  button.textContent = enabled ? "Aprovar e aplicar" : "Sem ajuste executável";
  button.title = message || "";
  proposalButton.disabled = !enabled;
  proposalButton.textContent = enabled ? "Executar ajuste sugerido" : "Sem ajuste executável";
  proposalButton.title = message || "";
  hint.textContent = message || "";
  hint.className = enabled ? "apply-hint ok" : "apply-hint warning";
}

function explainApplyBlock(proposal) {
  const changes = Array.isArray(proposal.proposed_changes) ? proposal.proposed_changes : [];
  if (!changes.length) {
    return "A IA diagnosticou a falha, mas não encontrou uma alteração segura para aplicar automaticamente. Escale para humano.";
  }
  if (proposal.risk !== "low") {
    return `Aplicação exige revisão humana: risco ${proposal.risk}. Com mudanças concretas, você poderá aprovar e aplicar.`;
  }
  if (!proposal.apply_available) {
    return "Aplicação bloqueada: a proposta não está marcada como aplicável com segurança.";
  }
  return "Aplicação bloqueada por política de segurança.";
}

function showProposalMessage(message) {
  el("proposalBrief").className = "proposal-brief muted-box";
  el("proposalBrief").textContent = message;
  show(el("proposalOutput"), "Nenhuma proposta ainda.");
}

function renderProposal(proposal) {
  const briefing = proposal.briefing || buildProposalBriefing(proposal);
  const changes = Array.isArray(proposal.proposed_changes) ? proposal.proposed_changes : [];
  const canExecute = Boolean(changes.length && (proposal.risk === "low" || proposal.risk === "medium"));

  el("proposalBrief").className = canExecute ? "proposal-brief ok-box" : "proposal-brief warning-box";
  el("proposalBrief").innerHTML = `
    <strong>${escapeHtml(briefing.summary || "Proposta analisada.")}</strong>
    <span><b>Erro:</b> ${escapeHtml(briefing.error || proposal.detected_error || "unknown")}</span>
    <span><b>Sugestão:</b> ${escapeHtml(briefing.suggested_execution || "Sem sugestão executável.")}</span>
    <span><b>Por quê:</b> ${escapeHtml(briefing.why || "Sem justificativa disponível.")}</span>
    ${proposal.attempt_result ? `<span><b>Tentativa:</b> ${escapeHtml(proposal.attempt_result)}</span>` : ""}
    ${briefing.execution_blocker ? `<span><b>Bloqueio:</b> ${escapeHtml(briefing.execution_blocker)}</span>` : ""}
  `;
  show(el("proposalOutput"), proposal);
}

function buildProposalBriefing(proposal) {
  const changes = Array.isArray(proposal.proposed_changes) ? proposal.proposed_changes : [];
  if (changes.length) {
    return {
      summary: `Falha no node ${proposal.failed_node || "não identificado"}.`,
      error: proposal.detected_error || "unknown",
      suggested_execution: "Aplicar os patches listados no JSON abaixo após revisão humana.",
      why: "A proposta contém alterações específicas no workflow.",
      execution_blocker: null,
    };
  }
  return {
    summary: `Falha no node ${proposal.failed_node || "não identificado"}.`,
    error: proposal.detected_error || "unknown",
    suggested_execution: "Não há execução automática segura disponível para esta proposta.",
    why: "Sem proposed_changes, não existe patch concreto para aplicar via API.",
    execution_blocker: "Revise o node manualmente no n8n ou gere uma proposta com mudanças objetivas.",
  };
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadHealth() {
  try {
    const health = await api("/health");
    el("health").textContent = `API pronta -> ${health.n8n_url}`;
  } catch (error) {
    el("health").textContent = `Falha no backend: ${error.message}`;
  }
}

async function loadWorkflows() {
  const list = el("workflowList");
  list.innerHTML = "Carregando...";
  try {
    const data = await api("/workflows");
    const workflows = Array.isArray(data.workflows) ? data.workflows : [];
    allWorkflows = workflows;
    renderWorkflows();
  } catch (error) {
    list.textContent = `Erro: ${error.message}`;
  }
}

function renderWorkflows() {
  const list = el("workflowList");
  const query = el("workflowSearch").value.trim();
  const filtered = query ? allWorkflows.filter((workflow) => workflowMatchesSearch(workflow, query)) : allWorkflows;
  const searchActive = Boolean(query);

  el("workflowCount").textContent = searchActive ? `${filtered.length} / ${allWorkflows.length}` : allWorkflows.length;
  list.innerHTML = "";

  const categories = groupWorkflowsByCategory(filtered);
  for (const category of categories) {
    const categorySection = document.createElement("section");
    categorySection.className = "category-group";

    const categoryHeader = document.createElement("div");
    categoryHeader.className = "category-header";
    categoryHeader.innerHTML = `<span>${category.name}</span><small>${category.total}</small>`;

    const categoryBody = document.createElement("div");
    categoryBody.className = "category-body";

    for (const subgroup of category.subgroups) {
      const folderSection = document.createElement("section");
      folderSection.className = searchActive ? "folder-group" : "folder-group collapsed";

      const header = document.createElement("button");
      header.className = "folder-header";
      header.type = "button";
      header.innerHTML = `<span>${subgroup.name}</span><small>${subgroup.workflows.length}</small>`;
      header.addEventListener("click", () => folderSection.classList.toggle("collapsed"));

      const body = document.createElement("div");
      body.className = "folder-body";

      for (const workflow of subgroup.workflows) {
        const item = document.createElement("div");
        const statusClass = workflow.isArchived ? "archived" : workflow.active ? "enabled" : "disabled";
        item.className = `workflow-item ${statusClass}`;
        item.dataset.id = workflow.id;
        const status = workflow.isArchived ? "arquivado" : workflow.active ? "ativo" : "inativo";
        item.innerHTML = `<strong>${workflow.name || workflow.id}</strong><span>${workflow.id} - ${status}</span>`;
        item.addEventListener("click", () => setSelected(workflow));
        body.appendChild(item);
      }

      folderSection.appendChild(header);
      folderSection.appendChild(body);
      categoryBody.appendChild(folderSection);
    }

    categorySection.appendChild(categoryHeader);
    categorySection.appendChild(categoryBody);
    list.appendChild(categorySection);
  }

  if (!allWorkflows.length) {
    list.textContent = "Nenhum workflow encontrado.";
  } else if (!filtered.length) {
    list.textContent = "Nenhum resultado para a busca.";
  }
}

function workflowMatchesSearch(workflow, query) {
  const status = workflow.isArchived ? "arquivado" : workflow.active ? "ativo" : "inativo";
  const group = workflow.group || {};
  const fields = [
    workflow.id,
    workflow.name,
    workflow.folder_name,
    workflow.category_name,
    workflow.subgroup_name,
    group.category_name,
    group.subgroup_name,
    status,
    ...(Array.isArray(workflow.tags) ? workflow.tags : []),
  ];
  return normalizeSearch(fields.join(" ")).includes(normalizeSearch(query));
}

function normalizeSearch(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function groupWorkflowsByCategory(workflows) {
  const categories = new Map();
  for (const workflow of workflows) {
    const group = workflow.group || {};
    const categoryId = group.category_id || workflow.category_id || "unclassified";
    const categoryName = group.category_name || workflow.category_name || "Sem classificação";
    const subgroupId = group.subgroup_id || workflow.subgroup_id || workflow.folder_id || "unclassified";
    const subgroupName = group.subgroup_name || workflow.subgroup_name || workflow.folder_name || "Revisar manualmente";

    if (!categories.has(categoryId)) {
      categories.set(categoryId, { id: categoryId, name: categoryName, total: 0, subgroups: new Map() });
    }
    const category = categories.get(categoryId);
    category.total += 1;

    if (!category.subgroups.has(subgroupId)) {
      category.subgroups.set(subgroupId, { id: subgroupId, name: subgroupName, workflows: [] });
    }
    category.subgroups.get(subgroupId).workflows.push(workflow);
  }

  return [...categories.values()]
    .map((category) => ({
      ...category,
      subgroups: [...category.subgroups.values()]
        .map((subgroup) => ({
          ...subgroup,
          workflows: subgroup.workflows.sort(compareWorkflows),
        }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .sort((a, b) => {
      const order = { clients: 1, "potential-clients": 2, internal: 3, archived: 4, unclassified: 5 };
      return (order[a.id] || 99) - (order[b.id] || 99) || a.name.localeCompare(b.name);
    });
}

function compareWorkflows(a, b) {
  const statusOrder = workflowStatusRank(a) - workflowStatusRank(b);
  if (statusOrder !== 0) return statusOrder;
  return (a.name || "").localeCompare(b.name || "");
}

function workflowStatusRank(workflow) {
  if (workflow.active && !workflow.isArchived) return 0;
  if (!workflow.active && !workflow.isArchived) return 1;
  return 2;
}

function groupWorkflowsByFolder(workflows) {
  return groupWorkflowsByCategory(workflows)
    .flatMap((category) => category.subgroups)
    .sort((a, b) => {
      if (a.id === "archived") return 1;
      if (b.id === "archived") return -1;
      return a.name.localeCompare(b.name);
    });
}

async function createBackup() {
  if (!selectedWorkflow) return;
  show(el("backupOutput"), "Gerando backup...");
  try {
    const data = await api(`/workflows/${selectedWorkflow.id}/backup`, { method: "POST" });
    show(el("backupOutput"), data);
    await loadBackups();
  } catch (error) {
    show(el("backupOutput"), `Erro: ${error.message}`);
  }
}

async function loadExecutions(workflow = selectedWorkflow) {
  if (!workflow) return;
  const workflowId = workflow.id;
  show(el("analysisOutput"), {
    workflow_id: workflow.id,
    workflow_name: workflow.name,
    status: workflow.isArchived ? "arquivado" : workflow.active ? "ativo" : "inativo",
    mensagem: "Carregando execucoes recentes...",
  });
  try {
    const data = await api(`/workflows/${workflowId}/executions?limit=10`);
    if (!selectedWorkflow || selectedWorkflow.id !== workflowId) return;
    show(el("analysisOutput"), {
      workflow_id: workflow.id,
      workflow_name: workflow.name,
      status: workflow.isArchived ? "arquivado" : workflow.active ? "ativo" : "inativo",
      executions: data,
    });
  } catch (error) {
    if (!selectedWorkflow || selectedWorkflow.id !== workflowId) return;
    show(el("analysisOutput"), `Erro: ${error.message}`);
  }
}

async function analyzeFailure() {
  if (!selectedWorkflow) return;
  show(el("analysisOutput"), "Analisando falha...");
  try {
    const data = await api(`/workflows/${selectedWorkflow.id}/analyze-failure`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    show(el("analysisOutput"), data);
  } catch (error) {
    show(el("analysisOutput"), `Erro: ${error.message}`);
  }
}

async function proposeFix() {
  if (!selectedWorkflow) return;
  show(el("proposalOutput"), "Gerando proposta...");
  try {
    const data = await api(`/workflows/${selectedWorkflow.id}/propose-fix`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    lastProposal = data;
    renderProposal(data);
    const hasChanges = Array.isArray(data.proposed_changes) && data.proposed_changes.length > 0;
    const canApply = Boolean(hasChanges && (data.risk === "low" || data.risk === "medium"));
    const applyMessage = data.risk === "medium"
      ? "Correção de risco médio disponível. A aplicação exige aprovação humana explícita e salva backup antes."
      : "Correção de baixo risco disponível. Revise a proposta antes de aplicar.";
    setApplyState(canApply, canApply ? applyMessage : explainApplyBlock(data));
  } catch (error) {
    el("proposalBrief").className = "proposal-brief warning-box";
    el("proposalBrief").textContent = `Erro ao gerar proposta: ${error.message}`;
    show(el("proposalOutput"), `Erro: ${error.message}`);
    setApplyState(false, "Não foi possível gerar uma proposta aplicável.");
  }
}

async function applyFix() {
  if (!selectedWorkflow || !lastProposal) return;
  const riskText = lastProposal.risk === "medium" ? " Esta proposta é de risco médio e será aplicada por aprovação humana." : "";
  const ok = window.confirm(`Aprovar e aplicar esta correcao? Um backup sera salvo antes da alteracao.${riskText}`);
  if (!ok) return;
  show(el("proposalOutput"), "Aplicando correcao aprovada...");
  try {
    const data = await api(`/workflows/${selectedWorkflow.id}/apply-fix`, {
      method: "POST",
      body: JSON.stringify({
        execution_id: lastProposal.execution_id || null,
        approved_by: "human-ui",
        allow_medium_risk: lastProposal.risk === "medium",
        use_attempt: Boolean(lastProposal.attempted_auto_patch),
      }),
    });
    renderProposal(data);
    setApplyState(false, "Correção aplicada. Gere uma nova proposta para aplicar outra alteração.");
    await loadBackups();
    await loadAudit();
  } catch (error) {
    show(el("proposalOutput"), `Erro: ${error.message}`);
  }
}

async function loadBackups() {
  try {
    show(el("backupOutput"), await api("/backups"));
  } catch (error) {
    show(el("backupOutput"), `Erro: ${error.message}`);
  }
}

async function loadAudit() {
  try {
    show(el("auditOutput"), await api("/audit-log"));
  } catch (error) {
    show(el("auditOutput"), `Erro: ${error.message}`);
  }
}

el("refreshWorkflows").addEventListener("click", loadWorkflows);
el("workflowSearch").addEventListener("input", renderWorkflows);
el("backupBtn").addEventListener("click", createBackup);
el("executionsBtn").addEventListener("click", loadExecutions);
el("analyzeBtn").addEventListener("click", analyzeFailure);
el("proposeBtn").addEventListener("click", proposeFix);
el("applyBtn").addEventListener("click", applyFix);
el("proposalApplyBtn").addEventListener("click", applyFix);
el("refreshBackups").addEventListener("click", loadBackups);
el("refreshAudit").addEventListener("click", loadAudit);

loadHealth();
loadWorkflows();
loadBackups();
loadAudit();
