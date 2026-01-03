# services/chat_service.py
import time
import json
import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from flask import g, current_app

from mongoengine.connection import get_db
from utils.message_parser import parse_multi
from config.prompt_templates import make_chat_prompt, SYSTEM_INSTRUCTIONS

log = logging.getLogger("chat_service")

class ChatService:
    def __init__(self, vector_store, chat_model, web_retriever=None, router=None):
        self.vector_store = vector_store
        self.chat_model = chat_model
        self.web_retriever = web_retriever
        self.router = router
        
    # --- HELPERS ---
    def _is_greeting(self, text: str) -> bool:
        """Rileva saluti semplici per evitare chiamate LLM costose."""
        t = (text or "").strip()
        GREETING_RE = re.compile(r"\b(ciao|buongiorno|buonasera|salve|hey|hei|hi|hello)\b", re.IGNORECASE)
        if len(t) <= 12 and GREETING_RE.search(t):
            return True
        if GREETING_RE.match(t):
            return True
        return False

    def _strip_calc_json(self, text: str) -> str:
        """Rimuove blocchi calc_json dal testo."""
        if not text:
            return ""
        t = re.split(r"```calc_json[\s\S]*?```", text, flags=re.I)[0]
        t = re.sub(r"\[calc_json\]", "", t, flags=re.I)
        t = re.sub(r"(?i)\bcalc_json\b", "", t)
        return t.rstrip()

    def _ensure_calc_block(self, res: dict, auto_estimate: dict, question: str):
        """Assicura che il calc_json sia presente nella risposta."""
        if not auto_estimate:
            return
        try:
            block = "\n\n```calc_json\n" + json.dumps(auto_estimate, ensure_ascii=False) + "\n```"
            key = "reply" if "reply" in res else "answer"
            if key in res and "```calc_json" not in res[key]:
                res[key] += block
        except Exception:
            pass

    def _extract_region_city(self, text: str) -> tuple:
        """Estrae regione e città dal testo."""
        t = text.lower()
        reg, city = None, None
        
        # Regione: "in Lazio", "in Lombardia"
        mreg = re.search(r"\bin\s+([a-zàèéìòù\-\s]{3,})", t)
        if mreg:
            reg = mreg.group(1).strip().title()
        
        # Città: "a Roma", "a Milano"
        mcity = re.search(r"\ba\s+([a-zàèéìòù\-\s]{2,})", t)
        if mcity:
            city = mcity.group(1).strip().title()
        
        return reg, city

    def _should_search_web(self, intent: str, local_ctx: list, question: str) -> bool:
        """
        Logica a 3 livelli per decidere quando cercare sul web:
        1. Intent esplicito WEB_SEARCH (meteo, normative, etc.)
        2. Fallback se documenti locali vuoti
        3. Fallback se score documenti troppo basso
        """
        # CASO 1: Intent esplicito
        if intent == "WEB_SEARCH":
            log.info("Web search attivato: intent esplicito WEB_SEARCH")
            return True
        
        # CASO 2: Nessun documento locale trovato
        if not local_ctx and intent not in ("STAFF", "MATERIALI", "none"):
            log.info("Web search attivato: nessun documento locale trovato")
            return True
        
        # CASO 3: Score troppo basso nei risultati locali
        if intent in ("MATERIALI", "STIMA", "STAFF") and local_ctx:
            top_score = local_ctx[0].get("score", 0.0)
            # Assumiamo distanza L2: score > 0.75 = rilevanza bassa
            if top_score > 0.75:
                log.info(f"Web search attivato: score basso ({top_score})")
                return True
        
        return False

    def _save_analytics(self, session_id, question, response, latency_ms, project_id, intent):
        """Salva analytics in MongoDB."""
        try:
            db = get_db()
            ans_text = response.get("reply") or response.get("answer") or ""
            db["chat_analytics"].insert_one({
                "session_id": session_id,
                "question": question,
                "answer": ans_text[:500],
                "intent": intent,
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow(),
                "site_id": project_id,
                "had_error": False,
            })
        except Exception as e:
            log.warning(f"Analytics fail: {e}")

    def _call_estimate_preview(self, multi_items: list, question: str) -> dict:
        """Chiamata server-side a estimate_preview per valorizzare tabelle."""
        try:
            reg_hint, city_hint = self._extract_region_city(question)
            
            from utils.estimate import estimate_preview as _preview_ep
            preview_body = {"items": multi_items}
            if reg_hint:
                preview_body["region"] = reg_hint
            if city_hint:
                preview_body["city"] = city_hint

            with current_app.test_request_context(json=preview_body):
                _resp = _preview_ep()

            # Normalizza risposta Flask
            def _as_json(resp):
                try:
                    if isinstance(resp, tuple):
                        resp_obj = resp[0]
                    else:
                        resp_obj = resp
                    if hasattr(resp_obj, "get_json"):
                        return resp_obj.get_json()
                    txt = resp_obj.get_data(as_text=True)
                    return json.loads(txt)
                except Exception:
                    return None

            return _as_json(_resp) or {}
        except Exception as e:
            log.warning(f"Preview preventivo fallita: {e}")
            return {}

    def _build_ui_tables(self, multi_items: list, question: str) -> dict:
        """Costruisce struttura tabellare per UI con valorizzazione preventivo."""
        # 1) Struttura stub
        ui_items = []
        for it in multi_items:
            ui_items.append({
                "label": it.get("label", "voce"),
                "qty": float(it.get("qty", 1.0)),
                "unit": it.get("unit", "pz"),
                "materials": {
                    "columns": ["code", "descr", "um", "qta", "prezzo", "totale"],
                    "rows": []
                },
                "labor": {
                    "columns": ["ruolo", "ore", "tariffa", "totale"],
                    "rows": []
                },
                "subtotal": 0.0
            })

        # 2) Valorizzazione via estimate_preview
        preview_data = self._call_estimate_preview(multi_items, question)
        ui_tables = preview_data.get("ui_tables")
        
        if ui_tables:
            return ui_tables
        
        # Fallback: restituisci stub
        return {
            "items": ui_items,
            "grand_total": 0.0,
            "notes": "Anteprima non valorizzata (estimate service non disponibile)."
        }

    def process_message(self, question: str, session_id: str, project_id: str = None, user_context: dict = None):
        """
        Main entry point per processare un messaggio chat.
        Integra: skills, routing, RAG, web search, parsing multi-voce, preventivi.
        """
        t0 = time.perf_counter()
        
        # 0. SHORT-CIRCUIT: Saluti
        if self._is_greeting(question):
            res = {"answer": "Ciao! Dimmi pure cosa ti serve: materiali, personale o lavori del cantiere."}
            return self._finalize(res, t0, session_id, question, project_id, "GREETING")

        # 1. Tenta Skills deterministiche (delegate a ChatSkills)
        from services.chat_skills import ChatSkills
        
        # Skills progetto (se abbiamo project_id)
        if project_id:
            for skill_method in [ChatSkills.add_work_item, ChatSkills.plan_works, ChatSkills.auto_assign]:
                res = skill_method(question, project_id)
                if res:
                    return self._finalize(res, t0, session_id, question, project_id, res.get("INTENT_DB"))

        # Skills lettura (sempre disponibili)
        for skill_method in [
            ChatSkills.headcount,
            ChatSkills.role_lookup,
            ChatSkills.list_by_role_intent,
            ChatSkills.available_filtered,
            ChatSkills.set_worker_region_city,
            ChatSkills.capacity_check,
            ChatSkills.toggle_worker_availability,
            ChatSkills.project_counts,
            ChatSkills.recent_projects,
            ChatSkills.material_price
        ]:
            res = skill_method(question)
            if res:
                return self._finalize(res, t0, session_id, question, project_id, res.get("INTENT_DB"))

        # 2. Parsing Multi-Voce
        multi_items = []
        try:
            multi_items = parse_multi(question)
        except Exception:
            pass

        # 3. Routing & RAG locale
        routed = {}
        if self.router:
            try:
                routed = self.router.route(question)
            except Exception:
                pass
        
        intent = routed.get("intent", "none")
        entities = routed.get("entities", {})

        local_ctx = []
        if self.vector_store:
            where = {"project_id": int(project_id)} if project_id else None
            try:
                local_ctx = self.vector_store.search(question, limit=8, where=where)
            except Exception:
                pass

        # 4. Web Retrieval (logica a 3 livelli)
        web_ctx = []
        
        # DEBUG: Log dello stato web retrieval
        web_enabled = current_app.config.get("ENABLE_WEB_RETRIEVAL", False)
        log.info(f"🌐 Web Retrieval - enabled={web_enabled}, retriever_present={self.web_retriever is not None}")
        
        if self.web_retriever and web_enabled:
            should_search = self._should_search_web(intent, local_ctx, question)
            log.info(f"🔍 Should search web: {should_search} (intent={intent}, local_docs={len(local_ctx)})")
            
            if should_search:
                try:
                    log.info(f"🚀 Executing web search for: '{question[:60]}'")
                    web_ctx = self.web_retriever.search(question)
                    log.info(f"✅ Web search completata: {len(web_ctx)} risultati")
                    
                    # Log primi risultati per debug
                    for i, r in enumerate(web_ctx[:2], 1):
                        log.info(f"   [{i}] {r.get('title', 'N/A')[:50]}")
                        
                except Exception as e:
                    log.warning(f"❌ Web retriever fallito: {e}")
                    import traceback
                    log.warning(traceback.format_exc())
        else:
            if not self.web_retriever:
                log.warning("⚠️ Web retriever NON INIZIALIZZATO (self.web_retriever is None)")
            if not web_enabled:
                log.warning("⚠️ Web retrieval DISABILITATO in config (ENABLE_WEB_RETRIEVAL=False)")

        # 5. Stima automatica (se intent STIMA)
        auto_estimate = None
        if intent == "STIMA" and entities.get("qty"):
            try:
                from routes.estimate import estimate_from_entities
                auto_estimate = estimate_from_entities(entities)
            except ImportError:
                pass
            
            if not auto_estimate:
                try:
                    from models.estimators import pick_and_estimate
                    auto_estimate = pick_and_estimate(entities)
                except ImportError:
                    pass

        # 6. Build context e prompt
        from utils.retrieval import build_context
        db_ctx = build_context(project_id) if project_id else {}
        prompt = make_chat_prompt(db_ctx, question) if db_ctx else question
        
        # 7. LLM Call con dual context (local + web)
        res = self.chat_model.answer_with_contexts(
            session_id, 
            SYSTEM_INSTRUCTIONS + "\n\n" + prompt,
            local_ctx, 
            web_ctx,
            calc_json=auto_estimate,
            site_id=project_id
        )

        # 8. Post-Processing
        key = "reply" if "reply" in res else "answer"
        res[key] = self._strip_calc_json(res.get(key, ""))
        self._ensure_calc_block(res, auto_estimate, question)

        # 9. Multi-voce: aggiungi tabelle UI valorizzate
        if multi_items:
            res["parsed_items"] = multi_items
            res["ui_tables"] = self._build_ui_tables(multi_items, question)
            
            # Aggiungi nota al testo
            if key in res:
                res[key] += f"\n\nHo rilevato {len(multi_items)} lavorazioni. Trovi le tabelle dettagliate in basso."

        res["intent"] = intent
        return self._finalize(res, t0, session_id, question, project_id, intent)

    def _finalize(self, res, t0, sid, q, pid, intent):
        """Finalizza risposta con latency, analytics e metadati UI."""
        latency = int((time.perf_counter() - t0) * 1000)
        res["latency_ms"] = latency
        res["intent"] = intent
        res.setdefault("ui_meta", {}).update({"sender": "assistant", "align": "left"})
        
        self._save_analytics(sid, q, res, latency, pid, intent)
        
        # Telemetry opzionale
        try:
            from services.telemetry import log_chat_metrics
            log_chat_metrics({
                "intent": intent,
                "tokens_in": len(q.split()),
                "tokens_out": len((res.get("reply") or res.get("answer") or "").split()),
                "latency_ms": latency,
                "parsed_items": len(res.get("parsed_items") or []),
                "had_error": False
            })
        except Exception:
            pass
        
        return res