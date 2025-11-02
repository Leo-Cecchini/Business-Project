# services/analytics_service.py
from __future__ import annotations
import os, json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple
from pymongo.database import Database

USE_LLM = bool(os.getenv("GOOGLE_API_KEY"))
if USE_LLM:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception:
        USE_LLM = False

def _avg(xs): return round(sum(xs)/len(xs), 2) if xs else 0.0

def _fetch_records(db: Database, days: int, limit: int, site_id: str | None):
    q = {"timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}}
    if site_id: q["site_id"] = site_id
    return list(db["chat_analytics"].find(q).sort("timestamp", -1).limit(limit))

def _compute_metrics(records: List[Dict]) -> Dict[str, Any]:
    n = len(records)
    errors = sum(1 for r in records if r.get("had_error"))
    tool_usage = Counter(t for r in records for t in (r.get("tools_used") or []))
    intents = Counter((r.get("intent") or r.get("intent_tag") or "unknown") for r in records)
    q_len = [len((r.get("question") or "").split()) for r in records]
    a_len = [len((r.get("answer") or "").split()) for r in records]
    lat   = [r.get("latency_ms") for r in records if r.get("latency_ms") is not None]
    return {
        "total_chats": n,
        "error_rate": round(errors/n, 3) if n else 0.0,
        "top_tools": tool_usage.most_common(8),
        "top_intents": intents.most_common(8),
        "avg_question_tokens": _avg(q_len),
        "avg_answer_tokens": _avg(a_len),
        "avg_latency_ms": _avg(lat),
    }

def _build_chart_series(records: List[Dict]) -> Dict[str, Any]:
    # Serie 1: chat per giorno (ultimi N giorni)
    by_day = Counter((r["timestamp"].date() if isinstance(r.get("timestamp"), datetime) else r["timestamp"]) for r in records)
    days_sorted = sorted(set(d for d in by_day.keys()))
    series_chats = {"labels": [d.isoformat() for d in days_sorted], "values": [by_day.get(d, 0) for d in days_sorted]}

    # Serie 2: top intent
    intents = Counter((r.get("intent") or r.get("intent_tag") or "unknown") for r in records)
    top_intents = intents.most_common(8)
    series_intents = {"labels": [k for k, _ in top_intents], "values": [v for _, v in top_intents]}

    # Serie 3: errori vs OK
    errors = sum(1 for r in records if r.get("had_error"))
    series_errors = {"labels": ["OK", "Errori"], "values": [len(records)-errors, errors]}

    return {
        "chats_per_day": series_chats,
        "top_intents": series_intents,
        "errors_split": series_errors,
    }

def _make_llm_report(records: List[Dict], metrics: Dict[str, Any]) -> str:
    pairs = []
    for r in records[:300]:
        q = (r.get("question") or "").replace("\n", " ").strip()
        a = (r.get("answer") or "").replace("\n", " ").strip()
        pairs.append(f"Q: {q}\nA: {a}")
    transcript = "\n\n".join(pairs)[:20000]

    if not USE_LLM:
        # Fallback breve
        return (
            "Sintesi:\n"
            f"- Conversazioni: {metrics['total_chats']}\n"
            f"- Error rate: {metrics['error_rate']*100:.1f}%\n"
            f"- Top intent: {', '.join([f'{k}({v})' for k,v in metrics['top_intents'][:3]])}\n\n"
            "Debolezze:\n- Alias materiali/ruoli incompleti.\n- Alcune risposte brevi.\n\n"
            "Miglioramenti:\n- Espandere sinonimi DB + fuzzy.\n- Test tool-calls e conferma delete.\n- Riassunti memoria più frequenti."
        )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", temperature=0.2,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        convert_system_message_to_human=True, request_timeout=60,
    )
    prompt = f"""
Sei un analista qualità per un assistente AI in edilizia.
Crea un report operativo con sezioni: Sintesi, Debolezze, Miglioramenti, KPI, Prossime azioni.
Usa numeri dalle metriche e non inventare.
Metriche:\n{json.dumps(metrics, ensure_ascii=False, indent=2)}
Transcript campione:\n{transcript}
"""
    resp = llm.invoke(prompt)
    return getattr(resp, "content", str(resp))

def generate_and_save_report(db: Database, days=7, limit=500, site_id: str|None=None) -> Dict[str, Any]:
    records = _fetch_records(db, days, limit, site_id)
    metrics = _compute_metrics(records); metrics["period_days"] = days
    charts  = _build_chart_series(records)
    text    = _make_llm_report(records, metrics)
    bad = []
    for r in records:
        ans = (r.get("answer") or "").strip()
        if r.get("had_error") or len(ans) < 10:
            bad.append({"q": (r.get("question") or "")[:300], "a": ans[:300], "ts": r.get("timestamp")})
        if len(bad) >= 12: break

    doc = {
        "created_at": datetime.utcnow(),
        "period_days": days,
        "site_id": site_id,
        "metrics": metrics,
        "charts": charts,     # <-- serie PRONTE per i grafici
        "report": text,
        "bad_examples": bad,
    }
    db["chat_quality_reports"].insert_one(doc)
    doc["id"] = str(doc.get("_id"))
    return doc