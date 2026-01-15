# services/chat_skills.py
import re
import json
from datetime import datetime
from typing import Dict, Any, Optional
from pymongo.errors import OperationFailure

from mongoengine.queryset.visitor import Q
from models_mongo.worker import WorkerDoc
from models_mongo.project import ProjectDoc
from models_mongo.material import MaterialDoc
from models_mongo.computo import ComputoDoc

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
    def list_project_workers(text: str, project_id: str):
        """Elenca operai assegnati nel cantiere (da ProjectDoc.works[*].workers).

        Trigger: domande del tipo "quali/chi sono gli operai nel cantiere", "chi sta lavorando".
        """
        if not project_id:
            return None

        tl = (text or "").lower()

        # evita conflitto con azioni ("assegna operai")
        if re.search(r"\b(assegna|programma)\b.*\boperai\b", tl):
            return None

        wants_people = any(k in tl for k in ("operai", "dipendenti", "personale", "chi lavora", "lavorano", "workers"))
        wants_list = any(k in tl for k in ("quali", "chi", "elenco", "lista", "mostra", "dimm"))
        if not (wants_people and wants_list):
            return None

        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            return {"INTENT_DB": "PROJECT_WORKERS", "answer": "Cantiere non trovato."}

        works = list(getattr(p, "works", None) or [])
        worker_ids = []
        for w in works:
            for wid in (getattr(w, "workers", None) or []):
                if wid and str(wid) not in worker_ids:
                    worker_ids.append(str(wid))

        # foreman (se presente) può essere salvato in meta_extra
        meta = dict(getattr(p, "meta_extra", None) or {})
        foreman_id = meta.get("foreman_id") or meta.get("capo_cantiere_id")
        if foreman_id and str(foreman_id) not in worker_ids:
            worker_ids.insert(0, str(foreman_id))

        if not worker_ids:
            return {
                "INTENT_DB": "PROJECT_WORKERS_EMPTY",
                "answer": "Non risultano operai assegnati a questo cantiere. Prima pianifica i lavori e poi usa ‘Assegna operai’."
            }

        # lookup dettagli workers
        try:
            from bson import ObjectId
            oids = []
            for x in worker_ids:
                try:
                    oids.append(ObjectId(str(x)))
                except Exception:
                    pass
            ws = WorkerDoc.objects(id__in=oids) if oids else []
        except Exception:
            ws = []

        if not ws:
            return {
                "INTENT_DB": "PROJECT_WORKERS",
                "answer": f"Nel cantiere risultano {len(worker_ids)} assegnazioni, ma non riesco a leggere i dettagli anagrafici dal DB (ids: {', '.join(worker_ids[:6])})."
            }

        lines = []
        for wkr in ws:
            role = (wkr.role or "").strip() or "operaio"
            name = (wkr.name or "").strip() or str(wkr.id)
            tag = " (capo cantiere)" if str(wkr.id) == str(foreman_id) else ""
            lines.append(f"- {name} — {role}{tag}")

        ans = f"Operai assegnati nel cantiere {getattr(p, 'name', project_id)} ({len(ws)}):\n" + "\n".join(lines)
        return {"INTENT_DB": "PROJECT_WORKERS", "answer": ans}

    @staticmethod
    def work_deadline(text: str, project_id: str):
        """Risponde a domande su scadenza/data fine di una lavorazione specifica."""
        if not project_id:
            return None

        tl = (text or "").lower()
        if not ("scaden" in tl or "data fine" in tl or "quando fin" in tl or "deadline" in tl or "entro quando" in tl):
            return None

        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            return {"INTENT_DB": "WORK_DEADLINE", "answer": "Cantiere non trovato."}

        works = list(getattr(p, "works", None) or [])
        if not works:
            return {"INTENT_DB": "WORK_DEADLINE", "answer": "Non trovo lavorazioni pianificate per questo cantiere."}

        # Estrai possibile nome lavoro: tra virgolette oppure dopo la parola "lavoro"
        target = None
        m = re.search(r"[\"\']([^\"\']{3,80})[\"\']", text)
        if m:
            target = m.group(1).strip()
        if not target:
            m2 = re.search(r"\blavoro\b\s+(.{3,80})", text, re.IGNORECASE)
            if m2:
                target = re.split(r"[\?\!\.,;]", m2.group(1))[0].strip()

        # Se non ho un target esplicito, usa i token della domanda
        stop = {"quando", "finisce", "finira", "finirà", "scadenza", "data", "fine", "lavoro", "lavorazione", "del", "della", "dei", "delle", "nel", "in", "a", "di", "che", "il", "la", "un", "una", "questo", "questa"}
        tokens = [t for t in re.findall(r"[a-zàèéìòù0-9]{3,}", tl) if t not in stop]

        def score(wname: str) -> int:
            wn = (wname or "").lower()
            s = 0
            if target:
                # match diretto substring
                if target.lower() in wn:
                    s += 5
                # token overlap del target
                for t in re.findall(r"[a-zàèéìòù0-9]{3,}", target.lower()):
                    if t in wn:
                        s += 2
            for t in tokens:
                if t in wn:
                    s += 1
            return s

        best = None
        best_s = 0
        for w in works:
            name = getattr(w, "work_name", None) or getattr(w, "name", None) or ""
            s = score(name)
            if s > best_s:
                best_s = s
                best = w

        if not best or best_s <= 0:
            return {
                "INTENT_DB": "WORK_DEADLINE",
                "answer": "Quale lavorazione intendi? Dimmi il nome esatto (o scrivilo tra virgolette)."
            }

        name = getattr(best, "work_name", None) or "Lavorazione"
        status = getattr(best, "status", None) or "planned"
        ed = getattr(best, "end_date_planned", None) or getattr(best, "end_date", None)
        sd = getattr(best, "start_date_planned", None) or getattr(best, "start_date", None)

        def _fmt(d):
            try:
                return d.strftime("%d/%m/%Y")
            except Exception:
                return str(d) if d else "N/D"

        ans = f"La lavorazione ‘{name}’ è pianificata { _fmt(sd) } → { _fmt(ed) } (stato: {status})."
        return {"INTENT_DB": "WORK_DEADLINE", "answer": ans}

    @staticmethod
    def list_project_works(text: str, project_id: str):
        """Elenca la sequenza lavori del cantiere direttamente dal DB (ProjectDoc.works).

        Serve quando non esiste un PDF indicizzato: la chat deve comunque poter rispondere.
        """
        if not project_id:
            return None

        tl = (text or "").lower()
        # Trigger: richieste di elenco lavori / lavorazioni / sequenza
        if not any(k in tl for k in ("lavori", "lavorazioni", "sequenza")):
            return None
        if not any(k in tl for k in ("quali", "lista", "elenco", "mostra", "cosa", "da svolgere", "da fare")):
            return None

        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            return {"INTENT_DB": "PROJECT_WORKS_LIST", "answer": "Cantiere non trovato."}

        works = list(getattr(p, "works", None) or [])
        if not works:
            return {
                "INTENT_DB": "PROJECT_WORKS_EMPTY",
                "answer": "Per questo cantiere non c’è ancora una sequenza lavori. Prima genera/associa un computo e poi usa ‘Sequenza Lavori’."
            }

        lines = []
        for w in works[:25]:
            # Alcuni campi possono mancare a seconda dello schema/seed
            name = getattr(w, "work_name", None) or getattr(w, "name", None) or "Lavorazione"
            status = getattr(w, "status", None) or "planned"
            sd = getattr(w, "start_date_planned", None)
            ed = getattr(w, "end_date_planned", None)
            sd_s = sd.strftime("%d/%m/%Y") if sd else "N/D"
            ed_s = ed.strftime("%d/%m/%Y") if ed else "N/D"
            nw = getattr(w, "number_of_workers", None)
            nw_s = str(nw) if nw is not None else "N/D"
            lines.append(f"- {name} ({status}, {sd_s} → {ed_s}, operai: {nw_s})")

        ans = f"Nel cantiere {getattr(p, 'name', project_id)} risultano {len(works)} lavorazioni:\n" + "\n".join(lines)
        if len(works) > 25:
            ans += f"\n… e altre {len(works) - 25}."

        return {"INTENT_DB": "PROJECT_WORKS_LIST", "answer": ans}

    @staticmethod
    def latest_computo_summary(text: str, project_id: str):
        """Riassume l'ultimo computo associato al cantiere (ComputoDoc) dal DB.

        Utile quando il computo non è un PDF ma è stato generato e salvato in Mongo.
        """
        if not project_id:
            return None

        tl = (text or "").lower()
        if "computo" not in tl:
            return None

        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            return {"INTENT_DB": "COMPUTO_NONE", "answer": "Cantiere non trovato."}

        comp_ids = list(getattr(p, "metric_computation_id", None) or [])
        if not comp_ids:
            return {"INTENT_DB": "COMPUTO_NONE", "answer": "Non trovo un computo associato a questo cantiere."}

        cid = comp_ids[-1]
        c = ComputoDoc.objects(id=cid).first()
        if not c:
            return {"INTENT_DB": "COMPUTO_NONE", "answer": "Ho un riferimento al computo, ma il documento non è presente nel DB."}

        boq = list(getattr(c, "bill_of_quantities", None) or [])
        comp_code = getattr(c, "computo_code", None) or str(cid)
        grand_total = getattr(c, "grand_total", None)

        header = f"Ho trovato il computo {comp_code}."
        if isinstance(grand_total, (int, float)):
            header = f"Ho trovato il computo {comp_code} (totale: {grand_total:.2f} €)."

        if not boq:
            return {"INTENT_DB": "COMPUTO_SUMMARY", "answer": header + "\nNon trovo voci dettagliate nel computo."}

        # Normalizza numeri se arrivano come stringhe
        def _to_float(x):
            if isinstance(x, (int, float)):
                return float(x)
            if isinstance(x, str):
                xs = x.strip().replace("€", "").replace(" ", "")
                # gestisce "1.234,56" e "1234,56"
                if xs.count(",") == 1 and xs.count(".") >= 1:
                    xs = xs.replace(".", "").replace(",", ".")
                else:
                    xs = xs.replace(",", ".")
                try:
                    return float(xs)
                except Exception:
                    return None
            return None

        lines = []

        # Caso 1: computo per categorie (category/items)
        max_categories = 6
        is_categorized = bool(boq) and isinstance(boq[0], dict) and isinstance(boq[0].get("items"), list)

        if is_categorized:
            for cat in boq[:max_categories]:
                if not isinstance(cat, dict):
                    continue

                cat_name = cat.get("category") or cat.get("categoria") or "Categoria"
                cat_total = _to_float(cat.get("category_total") or cat.get("totale_categoria") or cat.get("total"))

                cat_line = f"- {cat_name}"
                if cat_total is not None:
                    cat_line += f" (totale: {cat_total:.2f} €)"
                # Riga vuota tra categorie per migliorare leggibilità (renderizzata con pre-wrap in UI)
                if lines:
                    lines.append("")
                lines.append(cat_line)

                items = cat.get("items") or []
                for item in items[:2]:
                    if not isinstance(item, dict):
                        continue

                    code = item.get("code") or item.get("codice") or item.get("reference") or item.get("ref")
                    descr = (
                        item.get("description")
                        or item.get("descrizione")
                        or item.get("voce")
                        or item.get("lavorazione")
                        or item.get("nome")
                        or item.get("titolo")
                        or item.get("label")
                    )

                    qty = item.get("qty") or item.get("quantita") or item.get("quantità") or item.get("qta")
                    unit = item.get("unit") or item.get("um") or item.get("unita") or item.get("unità")
                    tot = _to_float(item.get("total") or item.get("totale") or item.get("importo") or item.get("amount"))

                    if not descr:
                        try:
                            descr = json.dumps(item, ensure_ascii=False)[:120]
                        except Exception:
                            descr = "Voce"

                    sub = "  • "
                    if code:
                        sub += f"{code} - "
                    sub += f"{descr}"

                    if qty is not None and unit:
                        sub += f" ({qty} {unit})"
                    if tot is not None:
                        sub += f" → {tot:.2f} €"

                    lines.append(sub)

            if len(boq) > max_categories:
                lines.append(f"... e altre {len(boq) - max_categories} categorie.")

        # Caso 2: computo piatto (lista di voci)
        else:
            for it in boq[:12]:
                if not isinstance(it, dict):
                    continue

                descr = (
                    it.get("descrizione")
                    or it.get("description")
                    or it.get("voce")
                    or it.get("lavorazione")
                    or it.get("nome")
                    or it.get("titolo")
                    or it.get("articolo")
                    or it.get("testo")
                    or it.get("label")
                )

                qty = it.get("quantita") or it.get("quantità") or it.get("qty") or it.get("qta")
                unit = it.get("um") or it.get("unit") or it.get("unita") or it.get("unità")
                tot = _to_float(it.get("totale") or it.get("total") or it.get("importo") or it.get("amount"))

                if not descr:
                    try:
                        descr = json.dumps(it, ensure_ascii=False)[:120]
                    except Exception:
                        descr = "Voce"

                line = f"- {descr}"
                if qty is not None and unit:
                    line += f" ({qty} {unit})"
                if tot is not None:
                    line += f" → {tot:.2f} €"
                lines.append(line)

        ans = header + "\nPrime voci:\n" + "\n".join(lines)
        if len(boq) > 12:
            ans += f"\n… e altre {len(boq) - 12} voci."

        return {"INTENT_DB": "COMPUTO_SUMMARY", "answer": ans}


    @staticmethod
    def computo_category_items(text: str, project_id: str):
        """Mostra tutte (o molte) voci di una specifica categoria del computo.

        Esempi trigger:
        - "mostrami tutte le voci della categoria impianto elettrico"
        - "elenca le voci categoria demolizioni"
        """
        if not project_id:
            return None

        tl = (text or "").lower()
        if "computo" not in tl and "categoria" not in tl:
            return None

        # Deve essere una richiesta di elenco voci
        if not any(k in tl for k in ("mostra", "elenca", "lista", "tutte", "voci", "lavorazioni")):
            return None
        if "categoria" not in tl:
            return None

        # Estrai il nome categoria dal testo
        m = re.search(r"categoria\s+([^\n\r]+)$", tl)
        if not m:
            # fallback: "della categoria X"
            m = re.search(r"della\s+categoria\s+([^\n\r]+)$", tl)
        if not m:
            m = re.search(r"categoria\s+([a-zàèéìòù0-9\-\s]{3,})", tl)
        if not m:
            return None

        cat_query = (m.group(1) or "").strip(" .,:;!?\t\n\r")
        if len(cat_query) < 3:
            return None

        # Limite: "top 10" / "10 voci" / default
        limit = 25
        mnum = re.search(r"\b(\d{1,2})\b", tl)
        if mnum:
            try:
                limit = max(1, min(60, int(mnum.group(1))))
            except Exception:
                pass
        if "tutte" in tl:
            limit = max(limit, 50)

        # Recupera ultimo computo
        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            return {"INTENT_DB": "COMPUTO_CAT_ITEMS", "answer": "Cantiere non trovato."}

        comp_ids = list(getattr(p, "metric_computation_id", None) or [])
        if not comp_ids:
            return {"INTENT_DB": "COMPUTO_CAT_ITEMS", "answer": "Non trovo un computo associato a questo cantiere."}

        cid = comp_ids[-1]
        c = ComputoDoc.objects(id=cid).first()
        if not c:
            return {"INTENT_DB": "COMPUTO_CAT_ITEMS", "answer": "Ho un riferimento al computo, ma il documento non è presente nel DB."}

        boq = list(getattr(c, "bill_of_quantities", None) or [])
        if not boq:
            return {"INTENT_DB": "COMPUTO_CAT_ITEMS", "answer": "Il computo non contiene voci."}

        # Cerca categoria (match per contenimento, robusto)
        def _norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip().lower())

        cat_query_n = _norm(cat_query)
        found = None
        for cat in boq:
            if not isinstance(cat, dict):
                continue
            name = cat.get("category") or cat.get("categoria")
            if not name:
                continue
            if cat_query_n in _norm(name):
                found = cat
                break

        if not found:
            # fallback: match su parole principali (AND)
            q_words = [w for w in re.split(r"\W+", cat_query_n) if len(w) >= 3]
            for cat in boq:
                if not isinstance(cat, dict):
                    continue
                name = _norm(cat.get("category") or cat.get("categoria") or "")
                if not name:
                    continue
                if q_words and all(w in name for w in q_words):
                    found = cat
                    break

        if not found:
            # lista categorie disponibili
            cats = []
            for cat in boq:
                if isinstance(cat, dict):
                    nm = cat.get("category") or cat.get("categoria")
                    if nm:
                        cats.append(nm)
            cats = cats[:12]
            return {
                "INTENT_DB": "COMPUTO_CAT_ITEMS",
                "answer": "Non trovo quella categoria nel computo. Categorie disponibili: " + ", ".join(cats)
            }

        cat_name = found.get("category") or found.get("categoria") or "Categoria"
        items = list(found.get("items") or [])
        if not items:
            return {"INTENT_DB": "COMPUTO_CAT_ITEMS", "answer": f"La categoria '{cat_name}' non contiene voci."}

        # helper numerico
        def _to_float(x):
            if isinstance(x, (int, float)):
                return float(x)
            if isinstance(x, str):
                xs = x.strip().replace("€", "").replace(" ", "")
                if xs.count(",") == 1 and xs.count(".") >= 1:
                    xs = xs.replace(".", "").replace(",", ".")
                else:
                    xs = xs.replace(",", ".")
                try:
                    return float(xs)
                except Exception:
                    return None
            return None

        lines = [f"Categoria: {cat_name} (voci: {len(items)})"]
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            code = item.get("code") or item.get("codice") or item.get("reference") or item.get("ref")
            descr = (
                item.get("description")
                or item.get("descrizione")
                or item.get("voce")
                or item.get("lavorazione")
                or item.get("nome")
                or item.get("titolo")
                or item.get("label")
            )
            # Totale riga: prova campi espliciti, altrimenti qty * prezzo unitario
            tot = _to_float(
                item.get("total") or item.get("totale") or item.get("importo") or item.get("amount")
                or item.get("prezzo_totale") or item.get("partial_total") or item.get("line_total")
            )
            if tot is None:
                qty = _to_float(item.get("qty") or item.get("quantita") or item.get("quantità") or item.get("qta") or item.get("quantity"))
                up = _to_float(
                    item.get("unit_price") or item.get("prezzo_unitario") or item.get("prezzo") or item.get("price")
                    or item.get("unit_cost") or item.get("unitCost") or item.get("costo_unitario")
                )
                if qty is not None and up is not None:
                    tot = qty * up

            if not descr:
                try:
                    descr = json.dumps(item, ensure_ascii=False)[:120]
                except Exception:
                    descr = "Voce"

            row = "- "
            if code:
                row += f"{code} - "
            row += descr
            if tot is not None:
                row += f" → {tot:.2f} €"
            lines.append(row)

        if len(items) > limit:
            lines.append(f"… e altre {len(items) - limit} voci.")

        return {"INTENT_DB": "COMPUTO_CAT_ITEMS", "answer": "\n".join(lines)}

    @staticmethod
    def computo_top_expensive(text: str, project_id: str):
        """Mostra le voci più costose del computo (flatten di tutte le categorie)."""
        if not project_id:
            return None

        tl = (text or "").lower()
        if "computo" not in tl and not any(k in tl for k in ("più costose", "piu costose", "più care", "piu care", "più costosa", "piu costosa", "top")):
            return None

        if not any(k in tl for k in ("più cost", "piu cost", "più car", "piu car", "top")):
            return None

        # N richiesto
        n = 5
        mtop = re.search(r"\btop\s*(\d{1,2})\b", tl)
        if mtop:
            try:
                n = int(mtop.group(1))
            except Exception:
                pass
        else:
            mnum = re.search(r"\b(\d{1,2})\s+(voci|lavorazioni)\b", tl)
            if mnum:
                try:
                    n = int(mnum.group(1))
                except Exception:
                    pass
        n = max(1, min(20, n))

        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            return {"INTENT_DB": "COMPUTO_TOP", "answer": "Cantiere non trovato."}

        comp_ids = list(getattr(p, "metric_computation_id", None) or [])
        if not comp_ids:
            return {"INTENT_DB": "COMPUTO_TOP", "answer": "Non trovo un computo associato a questo cantiere."}

        cid = comp_ids[-1]
        c = ComputoDoc.objects(id=cid).first()
        if not c:
            return {"INTENT_DB": "COMPUTO_TOP", "answer": "Ho un riferimento al computo, ma il documento non è presente nel DB."}

        boq = list(getattr(c, "bill_of_quantities", None) or [])
        if not boq:
            return {"INTENT_DB": "COMPUTO_TOP", "answer": "Il computo non contiene voci."}

        def _to_float(x):
            if isinstance(x, (int, float)):
                return float(x)
            if isinstance(x, str):
                xs = x.strip().replace("€", "").replace(" ", "")
                if xs.count(",") == 1 and xs.count(".") >= 1:
                    xs = xs.replace(".", "").replace(",", ".")
                else:
                    xs = xs.replace(",", ".")
                try:
                    return float(xs)
                except Exception:
                    return None
            return None

        def _item_total(item: dict) -> float | None:
            """Calcola il totale di una singola voce.

            1) prova campi espliciti (total/totale/importo/...)
            2) fallback: qty * prezzo unitario
            """
            if not isinstance(item, dict):
                return None

            tot = _to_float(
                item.get("total") or item.get("totale") or item.get("importo") or item.get("amount")
                or item.get("prezzo_totale") or item.get("partial_total") or item.get("line_total")
            )
            if tot is not None:
                return tot

            qty = _to_float(item.get("qty") or item.get("quantita") or item.get("quantità") or item.get("qta") or item.get("quantity"))
            up = _to_float(
                item.get("unit_price") or item.get("prezzo_unitario") or item.get("prezzo") or item.get("price")
                or item.get("unit_cost") or item.get("unitCost") or item.get("costo_unitario")
            )
            if qty is not None and up is not None:
                return qty * up

            return None

        # Flatten items
        flat = []
        for cat in boq:
            if not isinstance(cat, dict):
                continue
            cat_name = cat.get("category") or cat.get("categoria") or "Categoria"
            items = cat.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    tot = _item_total(item)
                    if tot is None:
                        continue
                    flat.append((tot, cat_name, item))
            else:
                # caso piatto
                tot = _item_total(cat)
                if tot is not None:
                    flat.append((tot, "Computo", cat))

        if not flat:
            # Fallback: se non abbiamo importi per singola voce, ordiniamo le categorie per totale categoria
            cats = []
            for cat in boq:
                if not isinstance(cat, dict):
                    continue
                cat_name = cat.get("category") or cat.get("categoria")
                if not cat_name:
                    continue
                cat_tot = _to_float(cat.get("category_total") or cat.get("totale_categoria") or cat.get("total") or cat.get("totale"))
                if cat_tot is not None:
                    cats.append((cat_tot, cat_name))

            if cats:
                cats.sort(key=lambda x: x[0], reverse=True)
                top_cats = cats[: min(n, len(cats))]
                lines = ["Non trovo importi per singola voce: ti mostro le categorie più costose del computo:"]
                for tot, name in top_cats:
                    lines.append(f"- {tot:.2f} € | {name}")
                return {"INTENT_DB": "COMPUTO_TOP", "answer": "\n".join(lines)}

            return {"INTENT_DB": "COMPUTO_TOP", "answer": "Non trovo importi numerici nel computo."}

        flat.sort(key=lambda x: x[0], reverse=True)
        top = flat[:n]

        lines = [f"Top {len(top)} voci più costose del computo:"]
        for tot, cat_name, item in top:
            code = item.get("code") or item.get("codice") or item.get("reference") or item.get("ref")
            descr = (
                item.get("description")
                or item.get("descrizione")
                or item.get("voce")
                or item.get("lavorazione")
                or item.get("nome")
                or item.get("titolo")
                or item.get("label")
            )
            if not descr:
                try:
                    descr = json.dumps(item, ensure_ascii=False)[:120]
                except Exception:
                    descr = "Voce"

            row = f"- {tot:.2f} € | {cat_name}"
            if code:
                row += f" | {code}"
            row += f" | {descr}"
            lines.append(row)

        return {"INTENT_DB": "COMPUTO_TOP", "answer": "\n".join(lines)}

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