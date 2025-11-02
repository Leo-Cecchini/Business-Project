# utils/intent_router.py
from __future__ import annotations
from typing import Optional, Any, Dict
import json
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

# Modelli Pydantic esistenti
from models.intents import RoutedIntent, StaffIntent

# ==========================
# Normalizzazione & Alias
# ==========================
ROLE_ALIASES = {
    "elettricista": ["elettricista", "elettrici", "elettrico", "elettricisti"],
    "idraulico": ["idraulico", "idraulici", "impiantista idrico", "impianto idrico"],
    "muratore": ["muratore", "muratori"],
    "capo muratore": ["capo muratore", "capomuratore", "capo squadra muratori"],
    "carpentiere": ["carpentiere", "carpentieri"],
    "cartongessista": ["cartongessista", "cartongesso", "lastre gesso", "cartongessisti"],
    "imbianchino": ["imbianchino", "pittore edile", "tinteggiatore", "imbianchini"],
    "serramentista": ["serramentista", "posa serramenti", "posatore serramenti", "infissi", "serramentisti"],
    "piastrellista": ["piastrellista", "pavimentista", "posa piastrelle", "piastrellisti"],
    "capocantiere": ["capocantiere", "capo cantiere", "capicantiere"],
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


# ==========================
# Heuristics STIMA / STAFF / DOCUMENT
# ==========================
_STRONG_ESTIMATE = [
    "stima", "preventivo", "computo", "computo metrico", "offerta",
    "capitolato", "bozza di preventivo", "stima rapida", "costi di ristrutturazione",
    "quanto costa", "quanto verrebbe", "costo totale", "budget",
    "ristrutturazione", "ristrutturare", "analisi prezzi",
]

_WEAK_WORKWORDS = [
    "appartamento", "casa", "unità", "immobile",
    "pavimento", "piastrella", "gres", "massetto", "sottofondo",
    "intonaco", "rasatura", "cartongesso", "controsoffitto", "cappotto",
    "serramento", "porte", "infissi", "battiscopa",
    "impianto elettrico", "punti luce", "prese", "frutti", "quadro elettrico",
    "dati", "ethernet", "tv", "antenna", "sat", "citofono",
    "impianto idrico", "carico", "scarico", "tubi", "multistrato", "pex", "pozzetto",
    "impianto termico", "riscaldamento", "radiatori", "caldaia", "pompa di calore",
    "bagno", "bagni", "sanitari", "doccia", "piatto doccia", "vasca",
]

_RE_MQ = re.compile(r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(mq|m2|m²)\b", re.IGNORECASE)
_RE_COUNTS = re.compile(r"\b(\d{1,4})\s*(bagni?|punti(?:\s+luce)?|prese)\b", re.IGNORECASE)
_RE_TILE = re.compile(r"\b(\d{2,3})\s*[x×]\s*(\d{2,3})\b")
_RE_GENERIC_NUM = re.compile(r"\b\d{1,4}\b")

_STAFF_PHRASES = [
    "quanti dipendenti", "quanti operai", "che ruoli", "quali ruoli",
    "elettricisti disponibili", "muratori disponibili", "lista dipendenti",
    "conta dipendenti", "capo muratore", "capocantiere", "serramentista",
    "piastrellisti", "personale", "staff", "organico", "forza lavoro", "assunzion",
    "turni", "disponibilità", "non assegnati", "liberi",
]

_DOC_MARKERS = [
    "pdf", "allegato", "documento", "documenti", "file", "excel", "xlsx", "xls",
    "confronta", "confrontare", "comparare", "comparazione",
    "analizza", "analizzare", "analisi", "estrai", "estrarre", "estrazione",
    "capitolato", "computo", "offerta", "preventivo", "contratto",
    "allegati", "upload", "caricato", "caricare", "scaricato",
]

def _looks_like_staff_query(text: str) -> bool:
    q = (text or "").lower()
    return any(p in q for p in _STAFF_PHRASES)

def _looks_like_document_query(text: str) -> bool:
    q = (text or "").lower()
    return any(m in q for m in _DOC_MARKERS) and any(v in q for v in [
        "confronta", "confrontare", "analizza", "analizzare", "estrai", "estrarre", "confronto", "estrazione", "analisi"
    ])

def _looks_like_estimate_query(text: str) -> bool:
    q = (text or "").lower()
    if _looks_like_staff_query(q):
        return False
    if _looks_like_document_query(q):
        return False
    if any(k in q for k in _STRONG_ESTIMATE):
        return True
    has_workword = any(w in q for w in _WEAK_WORKWORDS)
    has_qty = bool(_RE_MQ.search(q) or _RE_COUNTS.search(q) or _RE_TILE.search(q))
    if has_workword and (has_qty or _RE_GENERIC_NUM.search(q)):
        return True
    return False


# ======= ESTIMATE ENTITY EXTRACTOR =======
_RE_INT = re.compile(r"\d+")
def _to_int(s, default=0):
    try:
        return int(s)
    except Exception:
        return default

def _to_float_num(s, default=0.0):
    try:
        return float(str(s).replace(",", "."))
    except Exception:
        return default

def extract_estimate_entities(text: str) -> dict:
    q = (text or "").lower()
    ent: Dict[str, Any] = {"voce_lavoro": None}

    if any(k in q for k in ("gres", "piastrell", "paviment")):
        ent["voce_lavoro"] = "pavimento gres"
    elif "cartongesso" in q:
        ent["voce_lavoro"] = "cartongesso"
    elif "intonaco" in q:
        ent["voce_lavoro"] = "intonaco"
    elif "cappotto" in q:
        ent["voce_lavoro"] = "cappotto"
    elif "impianto elettrico" in q or any(k in q for k in ("punti luce","prese","dati","tv")):
        ent["voce_lavoro"] = "impianto elettrico"
    elif "impianto idrico" in q or "bagno" in q or "bagni" in q:
        ent["voce_lavoro"] = "impianto idrico"

    m_fmt = re.search(r"(\d{2,3})\s*[x×]\s*(\d{2,3})", q)
    if m_fmt:
        ent["dimensioni"] = [f"{m_fmt.group(1)}x{m_fmt.group(2)}"]

    m_th = re.search(r"(\d{1,3})\s*(mm|cm)\b", q)
    if m_th:
        val = _to_float_num(m_th.group(1), 0.0)
        ent["spessori_mm"] = int(round(val * 10)) if m_th.group(2) == "cm" else int(round(val))

    m_mq = re.search(r"(\d{1,4})(?:[.,]\d+)?\s*(mq|m2|m²)\b", q)
    if m_mq:
        ent["qty"] = _to_float_num(m_mq.group(1))
        ent["unit"] = "m2"

    m_pl = re.search(r"(\d{1,4})\s*punti?\s*luce", q)
    m_pr = re.search(r"(\d{1,4})\s*(punti?\s*)?prese?", q)
    m_pd = re.search(r"(\d{1,4})\s*(punti?\s*)?(dati|ethernet)", q)
    m_tv = re.search(r"(\d{1,4})\s*(punti?\s*)?tv", q)
    if m_pl: ent["punti_luce"]  = _to_int(m_pl.group(1))
    if m_pr: ent["punti_prese"] = _to_int(m_pr.group(1))
    if m_pd: ent["punti_dati"]  = _to_int(m_pd.group(1))
    if m_tv: ent["punti_tv"]    = _to_int(m_tv.group(1))

    m_tr = re.search(r"(\d{1,4})(?:[.,]\d+)?\s*m(?:etri)?\s*tracc", q)
    if m_tr:
        ent["metri_tracce"] = _to_float_num(m_tr.group(1))

    m_bagni = re.search(r"(\d{1,2})\s*bagni?", q)
    if m_bagni: ent["n_bagni"] = _to_int(m_bagni.group(1))
    m_p_extra = re.search(r"(\d{1,3})\s*punti?\s*(idrici|acqua)", q)
    if m_p_extra: ent["punti_idrici_extra"] = _to_int(m_p_extra.group(1))

    return {k: v for k, v in ent.items() if v not in (None, "", [])}


# ==========================
# MATERIALS Heuristics
# ==========================
_MATERIAL_TRIGGERS = [
    r"\bmaterial", r"\bforniture?\b", r"\bmagazzino\b", r"\bsku\b",
    r"\bcartongesso\b", r"\bpittura\b", r"\bintonaco\b", r"\bcappotto\b",
    r"\bmalta\b", r"\bcemento\b", r"\badesivo\b", r"\bvernice\b", r"\bmp\b",
]
_UNIT_RE = re.compile(r"\b(kg|m2|m3|pz|lt|m)\b", re.IGNORECASE)
_CAT_RE  = re.compile(r"categoria[:\\s]*([a-zA-Z0-9\\s_-]+)")
_SUB_RE  = re.compile(r"sotto\\s*categoria[:\\s]*([a-zA-Z0-9\\s_-]+)")
_SKU_RE  = re.compile(r"\bsku[:\\s]*([A-Z0-9._\\-]+)\b", re.IGNORECASE)

def _looks_like_material_query(text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t) for p in _MATERIAL_TRIGGERS) or bool(_SKU_RE.search(t))

def extract_material_query(text: str) -> dict:
    """
    Ritorna un dict:
      {
        "operation": "lookup"|"search",
        "query": "<testo>",
        "filters": {"unit":..., "category":..., "subcategory":...} (se presenti),
        "sku": "..." (se trovato)
      }
    """
    q = (text or "").strip()
    out: Dict[str, Any] = {"operation": "search", "query": q, "filters": {}}

    m_sku = _SKU_RE.search(q)
    if m_sku:
        out["operation"] = "lookup"
        out["sku"] = m_sku.group(1).upper()

    m_unit = _UNIT_RE.search(q)
    if m_unit:
        out["filters"]["unit"] = m_unit.group(1).lower()

    m_cat = _CAT_RE.search(q)
    if m_cat:
        out["filters"]["category"] = m_cat.group(1).strip()

    m_sub = _SUB_RE.search(q)
    if m_sub:
        out["filters"]["subcategory"] = m_sub.group(1).strip()

    return out


# ==========================
# Prompt LLM (solo per STAFF)
# ==========================
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
{
  "topic": "staff" | "none",
  "staff": {
    "topic": "staff",
    "operation": "count"|"list"|"where"|"clarify"|"roles",
    "role": string|null,
    "free_only": boolean,
    "limit": integer,
    "free_hours_threshold": number,
    "reuse_last": boolean
  } | null
}
Rispondi SOLO con JSON:
"""


def parse_intent_llm(llm, question: str, last_context: dict | None):
    """
    Ritorna dict con:
      - intent in {"MATERIALI","STIMA","STAFF","DOCUMENTO","none"}
      - materials (se MATERIALI)
      - entities (se STIMA)
      - staff (schema StaffIntent per STAFF)
    """
    qtxt = question or ""

    # 0) MATERIALI (priorità altissima se è presente SKU o trigger materiali)
    if _looks_like_material_query(qtxt):
        mat = extract_material_query(qtxt)
        return {"intent": "MATERIALI", "materials": mat, "staff": None, "entities": {}}

    # 1) DOCUMENT (priorità alta)
    if _looks_like_document_query(qtxt):
        return {"intent": "DOCUMENTO", "materials": None, "staff": None, "entities": {}}

    # 2) STIMA (euristico + entità)
    if _looks_like_estimate_query(qtxt):
        return {
            "intent": "STIMA",
            "materials": None,
            "staff": None,
            "entities": extract_estimate_entities(qtxt)
        }

    # 3) STAFF via LLM (schema rigido)
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

    # ✅ Se l'LLM non è disponibile, usa un fallback euristico per evitare crash
    if llm is None:
        ql = qtxt.lower()
        staffish = any(k in ql for k in [
            "dipendenti", "opera", "operai", "staff", "personale", "lavoratori",
            "impiegati", "organico", "forza lavoro", "ruoli", "ruolo", "liberi",
            "elettric", "idraulic", "murator", "cartongess", "imbianchin", "serrament",
            "piastrell", "capocantier", "capo muratore",
        ])
        if staffish:
            return {
                "intent": "STAFF",
                "materials": None,
                "staff": StaffIntent(
                    topic="staff",
                    operation="list",
                    role=_norm_role(None),
                    free_only=False,
                    limit=25,
                    free_hours_threshold=20.0,
                    reuse_last=False,
                ),
                "entities": {}
            }
        return {"intent": "none", "materials": None, "staff": None, "entities": {}}

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("user", _USER),
    ])
    chain = prompt | llm | JsonOutputParser()

    try:
        raw = chain.invoke({
            "question": qtxt,
            "last_context": safe_ctx
        })
    except Exception:
        # Fallback euristico minimo sullo STAFF
        ql = qtxt.lower()
        staffish = any(k in ql for k in [
            "dipendenti", "opera", "operai", "staff", "personale", "lavoratori",
            "impiegati", "organico", "forza lavoro", "ruoli", "ruolo", "liberi",
            "elettric", "idraulic", "murator", "cartongess", "imbianchin", "serrament",
            "piastrell", "capocantier", "capo muratore",
        ])
        if staffish:
            return {
                "intent": "STAFF",
                "materials": None,
                "staff": StaffIntent(
                    topic="staff",
                    operation="list",
                    role=_norm_role(None),
                    free_only=False,
                    limit=25,
                    free_hours_threshold=20.0,
                    reuse_last=False,
                ),
                "entities": {}
            }
        return {"intent": "none", "materials": None, "staff": None, "entities": {}}

    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return {"intent": "none", "materials": None, "staff": None, "entities": {}}

    topic = (data.get("topic") or "none").strip().lower()
    staff = data.get("staff")

    if topic != "staff" or not isinstance(staff, dict):
        if _looks_like_document_query(qtxt):
            return {"intent": "DOCUMENTO", "materials": None, "staff": None, "entities": {}}
        if _looks_like_estimate_query(qtxt):
            return {"intent": "STIMA", "materials": None, "staff": None, "entities": extract_estimate_entities(qtxt)}
        return {"intent": "none", "materials": None, "staff": None, "entities": {}}

    op = (staff.get("operation") or "list").strip().lower()
    role = _norm_role(staff.get("role"))
    free_only = _coerce_bool(staff.get("free_only"), False)
    limit = _coerce_int(staff.get("limit"), 25)
    fht = _coerce_float(staff.get("free_hours_threshold"), 20.0)
    reuse_last = _coerce_bool(staff.get("reuse_last"), False)

    txt = qtxt.lower()
    role_markers = [
        "elettric", "idraulic", "murator", "capo muratore", "capocantier",
        "cartongess", "imbianchin", "serrament", "piastrell",
    ]
    avail_markers = ["liberi", "disponibili", "non assegnati", "non occupati"]

    if op == "roles" and (any(m in txt for m in role_markers) or any(m in txt for m in avail_markers)):
        op = "list"

    if txt.startswith("solo ") or txt.startswith("solo gli ") or txt.startswith("solo i "):
        op = "list"
        if not role:
            for canon, aliases in ROLE_ALIASES.items():
                if canon in txt or any(a in txt for a in aliases):
                    role = canon
                    break

    if any(m in txt for m in avail_markers) and op not in ("count", "where", "clarify"):
        op = "list"
        free_only = True

    staff_intent = StaffIntent(
        topic="staff",
        operation=op,
        role=role,
        free_only=free_only,
        limit=limit,
        free_hours_threshold=fht,
        reuse_last=reuse_last,
    )
    return {"intent": "STAFF", "materials": None, "staff": staff_intent, "entities": {}}


# ---------------- Convenience router ----------------
def route(question: str, llm=None, last_context: dict | None = None) -> dict:
    """
    Entry-point usabile da routes/chat.py:
      ritorna sempre: {
        "intent": "...",            # MATERIALI | STIMA | STAFF | DOCUMENTO | none
        "materials": {...}|None,    # se intent == MATERIALI
        "entities": {...},          # se intent == STIMA
        "staff": StaffIntent|None   # se intent == STAFF
      }
    """
    return parse_intent_llm(llm, question, last_context)

# ---------------- Lightweight class wrapper ----------------
class IntentRouter:
    """
    Wrapper compatibile con app.py/chat.py.
    Puoi passarci un LLM (ad es. quello di ChatModel) oppure lasciarlo None:
    - se llm è None, il routing userà solo le euristiche locali;
    - se llm è presente, lo impiega per i casi STAFF con schema strutturato.
    """
    def __init__(self, llm=None, api_key: str | None = None):
        self.llm = llm
        self.api_key = api_key  # tenuto per compatibilità, non usato qui

    def route(self, question: str, last_context: dict | None = None) -> dict:
        return parse_intent_llm(self.llm, question, last_context)


__all__ = [
    "IntentRouter",
    "route",
    "parse_intent_llm",
    "extract_estimate_entities",
]