# utils/intent_router.py
from __future__ import annotations
from typing import Optional, Any
import json

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

# Importa i tuoi modelli Pydantic già esistenti
from models.intents import RoutedIntent, StaffIntent

# ---------------- Normalizzatore ruoli ----------------
ROLE_ALIASES = {
    "elettricista": ["elettricista", "elettrici", "elettrico"],
    "idraulico": ["idraulico", "idraulici", "impiantista idrico", "impianto idrico"],
    "muratore": ["muratore", "muratori"],
    "capo muratore": ["capo muratore", "capomuratore", "capo squadra muratori"],
    "carpentiere": ["carpentiere", "carpentieri"],
    "cartongessista": ["cartongessista", "cartongesso", "lastre gesso"],
    "imbianchino": ["imbianchino", "pittore edile", "tinteggiatore"],
    "serramentista": ["serramentista", "posa serramenti", "posatore serramenti", "infissi"],
    "piastrellista": ["piastrellista", "pavimentista", "posa piastrelle"],
    "capocantiere": ["capocantiere", "capo cantiere"],
}


def _norm_role(txt: Optional[str]) -> Optional[str]:
    if not txt:
        return None
    ql = txt.strip().lower()
    for canon, aliases in ROLE_ALIASES.items():
        if ql == canon or any(ql == a for a in aliases) or any(ql in a for a in aliases):
            return canon
    return ql or None


def _coerce_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "si", "sì")
    return default


def _coerce_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _coerce_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


# ---------------- Prompt LLM ----------------
_SYSTEM = """Sei un parser di intenti per un assistente aziendale edile.
Devi restituire SOLO JSON valido, conforme allo schema. Non inventare dati:
se non capisci, topic="none" e staff=null.

Regole per topic="staff":
- operation:
  - "count": chiede un numero (quanti...?)
  - "list": chiede un elenco di persone (es. "mostrami", "elenca", "solo gli X", "dimmi gli X", "quali X abbiamo", "X disponibili")
  - "where": chiede città/località (es. "dove sono", "in che città")
  - "roles": chiede l'ELENCO DEI TIPI DI RUOLO (es. "che ruoli abbiamo?", "quali ruoli ci sono?").
    ATTENZIONE: se nella frase c’è un ruolo specifico (elettricisti, muratori, capi muratori, ecc.) oppure parole su disponibilità/liberi,
    NON usare "roles" ma "list".
  - "clarify": follow-up su risposta precedente (es. "e loro?", "come prima?", "50 cosa?")
- role: normalizza in minuscolo (elettricista, idraulico, muratore, capocantiere, capo muratore, cartongessista, imbianchino, serramentista, piastrellista).
  Se non specificato -> null.
- free_only: true se chiede "liberi", "disponibili", "non assegnati".
- reuse_last: true se è follow-up che dipende dal messaggio precedente.
- limit: default 25; free_hours_threshold: default 20.0.

Output SOLO JSON.
"""

_USER = """Messaggio utente: {question}
Contesto precedente (JSON, opzionale): {last_context}

Schema atteso:
{{
  "topic": "staff" | "none",
  "staff": {{
    "topic": "staff",
    "operation": "count"|"list"|"where"|"clarify"|"roles",
    "role": string|null,
    "free_only": boolean,
    "limit": integer,
    "free_hours_threshold": number,
    "reuse_last": boolean
  }} | null
}}
Rispondi SOLO con JSON:
"""


def parse_intent_llm(llm, question: str, last_context: dict | None) -> RoutedIntent:
    """
    Ritorna RoutedIntent (topic in {"staff","none"}).
    StaffIntent è popolato quando topic="staff".
    """
    # Riduci e “sanitizza” il contesto per evitare prompt gonfi
    safe_ctx = {}
    if isinstance(last_context, dict):
        intent = last_context.get("intent") or {}
        safe_ctx = {
            "topic": last_context.get("topic"),
            "intent": {
                "operation": intent.get("operation"),
                "role": intent.get("role"),
                "free_only": intent.get("free_only"),
                "limit": intent.get("limit"),
                "free_hours_threshold": intent.get("free_hours_threshold"),
            },
        }

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("user", _USER),
    ])
    chain = prompt | llm | JsonOutputParser()

    try:
        raw = chain.invoke({
            "question": question,
            "last_context": safe_ctx
        })
    except Exception:
        # Fallback euristico minimo
        ql = question.lower()
        staffish = any(k in ql for k in [
            "dipendenti", "opera", "operai", "staff", "personale", "lavoratori",
            "impiegati", "organico", "forza lavoro", "ruoli", "ruolo", "liberi",
            "elettric", "idraulic", "murator", "cartongess", "imbianchin", "serrament",
            "piastrell", "capocantier", "capo muratore"
        ])
        if staffish:
            return RoutedIntent(topic="staff", staff=StaffIntent(
                topic="staff", operation="list", role=_norm_role(None),
                free_only=False, limit=25, free_hours_threshold=20.0, reuse_last=False
            ))
        return RoutedIntent(topic="none", staff=None)

    # Alcuni parser restituiscono già dict, altri stringa JSON
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return RoutedIntent(topic="none", staff=None)

    # Normalizzazione robusta del JSON
    topic = (data.get("topic") or "none").strip().lower()
    staff = data.get("staff")

    if topic != "staff" or not isinstance(staff, (dict,)):
        return RoutedIntent(topic="none", staff=None)

    op = (staff.get("operation") or "list").strip().lower()
    role = _norm_role(staff.get("role"))
    free_only = _coerce_bool(staff.get("free_only"), False)
    limit = _coerce_int(staff.get("limit"), 25)
    fht = _coerce_float(staff.get("free_hours_threshold"), 20.0)
    reuse_last = _coerce_bool(staff.get("reuse_last"), False)

    # --- Guardrail anti false-positive su "roles" ---
    txt = (question or "").lower()
    role_markers = [
        "elettric", "idraulic", "murator", "capo muratore", "capocantier",
        "cartongess", "imbianchin", "serrament", "piastrell"
    ]
    avail_markers = ["liberi", "disponibili", "non assegnati", "non occupati"]

    # Se il modello ha messo "roles" ma la frase contiene un ruolo o disponibilità → forza "list"
    if op == "roles" and (any(m in txt for m in role_markers) or any(m in txt for m in avail_markers)):
        op = "list"

    # Comandi telegrafici tipo "solo gli elettricisti" → list
    if txt.startswith("solo ") or txt.startswith("solo gli ") or txt.startswith("solo i "):
        op = "list"
        if not role:
            # se non ha riconosciuto il ruolo, prova a dedurlo al volo
            for canon, aliases in ROLE_ALIASES.items():
                if canon in txt or any(a in txt for a in aliases):
                    role = canon
                    break

    # Se chiede disponibilità ma l'operazione non è chiaramente "count/where/clarify" → list
    if any(m in txt for m in avail_markers) and op not in ("count", "where", "clarify"):
        op = "list"
        free_only = True

    # Costruisci StaffIntent coerente con i tuoi modelli
    staff_intent = StaffIntent(
        topic="staff",
        operation=op,
        role=role,
        free_only=free_only,
        limit=limit,
        free_hours_threshold=fht,
        reuse_last=reuse_last,
    )

    return RoutedIntent(topic="staff", staff=staff_intent)