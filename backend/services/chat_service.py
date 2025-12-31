# services/chat_service.py
import time
import json
import re
import logging
from datetime import datetime
from flask import g
from mongoengine.connection import get_db

from utils.intent_router import IntentRouter
from utils.message_parser import parse_multi
from services.chat_skills import ChatSkills
from utils.retrieval import build_context
from config.prompt_templates import make_chat_prompt, SYSTEM_INSTRUCTIONS
from services.work_service import WorkService

# Import opzionali
try:
    from routes.estimate import estimate_from_entities
except ImportError:
    estimate_from_entities = None
try:
    from models.estimators import pick_and_estimate
except ImportError:
    pick_and_estimate = lambda x: None

log = logging.getLogger("chat_service")

class ChatService:
    def __init__(self, vector_store, chat_model, web_retriever=None):
        self.vector_store = vector_store
        self.chat_model = chat_model
        self.web_retriever = web_retriever
        self.router = IntentRouter()
        
        # LISTA AGGIORNATA SKILLS
        self.read_skills = [
            ChatSkills.headcount,
            ChatSkills.role_lookup,
            ChatSkills.list_by_role_intent,
            ChatSkills.available_filtered,      # NEW
            ChatSkills.set_worker_region_city,  # NEW
            ChatSkills.capacity_check,          # NEW
            ChatSkills.toggle_worker_availability,
            ChatSkills.project_counts,
            ChatSkills.recent_projects,         # NEW
            ChatSkills.material_price
        ]
        self.project_skills = [
            ChatSkills.add_work_item,
            ChatSkills.plan_works,
            ChatSkills.auto_assign
        ]
    
    # --- HELPER: Saluti veloci ---
    def _is_greeting(self, text: str) -> bool:
        """Rileva saluti semplici per evitare chiamate LLM costose."""
        t = (text or "").strip()
        GREETING_RE = re.compile(r"\b(ciao|buongiorno|buonasera|salve|hey|hei|hi|hello)\b", re.IGNORECASE)
        if len(t) <= 12 and GREETING_RE.search(t): return True
        if GREETING_RE.match(t): return True
        return False

    def _strip_calc_json(self, text: str) -> str:
        if not text: return ""
        t = re.split(r"```calc_json[\s\S]*?```", text, flags=re.I)[0]
        t = re.sub(r"\[calc_json\]", "", t, flags=re.I)
        t = re.sub(r"(?i)\bcalc_json\b", "", t)
        return t.rstrip()

    def _ensure_calc_block(self, res: dict, auto_estimate: dict, question: str):
        if not auto_estimate: return
        try:
             block = "\n\n```calc_json\n" + json.dumps(auto_estimate, ensure_ascii=False) + "\n```"
             key = "reply" if "reply" in res else "answer"
             if key in res and "```calc_json" not in res[key]:
                 res[key] += block
        except Exception: pass

    def _save_analytics(self, session_id, question, response, latency_ms, project_id, intent):
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

    def process_message(self, question: str, session_id: str, project_id: str = None, user_context: dict = None):
        t0 = time.perf_counter()
        
        # 0. SHORT-CIRCUIT: Saluti
        if self._is_greeting(question):
            res = {"answer": "Ciao! Dimmi pure cosa ti serve: materiali, personale o lavori del cantiere."}
            return self._finalize(res, t0, session_id, question, project_id, "GREETING")

        # 1. Action Skills
        if project_id:
            for skill in self.project_skills:
                res = skill(question, project_id)
                if res:
                    # Gestione specifica Action Add Work (recupero codice)
                    if res.get("INTENT_DB") == "ACTION_ADD_WORK":
                        payload = res.get("action_payload", {})
                        db = get_db()
                        t = payload.get("text", "").lower()
                        code = None
                        docs = list(db["work_catalog"].find({}, {"code": 1, "name": 1, "synonyms": 1}))
                        for d in docs:
                             if d.get("name", "").lower() in t: code = d["code"]; break
                             for syn in d.get("synonyms", []):
                                 if syn.lower() in t: code = d["code"]; break
                        
                        if code:
                            ws_res = WorkService.add_work_item(project_id, code, payload.get("qty", 1.0))
                            msg = f"Aggiunto {code} ({payload.get('qty')}) al progetto." if ws_res.get("ok") else f"Errore: {ws_res.get('error')}"
                            res["answer"] = msg
                        else:
                            res["answer"] = "Non ho capito quale voce aggiungere. Specifica il nome del capitolato."
                    
                    return self._finalize(res, t0, session_id, question, project_id, res.get("INTENT_DB"))

        # 2. Read Skills
        for skill in self.read_skills:
            res = skill(question)
            if res:
                return self._finalize(res, t0, session_id, question, project_id, res.get("INTENT_DB"))

        # 3. Parsing Multi-Voce
        multi_items = []
        try:
            multi_items = parse_multi(question)
        except Exception: pass

        # 4. Routing & RAG
        routed = self.router.route(question)
        intent = routed.get("intent", "none")
        entities = routed.get("entities", {})

        local_ctx = []
        if self.vector_store:
            where = {"project_id": int(project_id)} if project_id else None
            try:
                local_ctx = self.vector_store.search(question, limit=8, where=where)
            except Exception: pass

        # 5. Stima
        auto_estimate = None
        if intent == "STIMA" and entities.get("qty"):
             if estimate_from_entities: 
                 auto_estimate = estimate_from_entities(entities)
             if not auto_estimate:
                 auto_estimate = pick_and_estimate(entities)

        db_ctx = build_context(project_id) if project_id else {}
        prompt = make_chat_prompt(db_ctx, question) if db_ctx else question
        
        # 6. LLM Call
        res = self.chat_model.answer_with_contexts(
            session_id, 
            SYSTEM_INSTRUCTIONS + "\n\n" + prompt,
            local_ctx, 
            [], 
            calc_json=auto_estimate
        )

        # 7. Post-Processing
        key = "reply" if "reply" in res else "answer"
        res[key] = self._strip_calc_json(res.get(key, ""))
        self._ensure_calc_block(res, auto_estimate, question)

        if multi_items:
            res["parsed_items"] = multi_items
            res["ui_tables"] = {"items": [], "notes": "Preview tables integration pending"}

        res["intent"] = intent
        return self._finalize(res, t0, session_id, question, project_id, intent)

    def _finalize(self, res, t0, sid, q, pid, intent):
        latency = int((time.perf_counter() - t0) * 1000)
        res["latency_ms"] = latency
        res["intent"] = intent 
        res.setdefault("ui_meta", {}).update({"sender": "assistant", "align": "left"})
        self._save_analytics(sid, q, res, latency, pid, intent)
        return res