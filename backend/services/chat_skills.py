# services/chat_skills.py
import re
from datetime import datetime
from typing import Dict, Any, Optional
from pymongo.errors import OperationFailure

from mongoengine.queryset.visitor import Q
from models_mongo.worker import WorkerDoc
from models_mongo.project import ProjectDoc
from models_mongo.material import MaterialDoc

# Optional imports
try:
    from utils.capacity import check_capacity
except ImportError:
    check_capacity = None

# --- Safe count helper for Mongo index conflicts ---
def safe_count(queryset_callable):
    """Esegue una count() o simili e autoripara eventuali conflitti di indici Mongo."""
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
        raise

class ChatSkills:
    """Collezione completa di 'skills' deterministiche."""

    # --- REGEX PATTERNS ---
    HEADCOUNT_RE = re.compile(
        r"\b(quant\w*|quas\w*|numero|totale|tot)\b.*\b(impiegat\w*|opera\w*|dipendent\w*|personale|staff|lavorator\w*)\b",
        re.IGNORECASE
    )
    
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

    UNIT_MAP = {
        "mq":"m2", "m²":"m2", "mc":"m3", "m³":"m3",
        "l":"lt", "litri":"lt", "pezzi":"pz", "pezzo":"pz",
        "cart":"pz", "bomb":"pz"
    }

    # Gruppi sinonimi materiali
    MATERIAL_SYNONYM_GROUPS = [
        {"cemento", "cem", "portland"},
        {"calcestruzzo", "cls"},
        {"malta", "premiscelato", "m5"},
        {"intonaco", "civile"},
        {"cartongesso", "gkb", "lastra"},
        {"rete", "elettrosaldata"},
        {"acciaio", "barra", "tondino", "b450"},
        {"pittura", "lavabile", "smalto", "idropittura"},
        {"stucco", "fughe"},
        {"guaina", "bituminosa", "ardesiata"},
        {"eps", "polistirene", "isolante"},
        {"piastrella", "gres"},
        {"colla", "c2te", "adesivo"},
        {"tubo", "corrugato"},
        {"cavo", "fg16or"},
        {"scatola", "503"},
        {"interruttore"},
        {"presa", "schuko"},
    ]

    _SYNONYM_TO_ROOT = {}
    for group in MATERIAL_SYNONYM_GROUPS:
        root = sorted(group, key=len)[0]
        for s in group:
            _SYNONYM_TO_ROOT[s] = root

    # --- HELPER UTILS ---
    @staticmethod
    def _extract_region_city(text: str):
        t = text.lower()
        reg, city = None, None
        mreg = re.search(r"\bin\s+([a-zàèéìòù\-\s]{3,})", t)
        if mreg:
            reg = mreg.group(1).strip().title()
        mcity = re.search(r"\ba\s+([a-zàèéìòù\-\s]{2,})", t)
        if mcity:
            city = mcity.group(1).strip().title()
        return reg, city

    @staticmethod
    def _role_regex_from_text(tl: str) -> tuple:
        """Ricava pattern regex per il ruolo dal testo utente."""
        tl = (tl or "").lower()

        # Frasi complete
        phrases = {
            "capo cantiere": "capi cantiere",
            "capi cantiere": "capi cantiere",
            "responsabile cantiere": "responsabili di cantiere",
            "capo muratore": "capi muratore",
            "capo squadra": "capi squadra",
        }
        for p, plural in phrases.items():
            if p in tl:
                if "cantiere" in p and ("capo" in p or "capi" in p):
                    return r"cap\w*\s*cantiere", "capi cantiere"
                return p, plural

        # Variante robusta
        if "cantiere" in tl and ("capo" in tl or "capi" in tl):
            return r"cap\w*\s*cantiere", "capi cantiere"

        # Fallback: radici standard
        for root, plural in ChatSkills.ROLE_ROOTS.items():
            if root in tl:
                return root, plural

        return None, None

    @staticmethod
    def _normalize_material_tokens(text: str) -> list:
        """Converte il testo in gruppi di sinonimi."""
        if not text:
            return []
        cleaned = re.sub(r"(?i)\b(prezzo|quanto|costa|al|allo|alla|per|unit(a|à)|sku[:\s]*[A-Z0-9\-]+)\b", " ", text)
        raw_tokens = re.findall(r"[A-Za-z]+|\d+(?:[.,]\d+)?[A-Za-z]?", cleaned.lower())
        raw_tokens = [t.strip().replace(",", ".") for t in raw_tokens if len(t.strip()) >= 2]

        groups = []
        seen = set()
        for tok in raw_tokens:
            variants = {tok}
            m = re.match(r"^(\d+(?:\.\d+)?)([a-z])$", tok)
            if m:
                variants.add(f"{m.group(1)} {m.group(2)}")
            root = ChatSkills._SYNONYM_TO_ROOT.get(tok)
            if root:
                syns = {v for v, r in ChatSkills._SYNONYM_TO_ROOT.items() if r == root}
                variants |= syns
            norm = sorted({" ".join(v.split()) for v in variants})
            key = tuple(norm)
            if key in seen:
                continue
            seen.add(key)
            groups.append(norm)
        return groups

    # --- WORKERS SKILLS ---

    @staticmethod
    def headcount(text: str):
        if not ChatSkills.HEADCOUNT_RE.search(text or ""):
            return None
        tot = safe_count(lambda: WorkerDoc.objects.count())
        disp = safe_count(lambda: WorkerDoc.objects(available=True).count())
        return {"INTENT_DB":"HEADCOUNT", "answer": f"Totale personale: {tot} (disponibili: {disp})."}

    @staticmethod
    def role_lookup(text: str):
        m = re.search(r"che\s+lavoro\s+fa\s+(.+?)\??$", (text or "").strip(), re.IGNORECASE)
        if not m:
            return None
        name = m.group(1).strip()
        w = WorkerDoc.objects(name__iexact=name).first() or WorkerDoc.objects(name__icontains=name).first()
        if not w:
            return {"INTENT_DB":"ROLE_LOOKUP", "answer": f"Non trovo {name} nel personale."}
        return {"INTENT_DB":"ROLE_LOOKUP", "answer": f"{w.name} è {w.role}."}

    @staticmethod
    def list_by_role_intent(text: str):
        m = ChatSkills.ROLE_LIST_RE.search(text or "")
        if not m:
            return None
        word = m.group(2).lower()
        root = next((r for r in ChatSkills.ROLE_ROOTS if r in word), None)
        if not root:
            return None
        qs = WorkerDoc.objects(role__icontains=root)
        names = sorted({w.name for w in qs.only("name").limit(200)})
        if not names:
            return {"INTENT_DB": "ROLE_LIST", "answer": f"Nessun {ChatSkills.ROLE_ROOTS[root]} trovato."}
        label = ChatSkills.ROLE_ROOTS[root]
        first = names[:20]
        return {"INTENT_DB": "ROLE_LIST", "answer": f"Ecco {len(first)} {label}: " + ", ".join(first)}

    @staticmethod
    def available_filtered(text: str):
        """Quanti <ruolo> disponibili [in <regione>] [a <città>]?"""
        tl = (text or "").lower()
        if not ("disponibil" in tl or "liber" in tl):
            return None
        
        # Estrai ruolo
        root = next((r for r in ChatSkills.ROLE_ROOTS if r in tl), None)
        
        # Estrai Geo
        reg, city = ChatSkills._extract_region_city(tl)
        
        qs = WorkerDoc.objects(available=True)
        if root:
            qs = qs.filter(role__icontains=root)
        if city:
            qs = qs.filter(home_city__icontains=city)
            
        count = safe_count(lambda: qs.count())
        
        # Costruzione risposta
        pieces = [f"Disponibili: {count}"]
        if root:
            pieces.append(f"ruolo ~ {root}")
        if reg:
            pieces.append(f"regione: {reg}")
        if city:
            pieces.append(f"città: {city}")
        
        return {"INTENT_DB":"WORKERS_FREE_FILTERED", "answer": " • ".join(pieces)}

    @staticmethod
    def set_worker_region_city(text: str):
        """Imposta regione/città per un worker."""
        tl = text.lower()
        if not any(k in tl for k in ("imposta", "set ", "assegna")):
            return None
        if not ("regione" in tl or "citt" in tl):
            return None
        
        # Estrai ID/Nome
        m_id = re.search(r"\b(w-\d{3,6})\b", tl, re.IGNORECASE)
        ident = m_id.group(1) if m_id else None
        if not ident:
            m_name = re.search(r"\bper\s+([a-zàèéìòù]+\s+[a-zàèéìòù]+)\b", tl)
            ident = m_name.group(1).title() if m_name else None
        
        if not ident:
            return None
        
        w = WorkerDoc.objects(id__iexact=ident).first() if m_id else WorkerDoc.objects(name__icontains=ident).first()
        if not w:
            return {"INTENT_DB":"WORKER_SET_GEO", "answer": "Lavoratore non trovato."}
        
        # Estrai solo città
        city = None
        mcity = re.search(r"citt[aà]\s+([a-zàèéìòù\-\s]{2,})", tl)
        if mcity:
            city = mcity.group(1).strip().title()
        
        if city:
            w.home_city = city
            w.save()
            return {"INTENT_DB":"WORKER_SET_GEO", "answer": f"Aggiornato {w.name}: Città={w.home_city}."}
        
        return None

    @staticmethod
    def toggle_worker_availability(text: str):
        if not any(k in text.lower() for k in ("impegna ", "occupa ", "libera ")):
            return None
        
        m_id = re.search(r"(w-\d{3,6})", text, re.IGNORECASE)
        ident = m_id.group(1) if m_id else None
        if not ident:
            m_name = re.search(r"(impegna|occupa|libera)\s+([a-zàèéìòù]+\s+[a-zàèéìòù]+)", text, re.IGNORECASE)
            ident = m_name.group(2).title() if m_name else None
            
        w = WorkerDoc.objects(id__iexact=ident).first() if m_id else (
            WorkerDoc.objects(name__icontains=ident).first() if ident else None
        )
        if not w:
            return {"INTENT_DB":"WORKER_TOGGLE", "answer":"Non trovo il lavoratore indicato."}
        
        make_busy = any(k in text.lower() for k in ("impegna", "occupa"))
        target_avail = not make_busy
        if w.available != target_avail:
            w.available = target_avail
            w.save()
            action = "liberato" if target_avail else "impegnato"
            return {"INTENT_DB":"WORKER_TOGGLE", "answer": f"{w.name} è stato {action}."}
        return {"INTENT_DB":"WORKER_TOGGLE", "answer": f"{w.name} è già nello stato richiesto."}

    @staticmethod
    def capacity_check(text: str):
        """Capienza <ruolo> dal... al..."""
        if not check_capacity:
            return None
        tl = text.lower()
        if not ("capienz" in tl or ("disponibil" in tl and "dal" in tl and "al" in tl)):
            return None
        
        m_dates = re.search(r"dal\s+([0-9/\-]+)\s+al\s+([0-9/\-]+)", tl)
        if not m_dates:
            return None
        
        # Estrai ruolo
        root = next((r for r in ChatSkills.ROLE_ROOTS if r in tl), "operaio")
        
        try:
            return {"INTENT_DB":"CAPACITY", "answer": f"Controllo capienza per {root} dal {m_dates.group(1)} al {m_dates.group(2)}: OK (Simulato)"}
        except Exception:
            return None

    # --- PROJECTS SKILLS ---

    @staticmethod
    def project_counts(text: str):
        if re.search(r"\b(quanti|numero)\b.*\b(cantier[ei])\b", text.lower()):
            tot = safe_count(lambda: ProjectDoc.objects.count())
            att = safe_count(lambda: ProjectDoc.objects(status__in=["Confermato", "In corso", "Attivo", "Active"]).count())
            return {"INTENT_DB": "PROJECT_COUNTS", "answer": f"Ci sono {tot} cantieri totali, di cui {att} attivi."}
        return None

    @staticmethod
    def recent_projects(text: str):
        """Ultimi N cantieri."""
        m = re.search(r"\b(ultim[oi]|recent[ei])\b.*\b(cantier[ei])\b", text.lower())
        if not m:
            return None
        
        limit = 5
        mnum = re.search(r"\bultim[oi]\s+(\d{1,2})\b", text.lower())
        if mnum:
            limit = int(mnum.group(1))
        
        projs = ProjectDoc.objects.order_by("-id").limit(limit)
        items = [f"{p.name} ({p.status})" for p in projs]
        return {"INTENT_DB": "RECENT_PROJECTS", "answer": f"Ultimi {len(items)} cantieri: " + ", ".join(items)}

    # --- MATERIALS SKILLS ---

    @staticmethod
    def _material_answer(mdoc: MaterialDoc) -> dict:
        price = getattr(mdoc, 'unit_price_eur_2025', None) or 0.0
        sku = getattr(mdoc, 'sku', 'N/A')
        unit = getattr(mdoc, 'unit', 'pz')
        
        # Campi opzionali - usa getattr con default
        stock = int(getattr(mdoc, 'stock_qty', 0) or 0)
        lead_time = int(getattr(mdoc, 'lead_time_days', 0) or 0)
        vat = int(getattr(mdoc, 'vat_rate', 0) or 0)
        
        return {
            "INTENT_DB": "MATERIAL_PRICE",
            "answer": (
                f"{mdoc.name}: {price:.2f} €/{unit} (SKU {sku}). "
                f"Stock: {stock}, Lead time: {lead_time} gg, IVA: {vat}%."
            ),
        }

    @staticmethod
    def material_price(text: str):
        if not text:
            return None

        # 1) unità (sinonimi)
        unit = None
        for u in ["kg","m2","m3","pz","lt","m","mq","m²","mc","m³","l","litri","pezzi","pezzo","cart","bomb"]:
            if re.search(rf"\b{re.escape(u)}\b", text, re.IGNORECASE):
                unit = ChatSkills.UNIT_MAP.get(u, u)
                break

        # 2) SKU realistico
        sku_match = re.search(r"\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]*)\b", text.upper())
        if sku_match:
            mdoc = MaterialDoc.objects(sku=sku_match.group(1)).first()
            if mdoc:
                return ChatSkills._material_answer(mdoc)

        # 3) Token + sinonimi
        groups = ChatSkills._normalize_material_tokens(text)
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
            qs2 = MaterialDoc.objects
            if q is not None:
                qs2 = qs2.filter(q)
            mdoc = qs2.order_by("name").first()

        return ChatSkills._material_answer(mdoc) if mdoc else None

    # --- ACTIONS SKILLS (PROJECT-SCOPED) ---

    @staticmethod
    def add_work_item(text: str, project_id: str):
        if not project_id or not re.search(r"\b(aggiungi|inserisci)\b.*\blavor", text, re.IGNORECASE):
            return None
        
        qty_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(mq|m2|metri|pz)", text, re.IGNORECASE)
        qty = float(qty_match.group(1).replace(",", ".")) if qty_match else 1.0
        
        return {
            "INTENT_DB": "ACTION_ADD_WORK",
            "action_payload": {"project_id": project_id, "text": text, "qty": qty},
            "answer": f"Sto aggiungendo una lavorazione da {qty} unità..."
        }

    @staticmethod
    def plan_works(text: str, project_id: str):
        if not project_id:
            return None
        if re.search(r"\b(pianifica|calcola|stima)\b.*\blavor", text, re.IGNORECASE):
            try:
                from services.work_service import WorkService
                res = WorkService.plan_project(project_id)
                msg = f"Pianificati {len(res.get('items',[]))} lavori." if res.get("ok") else f"Errore: {res.get('error')}"
                return {"INTENT_DB": "ACTION_PLAN_PROJECT", "answer": msg}
            except Exception as e:
                return {"INTENT_DB": "ACTION_PLAN_PROJECT", "answer": f"Errore: {str(e)}"}
        return None

    @staticmethod
    def auto_assign(text: str, project_id: str):
        if not project_id:
            return None
        if re.search(r"\b(assegna|programma)\b.*\boperai", text, re.IGNORECASE):
            try:
                from services.work_service import WorkService
                res = WorkService.auto_assign(project_id)
                msg = f"Assegnati {res.get('assigned',0)} operai." if res.get("ok") else f"Errore: {res.get('error')}"
                return {"INTENT_DB": "ACTION_AUTO_ASSIGN", "answer": msg}
            except Exception as e:
                return {"INTENT_DB": "ACTION_AUTO_ASSIGN", "answer": f"Errore: {str(e)}"}
        return None