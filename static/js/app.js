/* static/js/app.js — versione migliorata e allineata alla nuova UI */

class ChatApp {
  constructor() {
    /* ------------------ Riferimenti UI base ------------------ */
    // Chat aziendale
    this.messagesContainer = document.getElementById("messagesContainer");
    this.messageInput = document.getElementById("messageInput");
    this.chatForm = document.getElementById("chatForm");
    this.resetChatBtn = document.getElementById("resetChatBtn");

    // Documenti aziendali
    this.fileInput = document.getElementById("fileInput");
    this.documentsList = document.getElementById("documentsList");
    this.uploadBtn = document.getElementById("uploadBtn");

    // Service
    this.resetDbBtn = document.getElementById("resetDbBtn");

    // Topbar: selettore cantiere
    this.projectSelect = document.getElementById("projectSelect");
    this.chatMeta = document.getElementById("chatMeta");

    // KPI aziendali
    this.kpiWorkers = document.getElementById("kpiWorkers");
    this.kpiProjects = document.getElementById("kpiProjects");
    this.kpiDocs = document.getElementById("kpiDocs");
    this.kpiActiveProjects = document.getElementById("kpiActiveProjects");
    this.kpiActiveWorkers = document.getElementById("kpiActiveWorkers");
    this.rolesBreakdown = document.getElementById("rolesBreakdown");
    this.activeProjects = document.getElementById("activeProjects"); // lista opzionale

    // Cards elenco progetti (se presente)
    this.projectsList = document.getElementById("projectsList");

    // Sezione CANTIERI (nuova UI)
    this.siteHeader = document.getElementById("siteHeader");
    this.siteStatusBadge = document.getElementById("siteStatusBadge");
    this.siteUploadBtn = document.getElementById("siteUploadBtn");
    this.siteFileInput = document.getElementById("siteFileInput");
    this.siteDocumentsList = document.getElementById("siteDocumentsList");
    this.siteMessages = document.getElementById("siteMessages");
    this.siteMessageInput = document.getElementById("siteMessageInput");
    this.siteChatForm = document.getElementById("siteChatForm");
    this.siteResetChatBtn = document.getElementById("siteResetChatBtn");
    this.siteChatMeta = document.getElementById("siteChatMeta");
    this.sitesList = document.getElementById("sitesList");

    // Toolbar cantiere
    this.btnClearSite = document.getElementById("btnClearSite");
    this.btnAssignWorker = document.getElementById("btnAssignWorker");
    this.btnDeleteProject = document.getElementById("btnDeleteProject");
    this.btnCreateProjectTop = document.getElementById("btnCreateProjectTop");
    this.btnToggleStatus = document.getElementById("btnToggleStatus");

    // Modale: Nuovo cantiere
    this.projectModal = document.getElementById("projectModal");
    this.projectForm = document.getElementById("projectForm");
    this.openCreateButtons = [
      document.getElementById("btnOpenCreateProject"),
      document.getElementById("btnCreateProjectTop")
    ].filter(Boolean);

    // Modali operai (se presenti)
    this.btnAddWorker = document.getElementById("btnAddWorker");
    this.btnRemoveWorker = document.getElementById("btnRemoveWorker");

    /* ------------------ Stato ------------------ */
    this.state = {
      currentProjectId: "",
      currentProjectName: "",
      sending: false,
      projects: [], // cache dei cantieri caricati
    };

    window.App = this;
    this.init();
  }

  /* ============================================================
   * Init & listeners
   * ============================================================ */
  init() {
    /* Chat aziendale */
    this.chatForm?.addEventListener("submit", (e) => this.handleSubmit(e));
    this.resetChatBtn?.addEventListener("click", () => this.resetChat());

    /* Upload documenti AZIENDALI (nuovo wiring server) */
    this.uploadBtn?.addEventListener("click", () => {
      if (!this.fileInput) return;
      this.fileInput.click();
    });
    this.fileInput?.addEventListener("change", (e) => this.handleCompanyFileUpload(e));

    /* Topbar: selettore cantiere */
    this.projectSelect?.addEventListener("change", () => {
      const pid = this.projectSelect.value || "";
      const name = this.projectSelect.options[this.projectSelect.selectedIndex]?.text || "";
      this.setCurrentProject(pid, name);
      this.applySiteSelection();  // aggiorna se siamo nella vista Cantieri
    });

    /* Toolbar cantiere */
    this.btnClearSite?.addEventListener("click", () => {
      this.setCurrentProject("", "");
      this.applySiteSelection();
    });
    this.btnCreateProjectTop?.addEventListener("click", () => this.openModal('#projectModal'));
    this.btnDeleteProject?.addEventListener("click", () => this.handleDeleteProject());
    this.btnToggleStatus?.addEventListener("click", () => this.toggleProjectStatus());

    /* Upload documenti CANTIERE (server) */
    this.siteUploadBtn?.addEventListener("click", () => this.siteFileInput?.click());
    this.siteFileInput?.addEventListener("change", () => this.handleSiteFilesUpload());

    /* Chat cantiere (demo) */
    this.siteChatForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!this.state.currentProjectId) return this.toast('Seleziona un cantiere', 'error');
      const txt = (this.siteMessageInput?.value || '').trim();
      if(!txt) return;
      this.siteMessages?.insertAdjacentHTML('beforeend', `<div class="msg"><div class="who">Tu</div><div>${this.escapeHtml(txt)}</div></div>`);
      this.siteMessageInput.value = '';
      this.siteMessages.scrollTop = this.siteMessages.scrollHeight;
    });
    this.siteResetChatBtn?.addEventListener("click", () => {
      if (this.siteMessages) this.siteMessages.innerHTML = '<div class="msg"><div class="who">Assistant</div><div>Chat del cantiere resettata.</div></div>';
    });

    /* Modale nuovo cantiere */
    this.openCreateButtons.forEach(b => b.addEventListener('click', () => this.openModal('#projectModal')));
    this.projectForm?.addEventListener('submit', (e) => this.handleCreateProject(e));

    /* Service */
    this.resetDbBtn?.addEventListener("click", () => this.resetDatabase());

    /* Caricamento iniziale */
    this.loadCompanyOverview();
    this.refreshCompanyDocuments();          // lista documenti aziendali reale
    this.loadProjects().then(() => {
      this.renderProjectSelect();
      this.renderSitesList();
      this.applySiteSelection();
    });
  }

  /* ============================================================
   * KPI / Overview (da /api/company/overview)
   * ============================================================ */
  applyOverview(j) {
    if (this.kpiWorkers) this.kpiWorkers.textContent = j.workers_total ?? "—";
    if (this.kpiProjects) this.kpiProjects.textContent = j.projects_total ?? "—";
    if (this.kpiDocs) this.kpiDocs.textContent = j.documents_total ?? "—";
    if (this.kpiActiveProjects) this.kpiActiveProjects.textContent = j.active_projects ?? "—";
    if (this.kpiActiveWorkers) this.kpiActiveWorkers.textContent = j.active_workers ?? "—";

    if (this.rolesBreakdown) {
      this.rolesBreakdown.innerHTML = "";
      Object.entries(j.roles_breakdown || {}).forEach(([k, v]) => {
        const li = document.createElement("li");
        li.textContent = `${k}: ${v}`;
        this.rolesBreakdown.appendChild(li);
      });
    }

    if (this.activeProjects) {
      this.activeProjects.innerHTML = "";
      const list = j.active_projects_list || [];
      list.forEach((name) => {
        const li = document.createElement("li");
        li.textContent = name;
        this.activeProjects.appendChild(li);
      });
    }
  }

  async loadCompanyOverview() {
    try {
      const r = await fetch("/api/company/overview");
      const j = await r.json();
      this.applyOverview(j);
    } catch (err) {
      console.error("overview error:", err);
    }
  }

  /* ============================================================
   * Chat (Azienda)
   * ============================================================ */
  async handleSubmit(e) {
    e.preventDefault();
    if (this.state.sending) return;

    const message = (this.messageInput?.value || "").trim();
    if (!message) return;

    this.state.sending = true;

    // Mostra subito il messaggio utente e il loader
    this.addMessage("user", message);
    this.messageInput.value = "";
    const loadingId = this.addLoadingMessage();

    // Usa AbortController per evitare richieste "appese"
    const controller = new AbortController();
    const timeoutMs = 15000; // 15s
    const t = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const body = { message };
      if (this.state.currentProjectId) body.project_id = Number(this.state.currentProjectId);

      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal
      });

      const contentType = response.headers.get("content-type") || "";
      let data = null;

      if (contentType.includes("application/json")) {
        try {
          data = await response.json();
        } catch (jsonErr) {
          console.error("JSON parse error:", jsonErr);
          data = null;
        }
      } else {
        // prova a leggere testo per debug
        try {
          const raw = await response.text();
          console.warn("Non-JSON response:", raw?.slice(0, 500));
        } catch {}
      }

      this.removeMessage(loadingId);

      // Se HTTP non ok
      if (!response.ok) {
        const errMsg = (data && data.error) ? data.error : `HTTP ${response.status}`;
        this.addMessage("assistant", `Errore: ${this.escapeHtml(String(errMsg))}`);
        return;
      }

      // Se nessun JSON valido
      if (!data || typeof data !== "object") {
        this.addMessage("assistant", "Errore: risposta dal server non valida.");
        return;
      }

      // Se il backend ha messo un "error" esplicito
      if (data.error && !data.answer) {
        this.addMessage("assistant", `Errore: ${this.escapeHtml(String(data.error))}`);
        return;
      }

      // Rendering ricco standard (con fallback interno)
      this.addAssistantRichMessage(data);

      // Log utile per diagnostica
      console.debug("Chat response payload:", data);
    } catch (err) {
      this.removeMessage(loadingId);
      if (err?.name === "AbortError") {
        this.addMessage("assistant", "La richiesta ha impiegato troppo tempo. Riprova tra poco.");
      } else {
        this.addMessage("assistant", `Errore di connessione: ${this.escapeHtml(String(err.message || err))}`);
      }
      console.error("handleSubmit error:", err);
    } finally {
      clearTimeout(t);
      this.state.sending = false;
    }
  }

  addAssistantRichMessage(data) {
    // Robust: fallback, errori, dati non disponibili
    const parts = [];

    // 1) Testo principale
    let mainText = "";
    if (data && typeof data === "object" && "answer" in data && data.answer) {
      mainText = String(data.answer);
    } else if (data && typeof data === "object" && "error" in data && data.error) {
      mainText = "Errore: " + this.escapeHtml(String(data.error));
    } else if (data && typeof data === "object" && "detail" in data && data.detail) {
      mainText = this.escapeHtml(String(data.detail));
    } else if (!data) {
      mainText = "Dati non disponibili.";
    } else {
      mainText = "Nessuna risposta disponibile.";
    }
    const safe = this.escapeHtml(mainText).replace(/\n/g, "<br>");
    parts.push('<div class="assistant-answer"><p>' + safe + "</p></div>");

    // 2) Stima: supporta sia auto_estimate che estimate
    let est = (data && (data.auto_estimate || data.estimate)) || null;
    if (est && est.project) {
      let b = est.project.budget || {};
      let sum = est.project.summary || {};
      parts.push(
        '<div class="estimate-box">' +
          "<h4>🧮 Stima automatica</h4>" +
          '<ul class="compact">' +
            "<li><strong>Materiali:</strong> € " + (b.materials != null ? b.materials : "—") + "</li>" +
            "<li><strong>Manodopera:</strong> € " + (b.labor != null ? b.labor : "—") + "</li>" +
            "<li><strong>Totale:</strong> <strong>€ " + (b.total != null ? b.total : "—") + "</strong></li>" +
            "<li><strong>Ore totali:</strong> " + (sum.total_hours != null ? sum.total_hours : "—") + "</li>" +
            "<li><strong>Giorni (team 3):</strong> " + (sum.estimated_days != null ? sum.estimated_days : "—") + "</li>" +
          "</ul>" +
        "</div>"
      );
    }

    // 3) Fonti
    let local = (data && (data.local_sources || data.source_documents)) || [];
    let web = (data && data.web_sources) || [];

    // Fallback: se non sono array, forza array vuoto
    if (!Array.isArray(local)) local = [];
    if (!Array.isArray(web)) web = [];

    if ((local && local.length) || (web && web.length)) {
      let localHtml = "";
      if (local && local.length) {
        localHtml = "<h5>Interne</h5><ul>" + local.map(function(s, i) {
          let title = s && (s.title || "Documento");
          let snippet = s && s.snippet ? s.snippet : "";
          return (
            "<li><strong>[LOCAL " + (i + 1) + "]</strong> " +
            (title ? ChatApp.prototype.escapeHtml(String(title)) : "Documento") +
            (snippet ? " — <span class=\"muted\">" + ChatApp.prototype.escapeHtml(String(snippet)) + "</span>" : "") +
            "</li>"
          );
        }).join("") + "</ul>";
      }

      let webHtml = "";
      if (web && web.length) {
        webHtml = "<h5>Web</h5><ul>" + web.map(function(s, i) {
          let title = s && (s.title || s.url || "Fonte");
          let url = s && s.url ? s.url : "";
          let snippet = s && s.snippet ? s.snippet : "";
          let titleEsc = ChatApp.prototype.escapeHtml(String(title));
          let link = url ? '<a href="' + url + '" target="_blank" rel="noopener">' + titleEsc + "</a>" : titleEsc;
          return (
            "<li><strong>[WEB " + (i + 1) + "]</strong> " +
            link +
            (snippet ? " — <span class=\"muted\">" + ChatApp.prototype.escapeHtml(String(snippet)) + "</span>" : "") +
            "</li>"
          );
        }).join("") + "</ul>";
      }

      parts.push(
        '<div class="sources">' +
          "<h4>📚 Fonti</h4>" +
          (localHtml || "") +
          (webHtml || "") +
        "</div>"
      );
    }

    // Se non c'è nulla di utile, mostra fallback
    if (parts.length === 0 || (parts.length === 1 && !mainText)) {
      this.addMessage("assistant", "<p>Dati non disponibili.</p>");
    } else {
      this.addMessage("assistant", parts.join("\n"));
    }
  }

  /* ============================================================
   * Documenti AZIENDALI (server)
   * ============================================================ */
  async handleCompanyFileUpload(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    for (const f of files) {
      const fd = new FormData();
      fd.append('file', f);

      try {
        const r = await fetch('/api/company/documents', { method: 'POST', body: fd });
        const j = await r.json();
        if (!r.ok) {
          alert(j.error || 'Errore upload aziendale');
          continue;
        }

        // ✅ Aggiorna KPI con l’overview restituita
        this.applyOverview(j);

        // Rinfresca la lista reale dei documenti aziendali
        await this.refreshCompanyDocuments();
      } catch (err) {
        console.error('upload company doc error:', err);
        alert('Errore nel caricamento documento aziendale');
      }
    }

    this.fileInput.value = "";
  }

  async refreshCompanyDocuments() {
    if (!this.documentsList) return;
    try {
      const r = await fetch('/api/company/documents');
      const j = await r.json();
      const docs = j.documents || [];
      this.documentsList.innerHTML = docs.length
        ? docs.map(d => `<div class="doc-item">📄 ${this.escapeHtml(d.name)}</div>`).join('')
        : '<p class="no-docs">—</p>';
    } catch (err) {
      console.error('refresh company docs error:', err);
      this.documentsList.innerHTML = '<p class="no-docs">Errore nel caricamento documenti.</p>';
    }
  }

  /* ============================================================
   * Progetti / Documenti CANTIERE (server)
   * ============================================================ */
  async loadProjects() {
    try {
      const r = await fetch("/api/projects");
      const raw = await r.json();
      this.state.projects = Array.isArray(raw) ? raw : (raw.projects || []);
      this.renderProjectSelect();
      this.renderSitesList();

      // cards elenco (se presente)
      if (this.projectsList) {
        this.projectsList.innerHTML = "";
        this.state.projects.forEach((p) => {
          const card = document.createElement("div");
          card.className = "card project-card";
          card.innerHTML = `
            <h3>${this.escapeHtml(p.name)}</h3>
            <p>${this.escapeHtml(p.location_city || "")}</p>
            <p class="muted">${this.escapeHtml(p.start_date || "")} → ${this.escapeHtml(p.end_date || "in corso")}</p>
            <button class="btn sm" data-pid="${p.id}">Apri</button>
          `;
          this.projectsList.appendChild(card);
        });
        this.projectsList.querySelectorAll("button[data-pid]").forEach(btn=>{
          btn.addEventListener("click", ()=>{
            const p = this.state.projects.find(x=>String(x.id)===btn.dataset.pid);
            this.setCurrentProject(btn.dataset.pid, p?.name || "");
            this.syncProjectSelect();
            this.applySiteSelection();
          });
        });
      }
    } catch (err) {
      console.error("loadProjects error:", err);
    }
  }

  renderProjectSelect() {
    if (!this.projectSelect) return;
    this.projectSelect.innerHTML = '<option value="">— Nessuno —</option>' +
      this.state.projects.map(p => `<option value="${p.id}">${this.escapeHtml(p.name)}</option>`).join('');
    this.syncProjectSelect();
  }

  syncProjectSelect() {
    if (!this.projectSelect) return;
    const cur = this.state.currentProjectId || "";
    if (this.projectSelect.value !== cur) this.projectSelect.value = cur;
  }

  renderSitesList() {
    if (!this.sitesList) return;
    const cur = this.state.currentProjectId;
    this.sitesList.innerHTML = this.state.projects.map(p => `
      <div class="site-item ${String(p.id)===String(cur)?'active':''}" data-id="${p.id}">
        <div style="font-weight:600">${this.escapeHtml(p.name)}</div>
        <small>${this.escapeHtml(p.location_city||'')} — ${this.prettyStatus(p.status || p.stato || 'Preventivo')}</small>
      </div>
    `).join('');
    this.sitesList.querySelectorAll('.site-item').forEach(el=>{
      el.addEventListener('click', ()=>{
        const pid = el.dataset.id;
        const p = this.state.projects.find(x=>String(x.id)===String(pid));
        this.setCurrentProject(String(p.id), p.name);
        this.syncProjectSelect();
        this.applySiteSelection();
      });
    });
  }

  async handleSiteFilesUpload() {
    const pid = this.state.currentProjectId;
    if (!pid || !this.siteFileInput?.files?.length) return;

    const files = Array.from(this.siteFileInput.files);
    for (const f of files) {
      const fd = new FormData();
      fd.append('file', f);
      try {
        const r = await fetch(`/api/projects/${pid}/documents`, { method: 'POST', body: fd });
        const j = await r.json();
        if (!r.ok) {
          alert(j.error || 'Errore upload cantiere');
          continue;
        }
      } catch (err) {
        console.error('upload site doc error:', err);
        alert('Errore nel caricamento documento del cantiere');
      }
    }
    this.siteFileInput.value = "";
    await this.refreshSiteDocuments(); // ricarica lista dal server
    this.toast(`Aggiunti ${files.length} file.`, 'info');
  }

  async refreshSiteDocuments() {
    if (!this.siteDocumentsList) return;
    const pid = this.state.currentProjectId;
    if (!pid) { this.siteDocumentsList.innerHTML = '<p class="muted">—</p>'; return; }
    try {
      const r = await fetch(`/api/projects/${pid}/summary`);
      const j = await r.json();
      const docs = j.documents || [];
      this.siteDocumentsList.innerHTML = docs.length
        ? docs.map(n => `<div class="doc-row">📄 ${this.escapeHtml(n.name || n.path || "Documento")}</div>`).join('')
        : '<p class="muted">—</p>';
    } catch (err) {
      console.error('refresh site docs error:', err);
      this.siteDocumentsList.innerHTML = '<p class="muted">Errore nel caricamento documenti.</p>';
    }
  }

  /* ============================================================
   * Selezione cantiere / Toolbar / Badge
   * ============================================================ */
  setCurrentProject(id, name) {
    this.state.currentProjectId = id || "";
    this.state.currentProjectName = name || "";
    if (this.chatMeta) this.chatMeta.textContent = `Cantiere: ${this.state.currentProjectName || "—"}`;
  }

  async applySiteSelection() {
    const p = this.state.projects.find(x => String(x.id) === String(this.state.currentProjectId));
    // Header e meta
    if (this.siteHeader) this.siteHeader.textContent = p ? p.name : 'Nessun cantiere selezionato';
    if (this.siteChatMeta) this.siteChatMeta.textContent = p ? `Contesto: cantiere (${p.name})` : 'Contesto: cantiere (nessun cantiere selezionato)';

    // Badge + testo bottone toggle
    this.updateStatusControls(p);

    // Abilitazioni
    this.updateToolbar(p);

    // Documenti lista (server)
    await this.refreshSiteDocuments();

    // Lista cantieri (attivo)
    this.renderSitesList();

    // Chat placeholder quando nessun cantiere
    if (!p && this.siteMessages) {
      this.siteMessages.innerHTML = '<div class="msg"><div class="who">Assistant</div><div>Nessun cantiere selezionato.</div></div>';
    }

    // Toggle sezioni (niente documenti/chat se non selezionato)
    this.toggleSiteSections(!!p);
  }

  toggleSiteSections(visible) {
    const show = (el) => { if (el) el.style.display = 'block'; }
    const hide = (el) => { if (el) el.style.display = 'none'; }

    const docsCard = document.querySelector('.site-docs.card') || document.querySelector('.site-docs');
    const chatCard = document.querySelector('.site-chat .chat-card') || document.querySelector('.site-chat');

    if (visible) {
      show(docsCard); show(chatCard);
    } else {
      hide(docsCard); hide(chatCard);
    }
  }

  updateToolbar(p) {
    const has = !!p;
    if (this.btnClearSite) this.btnClearSite.disabled = !has;
    if (this.btnAssignWorker) this.btnAssignWorker.disabled = !has;
    if (this.btnDeleteProject) this.btnDeleteProject.style.display = has ? 'inline-flex' : 'none';
    if (this.btnCreateProjectTop) this.btnCreateProjectTop.style.display = has ? 'none' : 'inline-flex';
    if (this.btnToggleStatus) this.btnToggleStatus.style.display = has ? 'inline-flex' : 'none';
    if (this.siteUploadBtn) this.siteUploadBtn.disabled = !has;
  }

  prettyStatus(s) { return (s === 'Confermato') ? 'Confermato' : (s === 'Preventivo' ? 'Da approvare' : s); }
  isConfirmed(p){ return p && (p.status === 'Confermato' || p.stato === 'Confermato'); }

  updateStatusControls(p){
    if (!this.siteStatusBadge || !this.btnToggleStatus) return;
    if (!p) {
      this.siteStatusBadge.style.display='none';
      this.btnToggleStatus.style.display='none';
      return;
    }

    const confirmed = this.isConfirmed(p);
    this.btnToggleStatus.textContent = confirmed ? 'Segna come Da approvare' : 'Segna come Confermato';

    this.siteStatusBadge.style.display = 'inline-block';
    this.siteStatusBadge.textContent = this.prettyStatus(p.status || p.stato || 'Preventivo');
    this.siteStatusBadge.classList.remove('badge-confirmed','badge-pending');
    this.siteStatusBadge.classList.add(confirmed ? 'badge-confirmed' : 'badge-pending');
  }

  async toggleProjectStatus(){
    const pid = this.state.currentProjectId;
    if(!pid) return;

    try {
      const r = await fetch(`/api/projects/${pid}/status`, { method: 'POST' });
      const j = await r.json();
      if (!r.ok) {
        alert(j.error || 'Aggiornamento stato fallito');
        return;
      }

      // ✅ aggiorna KPI globali dall’overview che ritorna
      this.applyOverview(j);

      // aggiorna lo stato del progetto in cache
      const p = this.state.projects.find(x => String(x.id) === String(pid));
      if (p) {
        const was = (p.status || p.stato || 'Preventivo');
        const now = (was === 'Confermato') ? 'Preventivo' : 'Confermato';
        p.status = now;
        p.stato = now;
      }
      this.updateStatusControls(p);
      this.renderSitesList();
      this.toast(`Stato aggiornato`);
    } catch (err) {
      console.error('toggle status error', err);
      alert('Errore aggiornando lo stato del cantiere');
    }
  }

  /* ============================================================
   * Creazione / Eliminazione cantiere
   * ============================================================ */
  openModal(id){ document.querySelector(id)?.classList.add('open'); }
  closeModal(id){ document.querySelector(id)?.classList.remove('open'); }

  async handleCreateProject(e){
    e.preventDefault();
    const nome = document.getElementById('projName')?.value.trim();
    if(!nome) return alert('Inserisci un nome progetto.');
    const body = {
      name: nome,
      location_city: document.getElementById('projCity')?.value.trim(),
      start_date: document.getElementById('projStart')?.value || undefined,
      end_date: document.getElementById('projEnd')?.value || undefined,
      status: document.getElementById('projStatus')?.value || 'Preventivo'
    };
    try{
      const r = await fetch('/api/projects', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      const payload = await r.json().catch(()=>({}));
      if(!r.ok) throw new Error(payload.error || 'Creazione cantiere fallita');

      const proj = payload.project || payload;
      this.closeModal('#projectModal');
      await this.loadProjects();
      this.setCurrentProject(String(proj.id), proj.name);
      this.syncProjectSelect();
      this.applySiteSelection();
      this.toast(`Cantiere creato: ${proj.name}`);
    }catch(err){
      alert(`Errore: ${err.message}`);
    }
  }

  async handleDeleteProject(){
    const pid = this.state.currentProjectId;
    if(!pid) return;
    const p = this.state.projects.find(x=>String(x.id)===String(pid));
    if(!confirm(`Eliminare il cantiere "${p?.name||pid}"?`)) return;
    try{
      const r = await fetch(`/api/projects/${pid}`, { method:'DELETE' });
      const j = await r.json().catch(()=>({}));
      if(!r.ok) {
        throw new Error(j.error || 'Eliminazione fallita');
      }
      // aggiorna KPI (delete ritorna overview)
      this.applyOverview(j);

      // local cache
      this.state.projects = this.state.projects.filter(x=>String(x.id)!==String(pid));
      this.setCurrentProject('', '');
      this.renderProjectSelect();
      this.renderSitesList();
      this.applySiteSelection();
      this.toast('Cantiere eliminato');
    }catch(err){ alert(`Errore: ${err.message}`); }
  }

  /* ============================================================
   * Service actions
   * ============================================================ */
  async resetChat() {
    if (!confirm("Vuoi resettare la cronologia chat?")) return;
    try {
      await fetch("/api/reset-chat", { method: "POST" });
      if (this.messagesContainer) {
        this.messagesContainer.innerHTML = `
          <div class="message assistant">
            <div class="message-content">
              <strong>🤖 Assistant:</strong>
              <p>Chat resettata. Come posso aiutarti?</p>
            </div>
          </div>`;
      }
    } catch {
      alert("Errore durante il reset della chat");
    }
  }

  async resetDatabase() {
    if (!confirm("Vuoi eliminare tutti i documenti? Questa azione è irreversibile!")) return;
    try {
      const response = await fetch("/api/reset-db", { method: "POST" });
      const data = await response.json();
      if (response.ok) {
        alert("✅ Database resettato con successo!");
        this.refreshCompanyDocuments();
        this.loadCompanyOverview();
      } else {
        alert(`❌ Errore: ${data.error}`);
      }
    } catch {
      alert("Errore durante il reset del database");
    }
  }

  /* ============================================================
   * UI helpers messaggi & toast
   * ============================================================ */
  addMessage(role, content) {
    if (!this.messagesContainer) return;
    const id = `msg-${Date.now()}`;
    const icon = role === "user" ? "🧑‍💻" : "🤖";
    const label = role === "user" ? "Tu" : "Assistant";
    const inner = role === "assistant" ? content : `<p>${this.escapeHtml(content)}</p>`;
    const el = document.createElement("div");
    el.className = `message ${role}`; el.id = id;
    el.innerHTML = `
      <div class="message-content">
        <strong>${icon} ${label}:</strong>
        <div class="${role === "assistant" ? "assistant-html" : ""}">${inner}</div>
      </div>`;
    this.messagesContainer.appendChild(el);
    this.scrollToBottom();
    return id;
  }

  addLoadingMessage() {
    if (!this.messagesContainer) return '';
    const id = `loading-${Date.now()}`;
    const el = document.createElement("div");
    el.className = "message assistant"; el.id = id;
    el.innerHTML = `
      <div class="message-content">
        <strong>🤖 Assistant:</strong>
        <p><span class="loading"></span> Sto pensando…</p>
      </div>`;
    this.messagesContainer.appendChild(el);
    this.scrollToBottom(); return id;
  }

  removeMessage(id){ const el = document.getElementById(id); if (el) el.remove(); }
  scrollToBottom(){ this.messagesContainer && (this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight); }

  toast(msg, type='info'){
    let t = document.getElementById('toast');
    if(!t){
      t = document.createElement('div');
      t.id = 'toast';
      t.className = 'toast';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.background = (type==='error') ? '#b91c1c' : '#111827';
    t.classList.add('show');
    clearTimeout(this.__toastTimer);
    this.__toastTimer = setTimeout(()=>t.classList.remove('show'), 2200);
  }

  escapeHtml(text) { const div = document.createElement("div"); div.textContent = text ?? ""; return div.innerHTML; }
}

/* Sicurezza: intercetta errori JS globali e Promise non gestite */
window.addEventListener("error", (ev) => {
  try {
    console.error("Global error:", ev.error || ev.message);
    const app = window.App;
    if (app) app.toast("Errore imprevisto nell'interfaccia. Guarda la console.", "error");
  } catch {}
});
window.addEventListener("unhandledrejection", (ev) => {
  try {
    console.error("Unhandled promise rejection:", ev.reason);
    const app = window.App;
    if (app) app.toast("Errore di rete o risposta non valida.", "error");
  } catch {}
});

/* Avvio */
document.addEventListener("DOMContentLoaded", () => { new ChatApp(); });