# services/analytics_service.py
from __future__ import annotations
import os
import json
from datetime import datetime, timedelta
from collections import Counter
from typing import Any, Dict, List, Optional
from mongoengine.connection import get_db

# Configurazione LLM opzionale
USE_LLM = bool(os.getenv("GOOGLE_API_KEY"))
if USE_LLM:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception:
        USE_LLM = False


class AnalyticsService:
    """
    Centralized analytics service for chat quality analysis.
    Gestisce KPI, reportistica e integrazione LLM.
    """
    
    # --- HELPER INTERNI ---
    @staticmethod
    def _avg(xs):
        return round(sum(xs)/len(xs), 2) if xs else 0.0

    # --- KPI VELOCI (Dashboard) ---
    
    @staticmethod
    def get_summary(days: int = 7, site_id: str | None = None) -> Dict[str, Any]:
        """
        Calcola i KPI veloci usando count_documents (efficiente).
        Sostituisce la vecchia logica che scaricava tutti i record.
        """
        db = get_db()
        col = db["chat_analytics"]
        
        since = datetime.utcnow() - timedelta(days=days)
        
        # Filtri base
        q_total = {}
        q_period = {"timestamp": {"$gte": since}}
        q_error = {"had_error": True, "timestamp": {"$gte": since}}
        
        if site_id:
            q_total["site_id"] = site_id
            q_period["site_id"] = site_id
            q_error["site_id"] = site_id
            
        total = col.count_documents(q_total)
        period_chats = col.count_documents(q_period)
        period_errors = col.count_documents(q_error)
        
        return {
            "total_chats": total,
            "period_days": days,
            "period_chats": period_chats,
            "period_errors": period_errors,
            "error_rate": round(period_errors / period_chats, 3) if period_chats else 0.0
        }
    
    # Alias per compatibilità
    get_quick_stats = get_summary

    # --- REPORT LISTING ---

    @staticmethod
    def list_reports(limit: int = 10, site_id: str = None) -> List[Dict]:
        """Lista i report generati salvati nel DB."""
        db = get_db()
        q = {}
        if site_id:
            q["site_id"] = site_id
            
        # Projection per efficienza e ordinamento
        cursor = db["chat_quality_reports"].find(q).sort("created_at", -1).limit(limit)
        
        results = []
        for r in cursor:
            results.append({
                "id": str(r.get("_id")),
                "created_at": r.get("created_at"),
                "period_days": r.get("period_days"),
                "site_id": r.get("site_id"),
                "metrics": r.get("metrics") or {},
                "report": r.get("report") or "",
                "bad_examples": r.get("bad_examples") or [],
            })
        return results

    # --- GENERAZIONE REPORT (Deep Analysis) ---

    @staticmethod
    def fetch_records(days: int, limit: int, site_id: str | None) -> List[Dict]:
        """Recupera i log grezzi delle chat per analisi approfondita."""
        db = get_db()
        q = {"timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}}
        if site_id:
            q["site_id"] = site_id
        return list(db["chat_analytics"].find(q).sort("timestamp", -1).limit(limit))
    
    @staticmethod
    def compute_metrics(records: List[Dict]) -> Dict[str, Any]:
        """Calcola metriche aggregate dai record."""
        n = len(records)
        errors = sum(1 for r in records if r.get("had_error"))
        
        # Flattening dei tool usati
        all_tools = []
        for r in records:
            tools = r.get("tools_used")
            if isinstance(tools, list):
                all_tools.extend(tools)
                
        tool_usage = Counter(all_tools)
        intents = Counter((r.get("intent") or r.get("intent_tag") or "unknown") for r in records)
        
        q_len = [len((r.get("question") or "").split()) for r in records]
        a_len = [len((r.get("answer") or "").split()) for r in records]
        lat = [r.get("latency_ms") for r in records if r.get("latency_ms") is not None]
        
        return {
            "total_chats": n,
            "error_rate": round(errors/n, 3) if n else 0.0,
            "top_tools": tool_usage.most_common(8),
            "top_intents": intents.most_common(8),
            "avg_question_tokens": AnalyticsService._avg(q_len),
            "avg_answer_tokens": AnalyticsService._avg(a_len),
            "avg_latency_ms": AnalyticsService._avg(lat),
        }
    
    @staticmethod
    def build_chart_series(records: List[Dict]) -> Dict[str, Any]:
        """Prepara i dati per i grafici (Chart.js)."""
        # Chats per day
        by_day = Counter()
        for r in records:
            ts = r.get("timestamp")
            if isinstance(ts, datetime):
                by_day[ts.date()] += 1
        
        days_sorted = sorted(by_day.keys())
        series_chats = {
            "labels": [d.isoformat() for d in days_sorted],
            "values": [by_day[d] for d in days_sorted]
        }
        
        # Top intents
        intents = Counter((r.get("intent") or r.get("intent_tag") or "unknown") for r in records)
        top_intents = intents.most_common(8)
        series_intents = {
            "labels": [k for k, _ in top_intents],
            "values": [v for _, v in top_intents]
        }
        
        # Errors split
        errors = sum(1 for r in records if r.get("had_error"))
        series_errors = {
            "labels": ["OK", "Errori"],
            "values": [len(records)-errors, errors]
        }
        
        return {
            "chats_per_day": series_chats,
            "top_intents": series_intents,
            "errors_split": series_errors,
        }
    
    @staticmethod
    def sample_bad_examples(records: List[Dict], max_items: int = 12) -> List[Dict]:
        """Estrae esempi negativi (errori o risposte troppo brevi)."""
        bad = []
        for r in records:
            ans = (r.get("answer") or "").strip()
            if r.get("had_error") or len(ans) < 5: # Soglia lunghezza minima
                bad.append({
                    "q": (r.get("question") or "")[:400],
                    "a": ans[:400],
                    "ts": r.get("timestamp")
                })
            if len(bad) >= max_items:
                break
        return bad
    
    @staticmethod
    def generate_llm_report(records: List[Dict], metrics: Dict[str, Any]) -> str:
        """Genera un'analisi qualitativa usando l'LLM."""
        
        # Build transcript (max 20k chars context)
        pairs = []
        for r in records[:300]:
            q = (r.get("question") or "").replace("\n", " ").strip()
            a = (r.get("answer") or "").replace("\n", " ").strip()
            pairs.append(f"Q: {q}\nA: {a}")
        transcript = "\n\n".join(pairs)[:20000]
        
        if not USE_LLM:
            return (
                f"Analisi Automatica (LLM non disponibile):\n"
                f"- Totale Chat: {metrics['total_chats']}\n"
                f"- Error Rate: {metrics['error_rate']*100:.1f}%\n"
                f"- Intent Principali: {', '.join([k for k,_ in metrics['top_intents'][:3]])}\n"
            )
        
        try:
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash", # Usiamo il modello veloce
                temperature=0.2,
                google_api_key=os.getenv("GOOGLE_API_KEY"),
                convert_system_message_to_human=True,
                request_timeout=60,
            )
            
            prompt = f"""Sei un analista qualità per un assistente AI in ambito edile.
Analizza i dati e fornisci un report operativo in Markdown.
Sezioni richieste: Sintesi, Punti Deboli (con esempi), Punti di Forza, Suggerimenti per il miglioramento.

METRICHE:
{json.dumps(metrics, ensure_ascii=False, indent=2)}

TRANSCRIPT CHAT RECENTI:
{transcript}
"""
            resp = llm.invoke(prompt)
            return getattr(resp, "content", str(resp))
        except Exception as e:
            return f"Errore generazione report AI: {str(e)}"
    
    @staticmethod
    def generate_and_save_report(days: int = 7, limit: int = 500, site_id: str | None = None) -> Dict[str, Any]:
        """Orchestra la generazione completa e il salvataggio."""
        db = get_db()
        
        # 1. Fetch
        records = AnalyticsService.fetch_records(days, limit, site_id)
        if not records:
            raise ValueError("Nessuna chat trovata nel periodo specificato.")
            
        # 2. Compute
        metrics = AnalyticsService.compute_metrics(records)
        metrics["period_days"] = days
        charts = AnalyticsService.build_chart_series(records)
        bad = AnalyticsService.sample_bad_examples(records)
        
        # 3. Analyze (LLM)
        text = AnalyticsService.generate_llm_report(records, metrics)
        
        # 4. Save
        doc = {
            "created_at": datetime.utcnow(),
            "period_days": days,
            "site_id": site_id,
            "metrics": metrics,
            "charts": charts,
            "report": text,
            "bad_examples": bad,
        }
        
        db["chat_quality_reports"].insert_one(doc)
        doc["id"] = str(doc.get("_id"))
        return doc