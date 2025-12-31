# services/prompt_templates.py
from __future__ import annotations
from typing import Dict, Any, List
import json

SYSTEM_INSTRUCTIONS = """Sei un assistente per gestione cantieri.
Rispondi sempre in tre sezioni concise:
1) Riepilogo (max 3 frasi)
2) Prossime azioni (bullet)
3) Blocchi/Rischi (solo se presenti)
Se il messaggio contiene più lavorazioni, elenca i calc_json richiesti in formato JSON puro (array), senza testo superfluo.
Non ripetere informazioni già nel contesto, sii sintetico e operativo.
"""

def make_chat_prompt(context: Dict[str, Any], user_text: str) -> str:
    ctx = {
        "project": context.get("project") or {},
        "work_items": context.get("work_items") or [],
        "assignments": context.get("assignments") or [],
        "documents": context.get("documents") or [],
    }
    return (
        "### CONTEXT (JSON)\n"
        + json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
        + "\n\n### QUESTION\n"
        + user_text.strip()
        + "\n\n### YOU MUST ANSWER (FORMAT)\n"
        "Riepilogo:\n- ...\n\nProssime azioni:\n- ...\n\nBlocchi/Rischi:\n- ... (se presenti)\n"
        "Se servono calcoli: restituisci un array JSON con N calc_json (uno per voce), senza testo aggiuntivo."
    )