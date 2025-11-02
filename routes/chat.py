# routes/chat.py
from __future__ import annotations
import uuid
import logging
import os
from flask import Blueprint, request, jsonify, session, g, current_app
from mongoengine.connection import get_db
from pymongo.errors import OperationFailure
import unicodedata
import time
from datetime import datetime
import json


log = logging.getLogger("chat")

# --- DB helpers per risposte deterministiche (MongoEngine) ---
import re
from models_mongo.worker import WorkerDoc
from models_mongo.material import MaterialDoc
from models_mongo.project import ProjectDoc
from mongoengine.queryset.visitor import Q
from utils.intent_router import route as route_intent


chat_bp = Blueprint("chat", __name__)

def _doc_m(doc):
    return {
        "id": str(doc.id),
        "name": doc.name,
        "sku": getattr(doc, "sku", None),
        "unit": getattr(doc, "unit", None),
        "category": getattr(doc, "category", None),
        "supplier": getattr(doc, "supplier", None),
        "aliases": getattr(doc, "aliases", []),
        "unit_price_eur_2025": getattr(doc, "unit_price_eur_2025", None),
    }


def _doc_w(w):
    return {
        "id": str(w.id),
        "name": w.name,
        "role": w.role,
        "available": w.available,
        "home_city": w.home_city,
        "aliases": w.aliases or [],
        "skills": w.skills or [],
    }


HEADCOUNT_RE = re.compile(
    r"\b(quant\w*|quas\w*|numero|totale|tot)\b.*\b(impiegat\w*|opera\w*|dipendent\w*|personale|staff|lavorator\w*)\b",
    re.IGNORECASE
)

# Saluti semplici (short-circuit: evita passaggi pesanti quando la UI manda un ping tipo "Ciao")
GREETING_RE = re.compile(r"\b(ciao|buongiorno|buonasera|salve|hey|hei|hi|hello)\b", re.IGNORECASE)

def _is_greeting(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # consideriamo saluto se è molto corto o è solo una parola di saluto
    if len(t) <= 12 and GREETING_RE.search(t):
        return True
    # frasi tipo "ciao, come va" → comunque saluto
    if GREETING_RE.match(t):
        return True
    return False

# --- Safe count helper for Mongo index conflicts ---

def safe_count(queryset_callable):
    """Esegue una count() o simili e autoripara eventuali conflitti di indici Mongo.
    Usa l'ensure indici dell'app e riprova una sola volta.
    """
    try:
        return queryset_callable()
    except OperationFailure as e:
        if getattr(e, "code", None) == 85 or "IndexOptionsConflict" in str(e):
            try:
                try:
                    from db.mongo import ensure_indexes_safely as _fix
                except ImportError:
                    from db.mongo import ensure_mongo_indexes as _fix
                _fix()
                return queryset_callable()
            except Exception:
                pass
        # Se non è un conflitto indici o il fix fallisce, rilancia
        raise

# --- Index reconciliation to avoid Mongo code 85 on MaterialDoc ---

def try_headcount(text: str):
    if not HEADCOUNT_RE.search(text or ""):
        return None
    tot = safe_count(lambda: WorkerDoc.objects.count())
    disp = safe_count(lambda: WorkerDoc.objects(available=True).count())
    return {"INTENT_DB":"HEADCOUNT", "answer": f"Totale personale: {tot} (disponibili: {disp})."}

def try_role_of_person(text: str):
    m = re.search(r"che\s+lavoro\s+fa\s+(.+?)\??$", (text or "").strip(), re.IGNORECASE)
    if not m: return None
    name = m.group(1).strip()
    w = WorkerDoc.objects(name__iexact=name).first() or WorkerDoc.objects(name__icontains=name).first()
    if not w:
        return {"INTENT_DB":"ROLE_LOOKUP", "answer": f"Non trovo {name} nel personale."}
    return {"INTENT_DB":"ROLE_LOOKUP", "answer": f"{w.name} è {w.role}."}

 # --- List workers by role intent (robusto, senza duplicati) ---
ROLE_LIST_RE = re.compile(
    r"\b(chi\s+sono|elenco|lista|quali)\b.*\b(murator\w*|elettricist\w*|idraulic\w*|carpent\w*|piastrell\w*|imbianch\w*|falegn\w*|manoval\w*|opera\w*|impieg\w*)\b",
    re.IGNORECASE
)

ROLE_ROOTS = {
    "murator": "muratori",
    "elettric": "elettricisti",
    "idraul": "idraulici",
    "carpent": "carpentieri",
    "piastrell": "piastrellisti",
    "imbianch": "imbianchini",
    "falegn": "falegnami",
    "manoval": "manovali",
    "opera": "operai",
    "impieg": "impiegati",
}

def try_list_by_role(text: str):
    m = ROLE_LIST_RE.search(text or "")
    if not m:
        return None
    word = m.group(2).lower()
    root = next((r for r in ROLE_ROOTS if r in word), None)
    if not root:
        return None
    qs = WorkerDoc.objects(role__icontains=root)
    names = sorted({w.name for w in qs.only("name").limit(200)})
    if not names:
        return {"INTENT_DB": "ROLE_LIST", "answer": f"Nessun {ROLE_ROOTS[root]} trovato."}
    label = ROLE_ROOTS[root]
    first = names[:20]
    return {"INTENT_DB": "ROLE_LIST", "answer": f"Ecco {len(first)} {label}: " + ", ".join(first)}


UNIT_MAP = {"mq":"m2","m²":"m2","mc":"m3","m³":"m3","l":"lt","litri":"lt","pezzi":"pz","pezzo":"pz","cart":"pz","bomb":"pz"}

# Gruppi di sinonimi per materiali (OR tra sinonimi dello stesso concetto)
MATERIAL_SYNONYM_GROUPS = [
    {"cemento", "cem", "portland"},
    {"calcestruzzo", "cls"},
    {"malta", "premiscelato", "m5"},
    {"intonaco", "civile"},
    {"calce", "idrata", "idratazione"},
    {"cartongesso", "gkb", "lastra"},
    {"rete", "elettrosaldata", "rete6", "rete 6"},
    {"acciaio", "barra", "tondino", "b450", "b450c", "b450d"},
    {"pittura", "lavabile", "smalto", "idropittura"},
    {"stucco", "fughe"},
    {"primer", "bituminoso", "poliuretanico"},
    {"guaina", "bituminosa", "ardesiata", "epdm"},
    {"eps", "polistirene", "isolante"},
    {"xps", "polistirene", "isolante"},
    {"lana", "roccia", "isolante"},
    {"nastro", "butilico"},
    {"additivo", "antigelo", "fluidificante"},
    {"sabbia"},
    {"ghiaia", "pietrisco"},
    {"piastrella", "gres"},
    {"colla", "c2te", "adesivo"},
    {"vite"},
    {"tassello"},
    {"taglierino"},
    {"tubo", "corrugato"},
    {"cavo", "fg16or"},
    {"scatola", "503"},
    {"placca"},
    {"interruttore"},
    {"presa", "schuko"},
    {"quadro", "elettrico"},
    {"magnetotermico"},
    {"differenziale", "rcd"},
    {"multistrato", "raccordo", "press"},
    {"valvola", "sfera"},
    {"rubinetto", "lavabo", "piletta"},
    {"frattazzo", "spugna"},
    {"mazzetta"},
    {"detergente", "cementizio"},
    {"scopa", "industriale"},
]

_SYNONYM_TO_ROOT = {}
for group in MATERIAL_SYNONYM_GROUPS:
    root = sorted(group, key=len)[0]
    for s in group:
        _SYNONYM_TO_ROOT[s] = root

def _normalize_material_tokens(text: str) -> list[list[str]]:
    """Converte il testo in gruppi di sinonimi. Ogni gruppo è una lista di varianti (OR)."""
    if not text:
        return []
    cleaned = re.sub(r"(?i)\b(prezzo|quanto|costa|al|allo|alla|per|unit(a|à)|sku[:\s]*[A-Z0-9\-]+)\b", " ", text)
    raw_tokens = re.findall(r"[A-Za-z]+|\d+(?:[.,]\d+)?[A-Za-z]?", cleaned.lower())
    raw_tokens = [t.strip().replace(",", ".") for t in raw_tokens if len(t.strip()) >= 2]

    groups: list[list[str]] = []
    seen = set()
    for tok in raw_tokens:
        variants = {tok}
        m = re.match(r"^(\d+(?:\.\d+)?)([a-z])$", tok)
        if m:
            variants.add(f"{m.group(1)} {m.group(2)}")
        root = _SYNONYM_TO_ROOT.get(tok)
        if root:
            syns = {v for v, r in _SYNONYM_TO_ROOT.items() if r == root}
            variants |= syns
        norm = sorted({" ".join(v.split()) for v in variants})
        key = tuple(norm)
        if key in seen:
            continue
        seen.add(key)
        groups.append(norm)
    return groups

def _material_answer(mdoc: MaterialDoc) -> dict:
    price = mdoc.unit_price_eur_2025 if mdoc.unit_price_eur_2025 is not None else 0.0
    return {
        "INTENT_DB": "MATERIAL_PRICE",
        "answer": (
            f"{mdoc.name}: {price:.2f} €/ {mdoc.unit} (SKU {mdoc.sku}). "
            f"Stock: {int(mdoc.stock_qty or 0)}, Lead time: {int(mdoc.lead_time_days or 0)} gg, IVA: {int(mdoc.vat_rate or 0)}%."
        ),
    }

def try_material_price(text: str):
    if not text:
        return None

    # 1) unità (sinonimi)
    unit = None
    for u in ["kg","m2","m3","pz","lt","m","mq","m²","mc","m³","l","litri","pezzi","pezzo","cart","bomb"]:
        if re.search(rf"\b{re.escape(u)}\b", text, re.IGNORECASE):
            unit = UNIT_MAP.get(u, u)
            break

    # 2) SKU realistico (es. CEM325R) — '32.5R' NON è SKU
    sku_match = re.search(r"\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]*)\b", text.upper())
    if sku_match:
        mdoc = MaterialDoc.objects(sku=sku_match.group(1)).first()
        if mdoc:
            return _material_answer(mdoc)

    # 3) Token + sinonimi: AND tra concetti, OR dentro ciascun gruppo
    groups = _normalize_material_tokens(text)
    if not groups:
        return None

    q = None
    for variants in groups:
        q_or = None
        for v in variants:
            cond = Q(name__icontains=v)
            q_or = cond if q_or is None else (q_or | cond)
        q = q_or if q is None else (q & q_or)

    qs = MaterialDoc.objects
    if q is not None:
        qs = qs.filter(q)
    if unit:
        qs = qs.filter(unit=unit)

    mdoc = qs.order_by("name").first()
    if not mdoc and unit:
        # ultimo tentativo senza vincolo unità
        qs2 = MaterialDoc.objects
        if q is not None:
            qs2 = qs2.filter(q)
        mdoc = qs2.order_by("name").first()

    if not mdoc:
        return None
    return _material_answer(mdoc)

TRUTHY_TEXT = {"1", "true", "si", "sì", "yes", "y"}

def _is_truthy_available_filter():
    """Costruisce un filtro Mongo per interpretare 'available' come vero in vari formati."""
    return {
        "$or": [
            {"available": True},
            {"available": 1},
            {"available": "1"},
            {"available": "true"},
            {"available": "True"},
            {"available": "si"},
            {"available": "sì"},
            {"available": "yes"},
            {"available": "y"},
        ]
    }

def _workers_count(role_icontains: str | None = None) -> int:
    if not WorkerDoc:
        return 0
    q = WorkerDoc.objects
    if role_icontains:
        q = q.filter(role__icontains=role_icontains)
    return safe_count(lambda: q.count())

def _workers_available_count(role_icontains: str | None = None) -> int:
    if not WorkerDoc:
        return 0
    raw = _is_truthy_available_filter()
    if role_icontains:
        q = WorkerDoc.objects(__raw__=raw).filter(role__icontains=role_icontains)
    else:
        q = WorkerDoc.objects(__raw__=raw)
    return safe_count(lambda: q.count())

def _materials_exists_and_nonempty() -> tuple[bool, int]:
    if not MaterialDoc:
        return False, 0
    try:
        c = safe_count(lambda: MaterialDoc.objects.count())
        return (c > 0), c
    except Exception:
        return False, 0

def _materials_best_match(name_like_norm: str):
    """Ritorna il materiale con match migliore su name/category/subcategory."""
    if not MaterialDoc:
        return None
    if not name_like_norm:
        return None
    # Primo tentativo: name contains
    rows = list(MaterialDoc.objects(name__icontains=name_like_norm).order_by("name"))
    if not rows:
        # Secondo tentativo: category/subcategory
        rows = list(MaterialDoc.objects(__raw__={
            "$or": [
                {"category": {"$regex": name_like_norm, "$options": "i"}},
                {"subcategory": {"$regex": name_like_norm, "$options": "i"}},
            ]
        }).order_by("category", "subcategory", "name"))
        if not rows:
            return None
    # Semplice scoring: esatto > startswith > contains
    nl = name_like_norm.lower()
    def _score(m):
        name_l = (getattr(m, "name", "") or "").lower()
        s = 0
        if name_l == nl: s += 10
        if name_l.startswith(nl): s += 5
        if nl in name_l: s += 2
        return s
    rows.sort(key=_score, reverse=True)
    return rows[0]


def _projects_counts() -> tuple[int, int]:
    if not ProjectDoc:
        return 0, 0
    try:
        tot = safe_count(lambda: ProjectDoc.objects.count())
        att = safe_count(lambda: ProjectDoc.objects(status__in=["Confermato", "In corso", "Attivo", "Active"]).count())
        return int(tot), int(att)
    except Exception:
        return 0, 0

# Direct PyMongo count for fault tolerance
def _projects_counts_direct() -> tuple[int, int]:
    """Conta cantieri usando PyMongo diretto, per evitare effetti collaterali degli ODM.
    Ritorna (totale, attivi)."""
    db = get_db()
    tot = db["projects"].count_documents({})
    att = db["projects"].count_documents({"status": {"$in": ["Confermato", "In corso", "Attivo", "Active"]}})
    return int(tot), int(att)

# ----- import opzionali con fallback -----------------------------------------
try:
    from utils.numparse import quick_extract, parse_prices
except Exception:
    # fallback minimi
    def quick_extract(q: str):
        return {"qty": None, "unit": None, "thickness_mm": None, "dimensions": None}
    def parse_prices(text: str):
        return []

try:
    # calcolatori baseline (opzionali)
    from models.estimators import pick_and_estimate
except Exception:
    def pick_and_estimate(_entities):  # fallback: nessuna stima
        return None

# ------------------------ Helpers --------------------------------------------
def _normalize_intent(raw: str) -> str:
    r = (raw or "").strip().lower()
    if r in ("stima", "estimate", "preventivo"):
        return "STIMA"
    if r in ("staff", "personale"):
        return "STAFF"
    if r in ("documento", "document", "doc"):
        return "DOCUMENTO"
    return "none"


def _format_estimate_text(calc: dict | None) -> str:
    if not calc or not isinstance(calc, dict):
        return ""
    lines = [
        "\n\n[STIMA CALCOLATA]",
        "- Questa sezione contiene la stima strutturata calcolata (non modificarne i numeri).",
    ]
    budget = (calc.get("project") or {}).get("budget") or {}
    if budget:
        m = budget.get("materials"); l = budget.get("labor"); t = budget.get("total")
        lines.append(f"- Quadro economico: Materiali={m} €, Manodopera={l} €, Totale={t} €")
    for ch in (calc.get("chunks") or [])[:3]:
        scope = ch.get("scope", "voce")
        sm = ch.get("subtotal_materials"); sl = ch.get("subtotal_labor")
        lines.append(f"- {scope}: materiali={sm} €, manodopera={sl} €")
    return "\n".join(lines)


# --- Helper: costruzione calc_json minimale da auto_estimate ---
def _build_calc_from_auto(auto: dict | None, question: str = "") -> dict | None:
    """Converte una stima auto_estimate (se presente) in uno schema `calc_json`
    minimale per la UI. Non fa assunzioni forti: se mancano dettagli, produce
    strutture vuote ma coerenti con lo schema atteso dal frontend.
    """
    if not auto or not isinstance(auto, dict):
        return None

    # scope di fallback dal testo della domanda (estrae poche parole chiave)
    fallback_scope = None
    ql = (question or "").strip()
    if ql:
        # prendi prime 7 parole utili come descrizione sintetica
        tokens = [t for t in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", ql)][:7]
        if tokens:
            fallback_scope = " ".join(tokens)

    calc = {
        "calc_id": str(uuid.uuid4()),
        "scope": (auto.get("work") or auto.get("scope") or (auto.get("project") or {}).get("name") or fallback_scope or "lavoro"),
        "materials": [],
        "labor": [],
        "totals": {"materials": 0.0, "labor": 0.0, "total": 0.0},
    }

    # prova a leggere eventuali righe
    # Formati possibili: auto["materials"], auto["labor"], oppure in chunks
    mats = auto.get("materials") or []
    lab  = auto.get("labor") or []
    if not mats and not lab:
        for ch in auto.get("chunks", []) or []:
            for m in ch.get("materials", []) or []:
                mats.append(m)
            for l in ch.get("labor", []) or []:
                lab.append(l)

    # normalizza materiali
    out_mats = []
    for m in mats:
        if not isinstance(m, dict):
            continue
        out_mats.append({
            "code": m.get("code") or m.get("sku"),
            "desc": m.get("desc") or m.get("description") or m.get("name") or "",
            "qty": float(m.get("qty") or m.get("quantity") or 0),
            "unit": m.get("unit") or m.get("uom") or "",
            "unit_price": float(m.get("unit_price") or m.get("price") or 0),
            "total": float(m.get("total") or 0),
        })

    # normalizza manodopera
    out_lab = []
    for l in lab:
        if not isinstance(l, dict):
            continue
        out_lab.append({
            "role": l.get("role") or l.get("name") or "",
            "hours": float(l.get("hours") or l.get("qty") or l.get("quantity") or 0),
            "hourly": float(l.get("hourly") or l.get("rate") or 0),
            "total": float(l.get("total") or 0),
        })

    # totali
    t_mat = sum((m.get("total") or 0) for m in out_mats)
    t_lab = sum((l.get("total") or 0) for l in out_lab)
    t_tot = float(auto.get("total") or auto.get("grand_total") or (t_mat + t_lab))

    budget = (auto.get("project") or {}).get("budget") or {}
    if budget:
        # se presenti, preferisci i totali espliciti del budget
        t_mat = float(budget.get("materials") or t_mat)
        t_lab = float(budget.get("labor") or t_lab)
        t_tot = float(budget.get("total") or (t_mat + t_lab))

    calc["materials"] = out_mats
    calc["labor"] = out_lab
    calc["totals"] = {"materials": t_mat, "labor": t_lab, "total": t_tot}
    return calc


def _ensure_calc_block(res: dict, auto_estimate: dict | None, question: str) -> dict:
    """Se la risposta testuale non contiene già un blocco ```calc_json```, e se è
    disponibile una stima `auto_estimate`, appende un blocco calc_json con uno
    schema coerente per il frontend. Ritorna `res` (mutato)."""
    text_key = "reply" if res.get("reply") else "answer" if res.get("answer") else "text" if res.get("text") else None
    if not text_key:
        return res

    text = res.get(text_key) or ""
    if re.search(r"```calc_json\s*[\s\S]*?```", text, flags=re.I):
        return res  # già presente, non duplicare

    calc = _build_calc_from_auto(auto_estimate, question)
    if not calc:
        return res

    try:
        block = "\n\n```calc_json\n" + json.dumps(calc, ensure_ascii=False) + "\n```"
    except Exception:
        return res

    res[text_key] = (text or "") + block
    # utile anche avere il calc nel payload per usi futuri
    res.setdefault("calc", calc)
    return res

# --- Helpers normalizzazione testo per materiali ---
STOP_WORDS = {"dimmi","il","lo","la","i","gli","le","del","dello","della","dei","degli","delle","di","da","in","su","per","con","tra","fra","quanto","costa","prezzo","costo","fammi","vedere","mostra"}
def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    # rimuovi accenti
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    # sostituisci separatori/punteggiatura con spazio
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in ".,/-_+":
            out.append(" ")
        else:
            out.append(" ")
    s = " ".join(" ".join(out).split())
    return s

def _like_from_tokens(text: str) -> str:
    tokens = [t for t in text.split() if t and t not in STOP_WORDS]
    if not tokens:
        return "%"
    return "%" + "%".join(tokens) + "%"

# --- Headcount helper: intercetta richieste generiche totali (impiegati/staff/operai/dipendenti) ---
def _is_generic_headcount(q: str) -> bool:
    ql = (q or "").lower()
    return (
        any(t in ql for t in [
            "impiegat", "operai", "dipendenti", "personale", "staff", "lavoratori", "forza lavoro", "organico"
        ])
        and any(t in ql for t in ["quanti", "numero", "quanta", "quante", "totali", "totale"])
    )

# ------------------------ Route principale -----------------------------------
@chat_bp.post("/chat")
def chat_route():
    """Chat dell’assistente edile (Gemini 2.5) con RAG locale, web (opzionale) e calc_json."""
    data = request.get_json(force=True) or {}
    enforced_pid = data.get("__enforced_pid")
    try:
        # ---- input -----------------------------------------------------------
        q = (data.get("message") or data.get("question") or "").strip()
        _t0 = time.perf_counter()
        # ---- DB-first intents (minimal, deterministic) --------------------
        for _fn in (try_headcount, try_role_of_person, try_list_by_role, try_material_price):
            _res = _fn(q)
            if _res:
                return jsonify(_res), 200
        # -------------------------------------------------------------------
        if not q:
            return jsonify({"error": "Domanda vuota"}), 422

        # Short-circuit per saluti: risposta rapida e nessun carico su router/vector store
        if _is_greeting(q):
            return jsonify({"answer": "Ciao! Dimmi pure cosa ti serve: materiali, personale o lavori del cantiere."}), 200

        # === PRE-HOOK: Intent routing DB-first (prima del modello) ===
        try:
            intent = route_intent(q)
        except Exception:
            intent = None

        if intent is not None:
            # MATERIALS_LOOKUP → SKU diretto
            if getattr(intent, "kind", None) == "MATERIALS_LOOKUP":
                m = MaterialDoc.objects(sku=getattr(intent, "query", None)).first()
                if m:
                    return jsonify({
                        "answer": f"Ho trovato 1 materiale con SKU {intent.query}.",
                        "materials": [_doc_m(m)],
                        "meta": {"routed": "MATERIALS_LOOKUP"}
                    }), 200
                return jsonify({
                    "answer": f"Nessun materiale con SKU {intent.query}.",
                    "materials": [],
                    "meta": {"routed": "MATERIALS_LOOKUP"}
                }), 200

            # MATERIALS_SEARCH → pipeline ibrida (aliases → name → text → fuzzy)
            if getattr(intent, "kind", None) == "MATERIALS_SEARCH":
                base = MaterialDoc.objects
                f = getattr(intent, "filters", None) or {}
                if f.get("category"):
                    base = base.filter(category__icontains=f["category"])
                if f.get("unit"):
                    base = base.filter(unit__iexact=f["unit"]) 

                qtxt = q
                hits = list(base.filter(aliases__icontains=qtxt).limit(20))
                if not hits:
                    hits = list(base.filter(name__icontains=qtxt).limit(20))
                if not hits:
                    try:
                        hits = list(base.search_text(qtxt).order_by("$text_score").limit(20))
                    except Exception:
                        hits = []
                if not hits:
                    import re as _re
                    pattern = ".*".join(map(_re.escape, qtxt.split()))
                    hits = list(base.filter(Q(name__iregex=pattern) | Q(aliases__iregex=pattern)).limit(20))

                if hits:
                    return jsonify({
                        "answer": f"Ho trovato {len(hits)} materiali pertinenti.",
                        "materials": [_doc_m(x) for x in hits],
                        "meta": {"routed": "MATERIALS_SEARCH"}
                    }), 200
                # altrimenti lascia proseguire al modello (fallback)

            # WORKERS_COUNT
            if getattr(intent, "kind", None) == "WORKERS_COUNT":
                total = safe_count(lambda: WorkerDoc.objects.count())
                avail = safe_count(lambda: WorkerDoc.objects(available=True).count())
                return jsonify({
                    "answer": f"Operai totali: {int(total)}. Disponibili ora: {int(avail)}.",
                    "workers": {"total": int(total), "available": int(avail)},
                    "meta": {"routed": "WORKERS_COUNT"}
                }), 200

            # WORKERS_SEARCH
            if getattr(intent, "kind", None) == "WORKERS_SEARCH":
                qs = WorkerDoc.objects
                hits_w = list(qs.filter(aliases__icontains=q).limit(40))
                if not hits_w:
                    hits_w = list(qs.filter(Q(role__icontains=q) | Q(name__icontains=q)).limit(40))
                if not hits_w:
                    try:
                        hits_w = list(qs.search_text(q).order_by("$text_score").limit(40))
                    except Exception:
                        hits_w = []
                if hits_w:
                    return jsonify({
                        "answer": f"Ho trovato {len(hits_w)} operai pertinenti.",
                        "workers": [_doc_w(w) for w in hits_w],
                        "meta": {"routed": "WORKERS_SEARCH"}
                    }), 200
                # se vuoto → lascia al modello

        # ----- Intent aziendali con risposta dal DB (prima del RAG) -----
        m = q.lower()

        # Quanti <ruolo> liberi/disponibili?
        if re.search(r"\b(liber[oi]|disponibil[ei])\b", m):
            # mappa ruoli comuni a radici per match robusto
            role_roots = [
                        "elettric", "murator", "idraul", "carpent", "piastrell",
                        "imbianch", "falegn", "manoval", "opera", "impieg"
            ]
            role_term = None
            for root in role_roots:
                if root in m:
                    role_term = root
                    break
            if role_term:
                cnt = _workers_available_count(role_term)
                log.warning("INTENT_DB → %s liberi: %s", role_term, int(cnt))
                # formato risposta naturale
                ruolo_label = {
                    "elettric": "elettricisti",
                    "murator": "muratori",
                    "idraul": "idraulici",
                    "carpent": "carpentieri",
                    "piastrell": "piastrellisti",
                    "imbianch": "imbianchini",
                    "falegn": "falegnami",
                    "manoval": "manovali",
                    "opera": "operai",
                    "impieg": "impiegati",
                }.get(role_term, f"{role_term} (liberi)")
                return jsonify({"answer": f"Ci sono {int(cnt)} {ruolo_label} disponibili."}), 200

        # Quanti cantieri?
        if re.search(r"\b(quanti|numero)\b.*\b(cantier[ei])\b", m):
            try:
                tot, att = _projects_counts_direct()
            except OperationFailure as e:
                # Code 85 = IndexOptionsConflict → autoripara e ritenta una volta
                if getattr(e, "code", None) == 85 or "IndexOptionsConflict" in str(e):
                    try:
                        try:
                            from db.mongo import ensure_indexes_safely as _fix
                        except ImportError:
                            from db.mongo import ensure_mongo_indexes as _fix
                        _fix()
                        tot, att = _projects_counts_direct()
                    except Exception:
                        # fallback last-resort
                        tot, att = _projects_counts()
                else:
                    # fallback last-resort
                    tot, att = _projects_counts()
            log.warning("INTENT_DB → cantieri (tot=%s, attivi=%s)", int(tot), int(att))
            return jsonify({"answer": f"Ci sono {int(tot)} cantieri in totale, {int(att)} attivi."}), 200

        # Cantieri attivi soli (senza chiedere i totali)
        if re.search(r"\b(quanti|numero|quante)\b.*\b(attiv[ie]|confermat[oi]|in\s+corso)\b.*\b(cantier[ei])\b", m):
            try:
                tot, att = _projects_counts_direct()
            except OperationFailure as e:
                if getattr(e, "code", None) == 85 or "IndexOptionsConflict" in str(e):
                    try:
                        try:
                            from db.mongo import ensure_indexes_safely as _fix
                        except ImportError:
                            from db.mongo import ensure_mongo_indexes as _fix
                        _fix()
                        tot, att = _projects_counts_direct()
                    except Exception:
                        tot, att = _projects_counts()
                else:
                    tot, att = _projects_counts()
            return jsonify({"answer": f"Cantieri attivi: {int(att)} (su {int(tot)} totali)."}), 200

        # Elenca ultimi N cantieri (di default 5) — es: "ultimi 5 cantieri", "ultimi cantieri"
        if re.search(r"\b(ultim[oi]|recent[ei])\b.*\b(cantier[ei])\b", m):
            try:
                N = 5
                mm = re.search(r"\bultim[oi]\s+(\d{1,2})\b", m)
                if mm:
                    N = max(1, min(20, int(mm.group(1))))
                db = get_db()
                # preferisci created_at desc; fallback su _id (ObjectId time) desc
                cur = db["projects"].find({}, {"_id": 0, "id": 1, "name": 1, "status": 1, "city": 1, "created_at": 1})
                docs = list(cur)
                def _key(p):
                    return p.get("created_at") or ""
                try:
                    docs.sort(key=_key, reverse=True)
                except Exception:
                    pass
                items = [{"id": p.get("id"), "name": p.get("name"), "status": p.get("status"), "city": p.get("city")} for p in docs[:N]]
                return jsonify({"answer": f"Ecco gli ultimi {len(items)} cantieri", "items": items}), 200
            except Exception:
                # non bloccare la chat se qualcosa fallisce
                pass
        # ----- /Intent DB ---------------------------------------------------

        # === INTENTI LAVORI E ASSEGNAZIONE (router semantico base) ===
        # Riconosce comandi testuali e richiama le route dei lavori progetto senza duplicare logica.
        db = get_db()
        pid = None
        m_pid = re.search(r"\bP-\d+\b", q, flags=re.I)
        text_pid = m_pid.group(0) if m_pid else None
        if enforced_pid:
            # Chat vincolata a un progetto: ignora/impedisci riferimenti ad altri progetti
            if text_pid and text_pid != enforced_pid:
                return jsonify({"reply": f"Questa chat è vincolata al progetto {enforced_pid}. Usa la chat aziendale per riferirti a {text_pid}."}), 200
            pid = enforced_pid
        else:
            pid = text_pid

        def _infer_work_code(text: str) -> str | None:
            """Trova il codice lavoro dal catalogo usando name/synonyms (in italiano)."""
            t = (text or "").lower()
            docs = list(db["work_catalog"].find({}, {"code": 1, "name": 1, "synonyms": 1}))
            for d in docs:
                nm = (d.get("name") or "").lower()
                if nm and nm in t:
                    return d["code"]
                for syn in (d.get("synonyms") or []):
                    if syn and syn.lower() in t:
                        return d["code"]
            return None

        # Lista lavori progetto
        if re.search(r"\b(mostra|vedi|lista|elenca)\b.*\blavor", q, flags=re.I):
            if not pid:
                return jsonify({"reply": "Dimmi anche l'ID del progetto (es. P-1001)."}), 200
            proj = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
            if not proj:
                return jsonify({"reply": f"Nessun progetto {pid} trovato."}), 404
            works = proj.get("works") or []
            return jsonify({"reply": f"Lavori nel progetto {pid}: {len(works)}", "items": works}), 200

        # Aggiungi lavoro (dal catalogo)
        if re.search(r"\b(aggiungi|inserisci)\b.*\blavor", q, flags=re.I):
            if not pid:
                return jsonify({"reply": "Specifica l'ID del progetto (es. P-1001)."}), 200
            code = _infer_work_code(q)
            qty_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(mq|m2|metri)", q, flags=re.I)
            qty = float(qty_match.group(1).replace(",", ".")) if qty_match else 1.0
            if not code:
                return jsonify({"reply": "Non ho capito il tipo di lavoro. Esempio: 'aggiungi posa pavimento 120 mq al progetto P-1001'."}), 200
            payload = {"code": code, "qty": qty}
            from routes.project_works import add_project_work
            with current_app.test_request_context(json=payload):
                resp = add_project_work(pid)
            return resp

        # Pianifica lavori esistenti
        if re.search(r"\b(pianifica|calcola|stima)\b.*\blavor", q, flags=re.I):
            if not pid:
                return jsonify({"reply": "Dimmi anche l'ID del progetto (es. P-1001)."}), 200
            from routes.project_works import plan_project
            with current_app.test_request_context(json={}):
                resp = plan_project(pid)
            return resp

        # Assegna operai su calendario (in base al piano)
        if re.search(r"\b(assegna|programma)\b.*\boperai", q, flags=re.I):
            if not pid:
                return jsonify({"reply": "Dimmi anche l'ID del progetto (es. P-1001)."}), 200
            from routes.project_works import schedule_auto_assign
            with current_app.test_request_context(json={}):
                resp = schedule_auto_assign(pid)
            return resp

        # Scope di progetto per RAG/ricerche: se enforced, forza il filtro
        where = None
        project_id = data.get("project_id")
        if enforced_pid:
            where = {"project_id": enforced_pid}
        elif project_id is not None:
            try:
                where = {"project_id": int(project_id)}
            except (TypeError, ValueError):
                where = None

        # ---- deps da app.py --------------------------------------------------
        vector_store = getattr(g, "vector_store", None)
        chat_model   = getattr(g, "chat_model", None)
        web_retriever = getattr(g, "web_retriever", None)
        router = current_app.extensions.get("deps", {}).get("router")

        if not vector_store or not chat_model:
            return jsonify({"error": "Componenti non inizializzati (vector_store/chat_model)"}), 500

        # ---- session ---------------------------------------------------------
        sid_base = session.get("sid") or str(uuid.uuid4())
        # Usa il PID imposto dalla route di progetto oppure quello passato nel payload come project_id
        pid_for_sid = enforced_pid or (str(data.get("project_id")) if data.get("project_id") is not None else None)
        if pid_for_sid:
            sid = f"{sid_base}::P:{pid_for_sid}"
        else:
            sid = f"{sid_base}::COMPANY"
        session["sid"] = sid
        log.info(f"[chat] sid={sid} pid={pid_for_sid}")

        # ---- intent routing --------------------------------------------------
        intent_raw = "none"; entities = {}
        try:
            if router is not None:
                routed = router.route(q)
                intent_raw = routed.get("intent", "none")
                entities = routed.get("entities", {}) or {}
            else:
                low = q.lower()
                if any(k in low for k in ("confronta","analizza","estrai","capitolato","computo","pdf","allegato","excel","file")):
                    intent_raw = "documento"
                elif any(k in low for k in ("stima","preventivo","quanto costa","costo","budget","analisi prezzi")):
                    intent_raw = "stima"
                else:
                    intent_raw = "stima"
        except Exception as e:
            log.warning("Router intent fallito: %s", e, exc_info=True)
            intent_raw = "stima"
            entities = {}

        intent = _normalize_intent(intent_raw)

        # ---- estrazione numerica minima -------------------------------------
        try:
            ex = quick_extract(q)
        except Exception:
            ex = {"qty": None, "unit": None, "thickness_mm": None, "dimensions": None}

        if entities.get("qty") is None and ex.get("qty") is not None:
            entities["qty"] = ex["qty"]
        if not entities.get("unit") and ex.get("unit"):
            entities["unit"] = ex["unit"]
        if not entities.get("spessori_mm") and ex.get("thickness_mm"):
            entities["spessori_mm"] = ex["thickness_mm"]
        if not entities.get("dimensioni") and ex.get("dimensions"):
            entities["dimensioni"] = ex["dimensions"]

        # ---- RAG locale con filtro cantiere (a prova di errori) -------------
        local_ctx = []
        try:
            try:
                local_ctx = vector_store.search(q, limit=12, where=where)
            except TypeError:
                # compat per vecchie firme senza 'where'
                local_ctx = vector_store.search(q, limit=12)
        except Exception as _e_vs:
            log.warning("Vector store search fallita: %s", _e_vs)
            local_ctx = []

        # ---- price hints dai documenti --------------------------------------
        price_hints = []
        try:
            for i, chunk in enumerate(local_ctx[:6], start=1):
                txt = (chunk.get("text") or "")
                hits = parse_prices(txt)
                if not hits: 
                    continue
                src = (chunk.get("metadata") or {}).get("source", f"Documento {i}")
                for p in hits[:2]:
                    price_hints.append(f"- {src}: {p['value']} {p['unit']}")
        except Exception:
            price_hints = []

        # ---- web retrieval (opzionale) --------------------------------------
        web_ctx = []
        if bool(current_app.config.get("ENABLE_WEB_RETRIEVAL", False)) and web_retriever and intent in ("STIMA","DOCUMENTO"):
            try:
                if hasattr(web_retriever, "search_and_fetch"):
                    web_ctx = web_retriever.search_and_fetch(q, max_results=5)
                elif hasattr(web_retriever, "invoke"):
                    web_ctx = web_retriever.invoke(q)
                elif hasattr(web_retriever, "run"):
                    web_ctx = web_retriever.run(q)
                elif hasattr(web_retriever, "search"):
                    web_ctx = web_retriever.search(q)
                else:
                    log.warning("Web retriever non ha metodi compatibili (search_and_fetch/invoke/run/search)")
                    web_ctx = []
            except Exception as e:
                log.warning("Web retriever fallito: %s", e)

        # ---- stima automatica (DB → fallback baseline) ----------------------
        auto_estimate = None
        if intent == "STIMA" and entities.get("qty") and entities.get("unit"):
            try:
                from routes.estimate import estimate_from_entities as _by_db
                auto_estimate = _by_db(entities) or pick_and_estimate(entities)
            except Exception as e:
                log.info("estimate_from_entities non disponibile/errore: %s", e)
                try:
                    auto_estimate = pick_and_estimate(entities)
                except Exception:
                    auto_estimate = None

        # ---- domanda arricchita per il modello ------------------------------
        parts = []
        if entities.get("qty") and entities.get("unit"):
            parts.append(f"[PARAMETRI RICONOSCIUTI] qty={entities['qty']} {entities['unit']}")
        if entities.get("spessori_mm"):
            parts.append(f"spessore={entities['spessori_mm']} mm")
        if entities.get("dimensioni"):
            parts.append(f"formato={', '.join(map(str, entities['dimensioni']))}")
        if project_id is not None:
            parts.append(f"project_id={project_id}")
        meta_hint = ("\n\n" + "; ".join(parts)) if parts else ""

        hints_block = ("\n\n[DATI ESTRATTI DAI DOCUMENTI]\n" + "\n".join(price_hints)) if price_hints else ""
        estimate_block = _format_estimate_text(auto_estimate) if auto_estimate else ""
        augmented_question = q + meta_hint + hints_block + estimate_block

        # ---- chiamata al modello --------------------------------------------
        res = chat_model.answer_with_contexts(
            sid,
            augmented_question,
            local_ctx,
            web_ctx,
            calc_json=auto_estimate
        )

        # Garantisci blocco calc_json per il frontend se abbiamo una stima
        try:
            res = _ensure_calc_block(res, auto_estimate, q)
        except Exception:
            pass

        # ---- payload UI ------------------------------------------------------
        res["intent"] = intent
        res["entities"] = entities
        res["price_hints"] = price_hints
        res["auto_estimate"] = auto_estimate

        # retro-compat: lista “sources” semplice
        local_sources = [
            {
                "source": (c.get("metadata") or {}).get("source", "Documento"),
                "text": (c.get("text") or (c.get("payload", {}) or {}).get("text", ""))[:300]
            }
            for c in (local_ctx or [])
        ]
        web_sources = [
            {
                "source": (c.get("title") or c.get("url") or "Fonte web"),
                "text": (c.get("text") or c.get("snippet") or "")[:300]
            }
            for c in (web_ctx or [])
        ]
        res["sources"] = local_sources + web_sources

        # --- analytics: salva record sintetico con latency e intent ---
        try:
            latency_ms = int((time.perf_counter() - _t0) * 1000)
            db = get_db()
            db["chat_analytics"].insert_one({
                "session_id": session.get("sid"),
                "question": q,
                "answer": (res.get("reply") or res.get("answer") or "")[:500],
                "tokens_in": len(q.split()),
                "tokens_out": len((res.get("reply") or res.get("answer") or "").split()),
                "tools_used": [],
                "intent": res.get("intent"),
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow(),
                "site_id": (enforced_pid or data.get("project_id") or data.get("site_id")),
                "had_error": False,
            })
            res["latency_ms"] = latency_ms
        except Exception:
            pass

        return jsonify(res), 200

    except Exception as e:
        log.exception("Errore /api/chat")
        return jsonify({"error": str(e)}), 500
@chat_bp.post("/chat/project/<pid>")
def chat_route_project(pid):
    """Chat vincolata a un progetto: tutte le operazioni e il contesto sono limitati a <pid>."""
    payload = request.get_json(force=True) or {}
    # Passa il messaggio originale e impone il progetto con un campo interno
    payload["__enforced_pid"] = pid
    if not payload.get("message") and payload.get("question"):
        payload["message"] = payload["question"]
    with current_app.test_request_context(json=payload):
        return chat_route()