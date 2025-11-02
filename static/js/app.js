/* static/js/app.js — versione migliorata e allineata alla nuova UI */
// Stati che permettono l'assegnazione (oltre a "Confermato")
const ASSIGNABLE_STATES = new Set(["Confermato","In corso","Attivo","Active"]);
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

    // Modale revisione lavori (bozze)
    this.reviewModal = document.getElementById("reviewModal");
    this.reviewProjectName = document.getElementById("reviewProjectName");
    this.reviewNotes = document.getElementById("reviewNotes");
    this.reviewRows = document.getElementById("reviewRows");
    this.reviewAddRow = document.getElementById("reviewAddRow");
    this.reviewSumMaterials = document.getElementById("reviewSumMaterials");
    this.reviewSumLabor = document.getElementById("reviewSumLabor");
    this.reviewSumTotal = document.getElementById("reviewSumTotal");
    this.btnDraftSave = document.getElementById("btnDraftSave");
    this.btnDraftCommit = document.getElementById("btnDraftCommit");
    this.btnDraftDiscard = document.getElementById("btnDraftDiscard");

    // Stato bozza corrente (solo lato UI)
    this.reviewState = { pid: "", draftId: "", scope: "", item: null };

    /* ------------------ Stato ------------------ */
    this.state = {
      currentProjectId: "",
      currentProjectName: "",
      sending: false,
      projects: [], // cache dei cantieri caricati
      siteHistory: {} // history chat per-cantiere (PID -> array di messaggi)
    };

    // Config performance/sicurezza per chat cantiere
    this.cfg = {
      SITE_MAX_MSG: 200,      // massimo messaggi persistiti/renderizzati per cantiere
      SITE_MAX_SOURCES: 3,    // massimo fonti mostrate per messaggio
      SITE_MAX_SNIPPET: 200,  // massimo lunghezza snippet fonte
      SITE_MAX_TITLE: 100     // massimo lunghezza titolo fonte
    };

    /** ----------- Calcolo strutturato (calc_json): parse & render ----------- */
    this.extractCalcJson = (markdown) => {
      if (!markdown) return null;
      const re = /```calc_json\s*([\s\S]*?)```/i;
      const m = re.exec(markdown);
      if (!m) return null;
      try {
        const obj = JSON.parse(m[1]);
        return obj && typeof obj === 'object' ? obj : null;
      } catch {
        return null;
      }
    };

    this.fmt = (n) => {
      const x = Number(n);
      return Number.isFinite(x)
        ? x.toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
    };

    this.renderCalcTables = (calc) => {
      const mats = Array.isArray(calc?.materials) ? calc.materials : [];
      const labor = Array.isArray(calc?.labor) ? calc.labor : [];
      const totals = calc?.totals || {};

      const matRows = mats.map(r => (
        `
          <tr>
            <td>${this.escapeHtml(r.code || '')}</td>
            <td>${this.escapeHtml(r.desc || r.description || '')}</td>
            <td style="text-align:right">${this.fmt(r.qty)}</td>
            <td>${this.escapeHtml(r.unit || r.uom || '')}</td>
            <td style="text-align:right">€ ${this.fmt(r.unit_price || r.price || 0)}</td>
            <td style="text-align:right">€ ${this.fmt(r.total || 0)}</td>
          </tr>
        `
      )).join('');

      const labRows = labor.map(r => (
        `
          <tr>
            <td>${this.escapeHtml(r.role || '')}</td>
            <td style="text-align:right">${this.fmt(r.hours || r.qty)}</td>
            <td style="text-align:right">€ ${this.fmt(r.hourly || r.rate || 0)}</td>
            <td style="text-align:right">€ ${this.fmt(r.total || 0)}</td>
          </tr>
        `
      )).join('');

      return (
        `
          <div class="card" style="margin-top:10px">
            <h4 style="margin:0 0 8px 0">Riepilogo calcolo — ${this.escapeHtml(calc.scope || calc.work || 'lavoro')}</h4>
            <div style="overflow:auto">
              <table style="width:100%; border-collapse:collapse; margin:8px 0">
                <thead>
                  <tr style="background:#f3f4f6">
                    <th style="text-align:left; padding:6px; border:1px solid var(--border)">Codice</th>
                    <th style="text-align:left; padding:6px; border:1px solid var(--border)">Descrizione</th>
                    <th style="text-align:right; padding:6px; border:1px solid var(--border)">Qty</th>
                    <th style="text-align:left; padding:6px; border:1px solid var(--border)">Unità</th>
                    <th style="text-align:right; padding:6px; border:1px solid var(--border)">€/unit</th>
                    <th style="text-align:right; padding:6px; border:1px solid var(--border)">Totale</th>
                  </tr>
                </thead>
                <tbody>
                  ${matRows || `<tr><td colspan="6" style="padding:6px;border:1px solid var(--border);text-align:center" class="muted">— Nessun materiale —</td></tr>`}
                </tbody>
              </table>
            </div>
            <div style="overflow:auto">
              <table style="width:100%; border-collapse:collapse; margin:8px 0">
                <thead>
                  <tr style="background:#f3f4f6">
                    <th style="text-align:left; padding:6px; border:1px solid var(--border)">Ruolo</th>
                    <th style="text-align:right; padding:6px; border:1px solid var(--border)">Ore</th>
                    <th style="text-align:right; padding:6px; border:1px solid var(--border)">€/ora</th>
                    <th style="text-align:right; padding:6px; border:1px solid var(--border)">Totale</th>
                  </tr>
                </thead>
                <tbody>
                  ${labRows || `<tr><td colspan="4" style="padding:6px;border:1px solid var(--border);text-align:center" class="muted">— Nessuna manodopera —</td></tr>`}
                </tbody>
              </table>
            </div>
            <div style="margin-top:6px; display:flex; gap:12px; flex-wrap:wrap">
              <div class="badge">Materiali: <strong style="margin-left:6px">€ ${this.fmt(totals.materials || 0)}</strong></div>
              <div class="badge">Manodopera: <strong style="margin-left:6px">€ ${this.fmt(totals.labor || 0)}</strong></div>
              <div class="badge">Totale: <strong style="margin-left:6px">€ ${this.fmt(totals.total || ((totals.materials||0)+(totals.labor||0)))}</strong></div>
            </div>
          </div>
        `
      );
    };

    this.appendCalcCard = (calc, pid) => {
      if (!this.siteMessages) return;

      const wrapper = document.createElement('div');
      wrapper.className = 'msg assistant';
      const uid = `calc-${Date.now()}`;
      wrapper.id = uid;

      // Pulsanti azione
      const actions = `
        <div class="actions-row" style="margin-top:8px; display:flex; gap:8px; flex-wrap:wrap">
          <button class="btn primary" data-action="commit">Aggiungi al cantiere</button>
          <button class="btn" data-action="draft">Salva come bozza</button>
          <button class="btn ghost" data-action="review">Revisiona</button>
        </div>
      `;

      wrapper.innerHTML = `
        <div class="who">Assistant</div>
        <div>
          ${this.renderCalcTables(calc)}
          ${actions}
        </div>
      `;
      this.siteMessages.appendChild(wrapper);
      this.siteMessages.scrollTop = this.siteMessages.scrollHeight;

      const toPayload = (c) => ({
        scope: c.scope || c.work || 'lavoro',
        materials: (c.materials || []).map(m => ({
          code: m.code || null,
          desc: m.desc || m.description || '',
          qty: Number(m.qty || 0),
          unit: m.unit || m.uom || '',
          unit_price: Number(m.unit_price || m.price || 0),
          total: Number(m.total || 0),
        })),
        labor: (c.labor || []).map(l => ({
          role: l.role || '',
          hours: Number(l.hours || l.qty || 0),
          hourly: Number(l.hourly || l.rate || 0),
          total: Number(l.total || 0),
        })),
        totals: {
          materials: Number((c.totals && c.totals.materials) || 0),
          labor: Number((c.totals && c.totals.labor) || 0),
          total: Number((c.totals && c.totals.total) || ((c.totals?.materials||0)+(c.totals?.labor||0))),
        }
      });

      // Listener Commit immediato
      wrapper.querySelector('[data-action="commit"]')?.addEventListener('click', async () => {
        try {
          const payload = { items: [toPayload(calc)] };
          const res = await fetch(`/api/projects/${pid}/works/bulk`, {
            method: 'POST',
            headers: { 'Content-Type':'application/json' },
            body: JSON.stringify(payload)
          });
          const j = await res.json().catch(()=>({}));
          if (!res.ok) throw new Error(j.error || 'Errore server');
          this.toast('Lavoro aggiunto al cantiere', 'success');
        } catch (e) {
          console.error(e);
          this.toast('Errore durante il salvataggio', 'error');
        }
      });

      // Listener Bozza
      wrapper.querySelector('[data-action="draft"]')?.addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/projects/${pid}/works/draft`, {
            method: 'POST',
            headers: { 'Content-Type':'application/json' },
            body: JSON.stringify({ item: toPayload(calc) })
          });
          const j = await res.json().catch(()=>({}));
          if (!res.ok) throw new Error(j.error || 'Errore server');
          const draftId = j.draft_id || j.id || '';
          this.toast(draftId ? `Bozza salvata (#${draftId})` : 'Bozza salvata', 'info');
        } catch (e) {
          console.error(e);
          this.toast('Errore salvando la bozza', 'error');
        }
      });

      // Listener Revisiona → apre il modale con i dati precompilati
      wrapper.querySelector('[data-action="review"]')?.addEventListener('click', () => {
        this.openReviewModal(pid, calc);
      });
    };

  // ===================== REVIEW MODAL: helpers =====================
  this.openReviewModal = (pid, calcOrDraft) => {
    if (!this.reviewModal) return;
    const p = this.getCurrentProject();
    this.reviewState = { pid: String(pid||this.state.currentProjectId||""), draftId: "", scope: (calcOrDraft?.scope||calcOrDraft?.work||"lavoro"), item: null };

    if (this.reviewProjectName) this.reviewProjectName.textContent = p ? p.name : '—';
    if (this.reviewNotes) this.reviewNotes.value = (calcOrDraft?.notes || "");

    // Pulisci righe
    if (this.reviewRows) this.reviewRows.innerHTML = '';

    // Materiali
    const mats = Array.isArray(calcOrDraft?.materials) ? calcOrDraft.materials : [];
    for (const m of mats){
      this.addReviewRow({
        kind: 'material',
        code: m.code||'', descr: m.desc||m.description||'',
        category: 'Materiale', qty: Number(m.qty||0), unit: m.unit||m.uom||'', unit_price: Number(m.unit_price||m.price||0),
      });
    }
    // Manodopera
    const labs = Array.isArray(calcOrDraft?.labor) ? calcOrDraft.labor : [];
    for (const l of labs){
      this.addReviewRow({
        kind: 'labor',
        code: l.role||'', descr: 'Manodopera',
        category: 'Manodopera', qty: Number(l.hours||l.qty||0), unit: 'h', unit_price: Number(l.hourly||l.rate||0),
      });
    }

    this.recomputeReviewTotals();
    this.openModal('#reviewModal');
  };

  this.addReviewRow = (row) => {
    if (!this.reviewRows) return;
    const r = Object.assign({ kind:'material', code:'', descr:'', category:'Materiale', qty:0, unit:'', unit_price:0 }, row||{});
    const tr = document.createElement('tr');

    const tdVoce = document.createElement('td');
    const inVoce = document.createElement('input'); inVoce.type='text'; inVoce.value=r.code; inVoce.className='inp';
    tdVoce.appendChild(inVoce);

    const tdCat = document.createElement('td');
    const selCat = document.createElement('select');
    ['Materiale','Manodopera'].forEach(opt=>{ const o=document.createElement('option'); o.value=opt; o.textContent=opt; selCat.appendChild(o); });
    selCat.value = r.category;
    tdCat.appendChild(selCat);

    const tdQty = document.createElement('td'); tdQty.style.textAlign='right';
    const inQty = document.createElement('input'); inQty.type='number'; inQty.step='0.01'; inQty.value=String(r.qty);
    tdQty.appendChild(inQty);

    const tdUnit = document.createElement('td');
    const inUnit = document.createElement('input'); inUnit.type='text'; inUnit.value=r.unit; inUnit.className='inp';
    tdUnit.appendChild(inUnit);

    const tdPrice = document.createElement('td'); tdPrice.style.textAlign='right';
    const inPrice = document.createElement('input'); inPrice.type='number'; inPrice.step='0.01'; inPrice.value=String(r.unit_price);
    tdPrice.appendChild(inPrice);

    const tdTot = document.createElement('td'); tdTot.style.textAlign='right';
    const spanTot = document.createElement('span'); spanTot.textContent='0'; tdTot.appendChild(spanTot);

    const tdAct = document.createElement('td'); tdAct.style.textAlign='center';
    const btnDel = document.createElement('button'); btnDel.type='button'; btnDel.className='btn sm'; btnDel.textContent='✕';
    btnDel.addEventListener('click', ()=>{ tr.remove(); this.recomputeReviewTotals(); });
    tdAct.appendChild(btnDel);

    tr.appendChild(tdVoce); tr.appendChild(tdCat); tr.appendChild(tdQty); tr.appendChild(tdUnit); tr.appendChild(tdPrice); tr.appendChild(tdTot); tr.appendChild(tdAct);

    [inVoce, selCat, inQty, inUnit, inPrice].forEach(el=>{
      el.addEventListener('input', ()=> this.recomputeReviewTotals());
      el.addEventListener('change', ()=> this.recomputeReviewTotals());
    });

    this.reviewRows.appendChild(tr);
  };

  this.recomputeReviewTotals = () => {
    if (!this.reviewRows) return;
    let sumM = 0, sumL = 0;
    const rows = Array.from(this.reviewRows.querySelectorAll('tr'));
    for (const tr of rows){
      const [inVoce, selCat, inQty, inUnit, inPrice] = tr.querySelectorAll('input, select');
      const qty = Number(inQty?.value||0); const price = Number(inPrice?.value||0);
      const tot = qty*price; const spanTot = tr.querySelector('td:nth-child(6) span'); if (spanTot) spanTot.textContent = this.fmt(tot);
      const cat = selCat?.value||'Materiale';
      if (cat === 'Manodopera') sumL += tot; else sumM += tot;
    }
    const sumT = sumM + sumL;
    if (this.reviewSumMaterials) this.reviewSumMaterials.textContent = this.fmt(sumM);
    if (this.reviewSumLabor) this.reviewSumLabor.textContent = this.fmt(sumL);
    if (this.reviewSumTotal) this.reviewSumTotal.textContent = this.fmt(sumT);
  };

  this.collectReviewData = () => {
    const scope = this.reviewState.scope || 'lavoro';
    const notes = this.reviewNotes ? String(this.reviewNotes.value||'') : '';
    const mats = []; const labs = [];
    const rows = this.reviewRows ? Array.from(this.reviewRows.querySelectorAll('tr')) : [];
    for (const tr of rows){
      const [inVoce, selCat, inQty, inUnit, inPrice] = tr.querySelectorAll('input, select');
      const code = String(inVoce?.value||'');
      const category = String(selCat?.value||'Materiale');
      const qty = Number(inQty?.value||0); const unit = String(inUnit?.value||''); const unit_price = Number(inPrice?.value||0);
      const row = { code, desc: code, qty, unit, unit_price, total: qty*unit_price };
      if (category === 'Manodopera') {
        labs.push({ role: code||'operaio', hours: qty, hourly: unit_price, total: qty*unit_price });
      } else {
        mats.push(row);
      }
    }
    const totals = {
      materials: mats.reduce((a,b)=>a+Number(b.total||0),0),
      labor: labs.reduce((a,b)=>a+Number(b.total||0),0),
    };
    totals.total = totals.materials + totals.labor;
    return { scope, notes, materials: mats, labor: labs, totals };
  };

  this.handleDraftSave = async () => {
    const pid = this.reviewState.pid || this.state.currentProjectId;
    if (!pid) return this.toast('Seleziona un cantiere', 'error');
    const item = this.collectReviewData();

    try{
      let res, j;
      if (this.reviewState.draftId){
        res = await fetch(`/api/projects/${pid}/works/draft/${this.reviewState.draftId}`,{ method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ item }) });
        j = await res.json().catch(()=>({}));
        if (!res.ok) throw new Error(j.error||'Patch bozza fallita');
        this.toast('Bozza aggiornata', 'success');
      } else {
        res = await fetch(`/api/projects/${pid}/works/draft`,{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ item }) });
        j = await res.json().catch(()=>({}));
        if (!res.ok) throw new Error(j.error||'Creazione bozza fallita');
        this.reviewState.draftId = j.draft_id||'';
        this.toast(`Bozza salvata #${this.reviewState.draftId||''}`, 'success');
      }
    }catch(e){
      console.error(e); this.toast(e.message||'Errore bozza', 'error');
    }
  };

  this.handleDraftCommit = async () => {
    const pid = this.reviewState.pid || this.state.currentProjectId;
    if (!pid) return this.toast('Seleziona un cantiere', 'error');
    try{
      if (!this.reviewState.draftId){
        await this.handleDraftSave();
        if (!this.reviewState.draftId) throw new Error('Bozza non disponibile');
      }
      const res = await fetch(`/api/projects/${pid}/works/commit/${this.reviewState.draftId}`, { method:'POST' });
      const j = await res.json().catch(()=>({}));
      if (!res.ok) throw new Error(j.error||'Commit fallito');
      this.toast('Bozza confermata nel cantiere', 'success');
      this.closeModal('#reviewModal');
      const r2 = await fetch(`/api/projects/${pid}`);
      const pj2 = await r2.json().catch(()=>null);
      if (r2.ok && pj2) {
        const idx = (this.state.projects||[]).findIndex(x => String(x.id)===String(pid));
        if (idx >= 0) this.state.projects[idx] = pj2;
        this.applySiteSelection();
      }
    }catch(e){ console.error(e); this.toast(e.message||'Errore commit', 'error'); }
  };

  this.handleDraftDiscard = async () => {
    const pid = this.reviewState.pid || this.state.currentProjectId;
    if (!pid) return this.toast('Seleziona un cantiere', 'error');
    if (!this.reviewState.draftId){ this.toast('Nessuna bozza da scartare', 'warning'); return; }
    try{
      const res = await fetch(`/api/projects/${pid}/works/draft/${this.reviewState.draftId}`,{ method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ status: 'discarded' }) });
      const j = await res.json().catch(()=>({}));
      if (!res.ok) throw new Error(j.error||'Scarto bozza fallito');
      this.toast('Bozza scartata', 'info');
      this.closeModal('#reviewModal');
    }catch(e){ console.error(e); this.toast(e.message||'Errore scarto', 'error'); }
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
    /* Assegna operai (CTA che muta: Pianifica → Assegna) */
this.btnAssignWorker?.addEventListener("click", async () => {
  const pid = this.state?.currentProjectId;
  if (!pid) return this.toast('Seleziona un cantiere', 'error');

  const pj = this.getCurrentProject();
  const mode = this.btnAssignWorker?.dataset?.mode || 'plan';

  const run = async (label, fn) => {
    const btn = this.btnAssignWorker;
    const old = btn.textContent;
    btn.disabled = true; btn.textContent = label + '…';
    try { await fn(); this.toast(label + ' ok', 'success'); }
    catch (e) { alert(`${label} fallita: ${e?.message || e}`); }
    finally { btn.disabled = false; btn.textContent = old; }
  };

  if (mode === 'plan') {
    await run('Pianificazione', async () => {
      const res = await fetch(`/api/projects/${pid}/plan`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ start_from: 'auto', replace: true })
      });
      const j = await res.json().catch(()=>({}));
      if (!res.ok) throw new Error(j.error || 'Errore server');

      // ricarica progetto per riflettere le date pianificate
      const r2 = await fetch(`/api/projects/${pid}`);
      const pj2 = await r2.json().catch(()=>null);
      if (r2.ok && pj2) {
        const idx = (this.state.projects||[]).findIndex(x => String(x.id)===String(pid));
        if (idx >= 0) this.state.projects[idx] = pj2;
      }
      this.updateAssignCta();
    });
    return;
  }

  // mode === 'assign'
  const st = (pj?.status || pj?.stato || '').trim();
  if (!ASSIGNABLE_STATES.has(st)) {
    return this.toast('Per assegnare imposta lo stato a "Confermato", "In corso" o "Attivo"', 'warning');
  }

  await run('Assegnazione', async () => {
    const res = await fetch(`/api/projects/${pid}/schedule/assign`, { method: 'POST' });
    const j = await res.json().catch(()=>({}));
    if (!res.ok) throw new Error(j.error || 'Errore server');

    // Riepilogo: quanti slot assegnati e cosa manca (dipendenti già impegnati, ruoli non coperti)
    const assigned = (typeof j.assigned === 'number') ? j.assigned : (Array.isArray(j.assigned) ? j.assigned.length : 0);
    const deficits = Array.isArray(j.deficits) ? j.deficits : [];
    if (deficits.length) {
      const byRole = {};
      for (const d of deficits) {
        const key = (d.role || d.work_code || 'ruolo').toString();
        // sommiamo le carenze (needed-found) per ruolo
        const miss = Math.max(0, (d.needed||1) - (d.found||0)) || 1;
        byRole[key] = (byRole[key] || 0) + miss;
      }
      const parts = Object.entries(byRole).map(([k,v]) => `${k}: ${v}`);
      this.toast(`Assegnati ${assigned}. Mancano → ${parts.join(' | ')}`, 'warning');
    } else {
      this.toast(`Assegnati ${assigned} slot.`, 'success');
    }

    // ricarica progetto per vedere assignments/meta aggiornati
    const r2 = await fetch(`/api/projects/${pid}`);
    const pj2 = await r2.json().catch(()=>null);
    if (r2.ok && pj2) {
      const idx = (this.state.projects||[]).findIndex(x => String(x.id)===String(pid));
      if (idx >= 0) this.state.projects[idx] = pj2;
    }
    this.updateAssignCta();

    // ridisegna intestazione e pannelli cantiere
    this.applySiteSelection();
  });
});

    /* Review modal listeners */
    this.reviewAddRow?.addEventListener('click', () => this.addReviewRow());
    this.btnDraftSave?.addEventListener('click', () => this.handleDraftSave());
    this.btnDraftCommit?.addEventListener('click', () => this.handleDraftCommit());
    this.btnDraftDiscard?.addEventListener('click', () => this.handleDraftDiscard());

    /* Upload documenti CANTIERE (server) */
    this.siteUploadBtn?.addEventListener("click", () => this.siteFileInput?.click());
    this.siteFileInput?.addEventListener("change", () => this.handleSiteFilesUpload());

    /* Chat cantiere (server + history per PID) */
    this.siteChatForm?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const pid = this.state.currentProjectId;
      if (!pid) return this.toast('Seleziona un cantiere', 'error');

      const txt = (this.siteMessageInput?.value || '').trim();
      if (!txt) return;

      // optimistic UI
      this.addSiteMessage("user", txt, pid);
      this.siteMessageInput.value = '';
      this.siteMessages && (this.siteMessages.scrollTop = this.siteMessages.scrollHeight);

      try {
        const r = await fetch(`/api/chat/project/${encodeURIComponent(pid)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ message: txt })
        });
        let data = null;
        const ct = r.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
          try { data = await r.json(); } catch (_) { data = null; }
        } else {
          try { await r.text(); } catch (_) {}
        }

        if (!r.ok) {
          const errMsg = (data && data.error) ? String(data.error) : `HTTP ${r.status}`;
          this.addSiteMessage('assistant', `Errore: ${this.escapeHtml(errMsg)}`, pid);
          this.saveSiteHistory(pid);
          return;
        }

        const reply = (data && (data.reply || data.answer || data.text)) || 'OK';
        const sources = (data && (data.sources || data.web_sources || data.local_sources)) || [];
        this.addSiteMessage('assistant', reply, pid, Array.isArray(sources) ? sources : []);
        this.saveSiteHistory(pid);

        // Se la risposta contiene un blocco ```calc_json``` renderizza tabelle + azioni
        const calc = this.extractCalcJson(reply);
        if (calc) {
          this.appendCalcCard(calc, pid);
        }
      } catch (err) {
        console.error('chat cantiere error:', err);
        this.addSiteMessage('assistant', '⚠️ Errore durante la risposta del server.', pid);
        this.saveSiteHistory(pid);
      }
    });

    this.siteResetChatBtn?.addEventListener("click", () => {
      const pid = this.state.currentProjectId;
      if (!pid) return;
      try { localStorage.removeItem(`site_chat_${pid}`); } catch (_) {}
      if (!this.state.siteHistory) this.state.siteHistory = {};
      this.state.siteHistory[pid] = [];
      if (this.siteMessages) this.siteMessages.innerHTML = '<div class="msg assistant"><div class="who">Assistant</div><div>Chat del cantiere resettata.</div></div>';
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
    // Avvio analytics sicuro (non blocca mai la UI)
    this.initAnalyticsSafe();
    // Allinea subito la CTA in base allo stato corrente/selezione
    this.updateAssignCta();
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
    // Aggiorna CTA Pianifica/Assegna in base allo stato attuale
    this.updateAssignCta();

    // Documenti lista (server)
    this.refreshSiteDocuments().catch(()=>{});

    // Lista cantieri (attivo)
    this.renderSitesList();

    // Chat: carica la history del cantiere selezionato
    if (p) {
      this.renderSiteHistory(String(p.id));
    }

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

  // ——— CTA mutante Pianifica/Assegna ———
  getCurrentProject(){
    const pid = this.state?.currentProjectId;
    if (!pid) return null;
    return (this.state.projects || []).find(x => String(x.id) === String(pid)) || null;
  }

  isProjectPlanned(pj){
    const works = pj?.works || pj?.meta?.works || [];
    return works.some(w => {
      if (!w) return false;
      const s = w.start_date_planned || w.start_planned || w.start_date;
      const e = w.end_date_planned || w.end_planned || w.end_date;
      return Boolean(s || e);
    });
  }

  updateAssignCta(){
    const btn = this.btnAssignWorker;
    if (!btn) return;

    const pj = this.getCurrentProject();
    if (!pj) {
      btn.textContent = 'Pianifica';
      btn.disabled = true;
      btn.title = 'Seleziona un cantiere';
      btn.dataset.mode = 'plan';
      return;
    }

    // Normalizza stato e verifica
    const raw = (pj.status ?? pj.stato ?? '').toString().trim();
    const alias = (raw === 'Active') ? 'Attivo' : raw;
    const canAssign = ASSIGNABLE_STATES.has(raw) || ASSIGNABLE_STATES.has(alias);
    const planned = this.isProjectPlanned(pj);

    if (!canAssign) {
      btn.textContent = 'Pianifica';
      btn.disabled = false;
      btn.title = 'Per assegnare porta lo stato a "Confermato", "In corso" o "Attivo"';
      btn.dataset.mode = 'plan';
      return;
    }

    if (!planned) {
      btn.textContent = 'Pianifica';
      btn.disabled = false;
      btn.title = 'Calcola le date dei lavori dal catalogo';
      btn.dataset.mode = 'plan';
      return;
    }

    btn.textContent = 'Assegna operai';
    btn.disabled = false;
    btn.title = 'Assegna la squadra sui lavori pianificati';
    btn.dataset.mode = 'assign';
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
      this.updateAssignCta();
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

    const wrap = document.createElement('div');
    wrap.className = `msg ${role === 'user' ? 'user' : 'assistant'}`;
    wrap.id = id;

    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = role === 'user' ? 'Tu' : 'Assistant';
    wrap.appendChild(who);

    const bubble = document.createElement('div');
    if (role === 'assistant') {
      // `content` per i messaggi assistant può già contenere HTML (sanitizzato a monte)
      bubble.innerHTML = content;
    } else {
      // messaggi utente sempre escaped
      bubble.textContent = String(content ?? '');
    }
    wrap.appendChild(bubble);

    this.messagesContainer.appendChild(wrap);
    this.scrollToBottom();
    return id;
  }

  addLoadingMessage() {
    if (!this.messagesContainer) return '';
    const id = `loading-${Date.now()}`;

    const wrap = document.createElement('div');
    wrap.className = 'msg assistant';
    wrap.id = id;

    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = 'Assistant';
    wrap.appendChild(who);

    const bubble = document.createElement('div');
    bubble.innerHTML = '<span class="loading"></span> Sto pensando…';
    wrap.appendChild(bubble);

    this.messagesContainer.appendChild(wrap);
    this.scrollToBottom();
    return id;
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

  /* ============================================================
   * Chat CANTIERE: helpers per-history PID
   * ============================================================ */
  addSiteMessage(role, text, pid, sources = []) {
    if (!this.state.siteHistory) this.state.siteHistory = {};
    if (!this.state.siteHistory[pid]) this.state.siteHistory[pid] = [];

    // normalizza/limita le fonti
    const normSources = (Array.isArray(sources) ? sources : []).slice(0, this.cfg.SITE_MAX_SOURCES).map((s) => ({
      title: String(s?.title || s?.source || s?.url || 'Fonte').slice(0, this.cfg.SITE_MAX_TITLE),
      url: s?.url ? String(s.url) : '',
      snippet: String(s?.snippet || s?.text || '').slice(0, this.cfg.SITE_MAX_SNIPPET)
    }));

    const item = { role, text: String(text), ts: Date.now(), sources: normSources };

    // append in memoria e taglia agli ultimi N
    this.state.siteHistory[pid].push(item);
    if (this.state.siteHistory[pid].length > this.cfg.SITE_MAX_MSG) {
      this.state.siteHistory[pid] = this.state.siteHistory[pid].slice(-this.cfg.SITE_MAX_MSG);
    }

    // render incrementale minimal
    if (this.siteMessages) {
      const who = role === 'user' ? 'Tu' : 'Assistant';
      const srcHtml = normSources.length
        ? `<div class="sources">${normSources.map((s, i) => {
            const url = s.url ? ` <a href="${this.escapeHtml(s.url)}" target="_blank" rel="noopener">link</a>` : '';
            const snip = s.snippet ? ` — <span class=\"muted\">${this.escapeHtml(s.snippet)}</span>` : '';
            return `<div><strong>[${i+1}]</strong> ${this.escapeHtml(s.title)}${url}${snip}</div>`;
          }).join('')}</div>`
        : '';

      this.siteMessages.insertAdjacentHTML(
        'beforeend',
        `<div class="msg ${role}">
          <div class="who">${who}</div>
          <div>${this.escapeHtml(String(item.text))}</div>
          ${srcHtml}
        </div>`
      );
      this.siteMessages.scrollTop = this.siteMessages.scrollHeight;
    }
  }

  saveSiteHistory(pid) {
    try {
      const arr = Array.isArray(this.state.siteHistory?.[pid]) ? this.state.siteHistory[pid] : [];
      const trimmed = arr.slice(-this.cfg.SITE_MAX_MSG);
      localStorage.setItem(`site_chat_${pid}`, JSON.stringify(trimmed));
    } catch (_) {}
  }

  loadSiteHistory(pid) {
    if (!pid) return [];
    try {
      const raw = localStorage.getItem(`site_chat_${pid}`);
      if (!raw) return [];
      // Protezione da blob giganteschi (es. > 2MB)
      if (raw.length > 2_000_000) {
        console.warn('History troppo grande, resetto per pid=', pid);
        localStorage.removeItem(`site_chat_${pid}`);
        return [];
      }
      let arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      if (arr.length > this.cfg.SITE_MAX_MSG * 3) {
        arr = arr.slice(-this.cfg.SITE_MAX_MSG * 3);
      }
      return arr;
    } catch (_) {
      return [];
    }
  }

  renderSiteHistory(pid) {
    if (!this.siteMessages) return;
    if (!this.state.siteHistory) this.state.siteHistory = {};

    const items = this.loadSiteHistory(pid);
    const recent = Array.isArray(items) ? items.slice(-this.cfg.SITE_MAX_MSG) : [];
    this.state.siteHistory[pid] = recent;

    const container = this.siteMessages;
    container.innerHTML = '';

    if (!recent.length) {
      container.innerHTML = '<div class="msg assistant"><div class="who">Assistant</div><div>Nessun messaggio per questo cantiere.</div></div>';
      return;
    }

    let i = 0;
    const chunk = 30; // renderizza 30 messaggi per frame

    const renderChunk = () => {
      const end = Math.min(i + chunk, recent.length);
      const frag = document.createDocumentFragment();
      for (; i < end; i++) {
        const m = recent[i] || {};
        const div = document.createElement('div');
        div.className = `msg ${m.role || 'assistant'}`;

        const who = document.createElement('div');
        who.className = 'who';
        who.textContent = (m.role === 'user') ? 'Tu' : 'Assistant';
        div.appendChild(who);

        const text = document.createElement('div');
        text.textContent = String(m.text || '');
        div.appendChild(text);

        const srcs = Array.isArray(m.sources) ? m.sources.slice(0, this.cfg.SITE_MAX_SOURCES) : [];
        if (srcs.length) {
          const sdiv = document.createElement('div');
          sdiv.className = 'sources';
          srcs.forEach((s, idx) => {
            const row = document.createElement('div');
            const title = String(s?.title || s?.source || s?.url || 'Fonte').slice(0, this.cfg.SITE_MAX_TITLE);
            const url = s?.url ? ` <a href="${this.escapeHtml(String(s.url))}" target="_blank" rel="noopener">link</a>` : '';
            const snippet = String(s?.snippet || s?.text || '').slice(0, this.cfg.SITE_MAX_SNIPPET);
            const snipHtml = snippet ? ` — <span class=\"muted\">${this.escapeHtml(snippet)}</span>` : '';
            row.innerHTML = `<strong>[${idx + 1}]</strong> ${this.escapeHtml(title)}${url}${snipHtml}`;
            sdiv.appendChild(row);
          });
          div.appendChild(sdiv);
        }

        frag.appendChild(div);
      }
      container.appendChild(frag);
      container.scrollTop = container.scrollHeight;
      if (i < recent.length) requestAnimationFrame(renderChunk);
    };

    requestAnimationFrame(renderChunk);
  }

  /* ============================================================
   * Analytics (sempre ON, ma a prova di crash)
   * ============================================================ */
  initAnalyticsSafe() {
    const run = async () => {
      try {
        const url = this.makeUrl('/analytics/reports/latest');
        const data = await this.safeFetchJson(url, { timeoutMs: 6000 });
        if (!data || typeof data !== 'object' || Object.keys(data).length === 0) {
          console.info('[analytics] Nessun dato o endpoint non disponibile → skip');
          return;
        }
        // Disegna solo quando il DOM è pronto
        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', () => this.drawAnalyticsChartsSafe(data), { once: true });
        } else {
          this.drawAnalyticsChartsSafe(data);
        }
      } catch (e) {
        console.warn('[analytics] init error:', e);
      }
    };

    // Esegui in idle per non bloccare la UI
    if ('requestIdleCallback' in window) {
      requestIdleCallback(run, { timeout: 3000 });
    } else {
      setTimeout(run, 0);
    }
  }

  makeUrl(path) {
    try {
      const base = (window.location && window.location.origin) ? window.location.origin : '';
      return new URL(String(path || '/'), base);
    } catch (e) {
      console.warn('[analytics] URL non valida:', path, e);
      return null;
    }
  }

  async safeFetchJson(url, { timeoutMs = 6000 } = {}) {
    if (!url) return null;
    const ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    const t = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : null;
    try {
      const r = await fetch(url, { cache: 'no-store', signal: ctl ? ctl.signal : undefined, headers: { 'Accept': 'application/json' } });
      if (!r.ok) return null;
      try { return await r.json(); } catch { return null; }
    } catch (e) {
      return null;
    } finally {
      if (t) clearTimeout(t);
    }
  }

  drawAnalyticsChartsSafe(data) {
    try {
      if (typeof Chart === 'undefined') {
        console.warn('[analytics] Chart.js non caricato → skip');
        return;
      }

      // Esempi: se esistono questi canvas, disegnali; altrimenti skip silenzioso
      const ctx1 = document.getElementById('chart-company-summary');
      if (ctx1) {
        try {
          const cfg = this.normalizeBarConfig(data.company_summary);
          if (ctx1.__chartInstance) ctx1.__chartInstance.destroy();
          ctx1.__chartInstance = new Chart(ctx1, cfg);
        } catch (e) { console.warn('[analytics] render company-summary fallito:', e); }
      }

      const ctx2 = document.getElementById('chart-revenue-trend');
      if (ctx2) {
        try {
          const cfg = this.normalizeLineConfig(data.revenue_trend);
          if (ctx2.__chartInstance) ctx2.__chartInstance.destroy();
          ctx2.__chartInstance = new Chart(ctx2, cfg);
        } catch (e) { console.warn('[analytics] render revenue-trend fallito:', e); }
      }

      // Se usi altri canvas, replica il pattern qui sopra in modo sicuro.
    } catch (e) {
      console.error('[analytics] errore generale draw:', e);
    }
  }

  normalizeBarConfig(src) {
    const labels = Array.isArray(src?.labels) ? src.labels : [];
    const values = Array.isArray(src?.values) ? src.values : [];
    return {
      type: 'bar',
      data: { labels, datasets: [{ label: (src?.label || 'Totali'), data: values }] },
      options: {
        responsive: true,
        animation: false,
        parsing: false,
        plugins: { legend: { display: true } },
        scales: { x: { ticks: { autoSkip: true } }, y: { beginAtZero: true } }
      }
    };
  }

  normalizeLineConfig(src) {
    const labels = Array.isArray(src?.labels) ? src.labels : [];
    const values = Array.isArray(src?.values) ? src.values : [];
    return {
      type: 'line',
      data: { labels, datasets: [{ label: (src?.label || 'Trend'), data: values, tension: 0.25, fill: false }] },
      options: {
        responsive: true,
        animation: false,
        parsing: false,
        plugins: { legend: { display: true } },
        scales: { x: { ticks: { autoSkip: true } }, y: { beginAtZero: true } }
      }
    };
  }
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