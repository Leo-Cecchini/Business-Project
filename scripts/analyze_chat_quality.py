#!/usr/bin/env python3
# scripts/analyze_chat_quality.py
from __future__ import annotations
import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

from pymongo import MongoClient

# LLM opzionale: se non c'è API key, andiamo in fallback
USE_LLM = bool(os.getenv("GOOGLE_API_KEY"))
if USE_LLM:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception:
        USE_LLM = False


def setup_logger(verbose: bool):
    lvl = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("chat_quality")


def get_db() -> Any:
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    dbname = os.getenv("MONGODB_DB", "business_project")
    client = MongoClient(uri)
    return client[dbname]


def fetch_records(db, days: int, limit: int, site_id: str | None) -> List[Dict]:
    q: Dict[str, Any] = {"timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}}
    if site_id:
        q["site_id"] = site_id
    cur = db["chat_analytics"].find(q).sort("timestamp", -1).limit(limit)
    return list(cur)


def simple_token_count(text: str) -> int:
    return len((text or "").split())


def compute_metrics(records: List[Dict]) -> Dict[str, Any]:
    n = len(records)
    errors = sum(1 for r in records if r.get("had_error"))
    tool_usage = Counter()
    intents = Counter()
    latencies = []  # se un domani salvi latenza ms, qui puoi fare medie
    q_len = []
    a_len = []

    # se in 6A hai salvato "intent" o "tools_used", li leggiamo qui
    for r in records:
        for t in (r.get("tools_used") or []):
            tool_usage[t] += 1
        intent = r.get("intent") or r.get("intent_tag")
        if intent:
            intents[intent] += 1
        q_len.append(simple_token_count(r.get("question", "")))
        a_len.append(simple_token_count(r.get("answer", "")))
        if "latency_ms" in r:
            latencies.append(r["latency_ms"])

    def _avg(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    metrics = {
        "total_chats": n,
        "error_rate": round(errors / n, 3) if n else 0.0,
        "top_tools": tool_usage.most_common(8),
        "top_intents": intents.most_common(8),
        "avg_question_tokens": _avg(q_len),
        "avg_answer_tokens": _avg(a_len),
        "avg_latency_ms": _avg(latencies),
        "period_days": None,  # lo inseriamo fuori
    }
    return metrics


def sample_bad_examples(records: List[Dict], max_items: int = 12) -> List[Dict]:
    """Prende esempi con errore o risposta molto corta/vuota."""
    bad = []
    for r in records:
        ans = (r.get("answer") or "").strip()
        if r.get("had_error") or len(ans) < 10:
            bad.append({"q": r.get("question", "")[:400],
                        "a": ans[:400],
                        "ts": r.get("timestamp")})
        if len(bad) >= max_items:
            break
    return bad


def make_llm_report(records: List[Dict], metrics: Dict[str, Any]) -> str:
    # Prepara transcript breve (evita testi troppo lunghi)
    pairs = []
    for r in records[:300]:
        q = (r.get("question") or "").replace("\n", " ").strip()
        a = (r.get("answer") or "").replace("\n", " ").strip()
        pairs.append(f"Q: {q}\nA: {a}")
    transcript = "\n\n".join(pairs)[:20000]

    prompt = f"""
Sei un analista qualità per un assistente AI in un'azienda edile.
Ti passo un transcript ridotto di Q/A e alcune metriche aggregate.
Devi restituire un report breve ma operativo, con queste sezioni:

1) Sintesi (3-5 bullet con numeri: volumi, %errori, tool più usati, intent top)
2) Debolezze individuate (categorie, esempi sintetici, frasi tipiche)
3) Miglioramenti concreti (max 6, ognuno con: area, impatto, step tecnico)
4) KPI da monitorare (3-4 indicatori con target)
5) Prossime azioni (priorità alta → bassa)

Metriche:
{json.dumps(metrics, ensure_ascii=False, indent=2)}

Transcript (campione):
{transcript}
"""
    if not USE_LLM:
        # Fallback euristico: testo generato a partire dalle metriche
        lines = []
        lines.append("Sintesi:")
        lines.append(f"- Conversazioni analizzate: {metrics['total_chats']}")
        lines.append(f"- Tasso errore: {metrics['error_rate']*100:.1f}%")
        if metrics["top_tools"]:
            lines.append(f"- Tool più usati: {', '.join([f'{k}({v})' for k,v in metrics['top_tools'][:3]])}")
        if metrics["top_intents"]:
            lines.append(f"- Intent più frequenti: {', '.join([f'{k}({v})' for k,v in metrics['top_intents'][:3]])}")
        lines.append("\nDebolezze individuate:")
        lines.append("- Alcune richieste non mappate su intent deterministici.")
        lines.append("- Risposte brevi o vuote in casi di errore.")
        lines.append("\nMiglioramenti concreti:")
        lines.append("- Ampliare sinonimi materiali/ruoli e usare fallback fuzzy negli endpoint.")
        lines.append("- Aggiungere test per tool-calls create/remove worker e conferma delete.")
        lines.append("- Migliorare memory con riassunti più frequenti se >20 turni.")
        lines.append("\nKPI da monitorare: error_rate < 5%, avg_latency_ms < 1200, coverage intent > 80%.")
        lines.append("\nProssime azioni: 1) sinonimi/aliases 2) intent router 3) test tool 4) dashboard errori.")
        return "\n".join(lines)

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.2,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        convert_system_message_to_human=True,
        request_timeout=60,
    )
    resp = llm.invoke(prompt)
    return getattr(resp, "content", str(resp))


def save_report(db, report_text: str, metrics: Dict[str, Any], bad_examples: List[Dict], days: int, site_id: str | None):
    doc = {
        "created_at": datetime.utcnow(),
        "period_days": days,
        "site_id": site_id,
        "metrics": metrics,
        "report": report_text,
        "bad_examples": bad_examples,
    }
    db["chat_quality_reports"].insert_one(doc)
    return doc


def main():
    parser = argparse.ArgumentParser(description="Chat quality analyzer")
    parser.add_argument("--days", type=int, default=7, help="intervallo di analisi (giorni)")
    parser.add_argument("--limit", type=int, default=500, help="max record chat_analytics da analizzare")
    parser.add_argument("--site-id", type=str, default=None, help="filtra per cantiere/azienda se lo salvi in chat_analytics")
    parser.add_argument("--dry-run", action="store_true", help="non salvare in DB, stampa solo")
    parser.add_argument("--verbose", action="store_true", help="log dettagliato")
    args = parser.parse_args()

    log = setup_logger(args.verbose)
    db = get_db()
    recs = fetch_records(db, args.days, args.limit, args.site_id)
    log.info(f"Record letti: {len(recs)} (ultimi {args.days} giorni)")

    metrics = compute_metrics(recs)
    metrics["period_days"] = args.days
    bad = sample_bad_examples(recs, max_items=12)
    report = make_llm_report(recs, metrics)

    if args.dry_run:
        print("# == METRICS ==")
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        print("\n# == REPORT ==\n")
        print(report)
        if bad:
            print("\n# == BAD EXAMPLES ==\n")
            for b in bad:
                print(f"- Q: {b['q']}\n  A: {b['a']}\n  TS: {b['ts']}\n")
        return

    saved = save_report(db, report, metrics, bad, args.days, args.site_id)
    log.info(f"Report salvato in chat_quality_reports con _id={saved.get('_id')}")
    print("OK")


if __name__ == "__main__":
    sys.exit(main())