# services/work_service.py
from datetime import datetime, timedelta
import math
from typing import List, Dict, Any, Optional

from bson import ObjectId
from mongoengine.connection import get_db

class WorkService:
    """Gestisce la logica dei lavori: aggiunta, pianificazione, assegnazione."""
    
    ALLOWED_ASSIGN_STATES = {"Confermato", "In corso", "Attivo", "Active"}

    @staticmethod
    def _norm_role(x: Optional[str]) -> str:
        s = (x or "").strip().lower()
        s = " ".join(s.split())
        # normalizza plurali comuni e varianti
        repl = {
            "muratori": "muratore",
            "elettricisti": "elettricista",
            "idraulici": "idraulico",
            "carpentieri": "carpentiere",
            "piastrellisti": "piastrellista",
            "imbianchini": "imbianchino",
            "falegnami": "falegname",
            "manovali": "manovale",
            "operai": "operaio",
            "operaio edile": "operaio",
            "operaio edil": "operaio",
            "operaio edile specializzato": "operaio",
            "operaio specializzato": "operaio",
            "capocantiere": "capo cantiere",
        }
        return repl.get(s, s)

    @staticmethod
    def _date_to_ymd(x) -> Optional[str]:
        """Accetta str, datetime/date e ritorna 'YYYY-MM-DD' oppure None."""
        if x is None:
            return None
        if isinstance(x, str):
            return x
        try:
            return x.strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _infer_roles_from_work_name(name: Optional[str]) -> List[str]:
        """Inferisce ruoli plausibili dal nome del lavoro quando mancano primary_role/roles_allowed."""
        n = (name or "").lower()
        roles: List[str] = []

        def add(*rs: str):
            for r in rs:
                rr = WorkService._norm_role(r)
                if rr and rr not in roles:
                    roles.append(rr)

        if any(k in n for k in ["elettric", "quadri", "cablagg", "presa", "interrutt", "dichiarazione di conformità impianto elettrico"]):
            add("elettricista")
        if any(k in n for k in ["idraul", "sanitari", "tubaz", "rubinet", "scarico", "dichiarazione di conformità impianto idrico"]):
            add("idraulico")
        if any(k in n for k in ["demol", "rimozion", "tracce", "macerie", "smalt", "trasporto"]):
            add("muratore", "manovale")
        if any(k in n for k in ["tramezz", "intonac", "masset", "muratur", "ricostru", "rasatura"]):
            add("muratore")
        if any(k in n for k in ["cartong", "controsoff", "controtelai"]):
            add("carpentiere", "muratore")
        if any(k in n for k in ["piastrel", "gres", "rivest", "battiscopa"]):
            add("piastrellista")
        if any(k in n for k in ["pittura", "tinteggi", "vernici"]):
            add("imbianchino")
        if any(k in n for k in ["infissi", "porte", "maniglie", "legno"]):
            add("falegname")
        if any(k in n for k in ["fabbro", "metallo"]):
            add("falegname")

        if not roles:
            add("operaio")
        return roles

    @staticmethod
    def _work_display_name(w: Dict[str, Any]) -> str:
        return (
            w.get("work_name")
            or w.get("name")
            or w.get("title")
            or w.get("label")
            or ""
        )

    @staticmethod
    def _role_aliases(role: str) -> List[str]:
        r = WorkService._norm_role(role)
        if not r:
            return []
        # sinonimi pragmatici (per match con seed/DB)
        if r in ["muratore", "manovale", "operaio", "operaio edile"]:
            return ["muratore", "manovale", "operaio", "operaio edile"]
        if r == "capo cantiere":
            return ["capo cantiere", "capocantiere", "responsabile cantiere", "foreman"]
        return [r]

    @staticmethod
    def _project_query(pid: str) -> dict:
        """Query robusta: supporta pid come ObjectId, id custom, name o site_id."""
        ors = [
            {"id": pid},
            {"_id": pid},
            {"name": pid},
            {"site_id": pid},
        ]
        try:
            ors.append({"_id": ObjectId(str(pid))})
        except Exception:
            pass
        return {"$or": ors}

    @staticmethod
    def _load_project_dict(pid: str):
        db = get_db()

        # 1) Caso standard: pid è una stringa ObjectId
        try:
            oid = ObjectId(str(pid))
            p = db["projects"].find_one({"_id": oid})
            if p:
                return p
        except Exception:
            pass

        # 2) Fallback: id custom / name / site_id
        return db["projects"].find_one(WorkService._project_query(pid))

    @staticmethod
    def _save_works(proj_id, works: list):
        db = get_db()
        db["projects"].update_one(WorkService._project_query(str(proj_id)), {"$set": {"works": works}})

    @staticmethod
    def add_work_item(pid: str, code: str, qty: float, notes: str = None) -> Dict[str, Any]:
        """Aggiunge un singolo lavoro al progetto."""
        db = get_db()
        proj = WorkService._load_project_dict(pid)
        if not proj: return {"ok": False, "error": "Progetto non trovato"}

        code = (code or "").strip().upper()
        if not code or qty <= 0: return {"ok": False, "error": "Dati invalidi"}

        cat = db["work_catalog"].find_one({"code": code})
        if not cat: return {"ok": False, "error": f"Codice {code} non trovato in catalogo"}

        item = {
            "work_code": code,
            "work_name": cat.get("name"),
            "qty": qty,
            "unit": cat.get("unit"),
            "primary_role": cat.get("primary_role"),
            "roles_allowed": cat.get("roles_allowed") or [],
            "status": "planned",
            "crew_size_planned": cat.get("min_crew", 1),
            "hours_estimated": None,
            "start_date_planned": None,
            "end_date_planned": None,
            "notes": (notes or "").strip() or None,
            "workers": [],
            "workers_meta": [],
        }
        
        works = list(proj.get("works") or [])
        works.append(item)
        WorkService._save_works(pid, works)
        return {"ok": True, "added": item, "total": len(works)}

    @staticmethod
    def plan_project(pid: str, start_from: str | None = None) -> Dict[str, Any]:
        """Ricalcola le date pianificate (Plan).

        Frontend contract (SiteHeader.jsx):
          POST /api/projects/<id>/plan body: { start_from: 'auto' | 'YYYY-MM-DD', replace: true }

        Questo metodo:
          - calcola crew_size_planned / number_of_workers in modo coerente usando min/max dal work_catalog
          - calcola start/end stimati basandosi su qty e produttività
        """
        return WorkService._plan_project_impl(pid, start_from=start_from)

    @staticmethod
    def _choose_crew(qty: float, prod_per_worker_per_hour: float, min_crew: int, max_crew: int, daily_hours: float = 8.0, target_days: int = 3) -> int:
        """Sceglie una crew tra min/max in modo deterministico.

        Obiettivo: evitare che tutto finisca a 1 operaio, ma senza assegnare sempre il massimo.
        Heuristica: scegli il numero di operai necessario a tenere la durata sotto ~target_days,
        rispettando min_crew/max_crew.
        """
        min_crew = max(1, int(min_crew or 1))
        max_crew = max(min_crew, int(max_crew or min_crew))
        try:
            qty = float(qty or 0.0)
        except Exception:
            qty = 0.0
        try:
            prod = float(prod_per_worker_per_hour or 0.0)
        except Exception:
            prod = 0.0

        if qty <= 0 or prod <= 0 or daily_hours <= 0:
            return min_crew

        needed = int(math.ceil(qty / (prod * float(daily_hours) * float(max(1, target_days)))))
        if needed <= 0:
            needed = min_crew
        return max(min_crew, min(max_crew, needed))

    @staticmethod
    def _plan_project_impl(pid: str, start_from: str | None = None) -> Dict[str, Any]:
        db = get_db()
        proj = WorkService._load_project_dict(pid)
        if not proj: return {"ok": False, "error": "Progetto non trovato"}
        
        works = list(proj.get("works") or [])
        if not works: return {"ok": False, "error": "Nessun lavoro da pianificare"}

        # start_from può essere 'auto' oppure una data YYYY-MM-DD
        start0_str = None
        if start_from and str(start_from).strip().lower() != "auto":
            start0_str = str(start_from).strip()
        if not start0_str:
            start0_str = proj.get("start_date_estimated") \
                or ((proj.get("meta_extra") or {}).get("estimate") or {}).get("start") \
                or datetime.utcnow().date().isoformat()
        
        # Carica catalogo
        codes = list({ w.get("work_code") for w in works if w.get("work_code") })
        cat_docs = list(db["work_catalog"].find({"code": {"$in": codes}}))
        cat = { c["code"]: c for c in cat_docs }
        
        # Topological Sort (semplificato)
        g = { w["work_code"]: set(cat.get(w["work_code"], {}).get("prerequisites", [])) for w in works if w.get("work_code") }
        ordered = []
        seen = set()
        def visit(code):
            if code in seen: return
            for dep in g.get(code, []):
                if dep in cat: visit(dep)
            seen.add(code); ordered.append(code)
        
        for w in works:
            if w.get("work_code"): visit(w["work_code"])
            
        by_code = { w["work_code"]: w for w in works if w.get("work_code") }
        
        # Calcolo date
        try:
            cursor = datetime.strptime(start0_str, "%Y-%m-%d")
        except ValueError:
            cursor = datetime.utcnow()

        planned = []
        planned_codes: set[str] = set()
        
        for code in ordered:
            w = by_code.get(code)
            c = cat.get(code)
            if not (w and c): continue

            planned_codes.add(code)
            
            qty = float(w.get("qty") or 0)
            prod = float(c.get("productivity_per_worker_per_hour") or 1.0)

            # crew coerente: usa min/max crew dal catalogo e qty/produttività
            min_crew = int(c.get("min_crew") or 1)
            max_crew = int(c.get("max_crew") or min_crew)
            crew = int(w.get("crew_size_planned") or 0)
            if crew <= 0:
                crew = WorkService._choose_crew(qty=qty, prod_per_worker_per_hour=prod, min_crew=min_crew, max_crew=max_crew)
            
            hours = 0 if qty <= 0 else qty / (prod * max(1, crew))
            days = 0 if hours == 0 else max(1, int((hours/8)+0.999))
            
            start_d = cursor
            end_d = cursor + timedelta(days=max(0, days-1))
            cursor = end_d + timedelta(days=1)
            
            w.update({
                "workers": list(w.get("workers") or []),
                "workers_meta": list(w.get("workers_meta") or []),
                "primary_role": w.get("primary_role") or c.get("primary_role"),
                "roles_allowed": w.get("roles_allowed") or c.get("roles_allowed", []),
                "hours_estimated": hours,
                "crew_size_planned": crew,
                "number_of_workers": float(crew),
                "start_date_planned": start_d.strftime("%Y-%m-%d"),
                "end_date_planned": end_d.strftime("%Y-%m-%d")
            })
            planned.append(w)

        # Fallback: conserva eventuali lavori senza work_code (o non presenti in catalogo)
        leftovers = [w for w in works if not w.get("work_code") or str(w.get("work_code")) not in planned_codes]
        for w in leftovers:
            # Se già pianificato altrove, mantieni start/end
            sd = WorkService._date_to_ymd(w.get("start_date_planned"))
            ed = WorkService._date_to_ymd(w.get("end_date_planned"))
            if sd and ed:
                planned.append(w)
                continue

            crew = int(w.get("number_of_workers") or w.get("crew_size_planned") or 1)
            crew = max(1, crew)
            start_d = cursor
            end_d = cursor  # default 1 day
            cursor = end_d + timedelta(days=1)
            w.update({
                "number_of_workers": float(crew),
                "crew_size_planned": float(crew),
                "start_date_planned": start_d.strftime("%Y-%m-%d"),
                "end_date_planned": end_d.strftime("%Y-%m-%d"),
            })
            planned.append(w)
            
        WorkService._save_works(pid, planned)
        return {"ok": True, "planned": len(planned), "items": planned}

    @staticmethod
    def auto_assign(pid: str) -> Dict[str, Any]:
        """Assegna operai ai lavori pianificati."""
        db = get_db()
        proj = WorkService._load_project_dict(pid)
        if not proj: return {"ok": False, "error": "Progetto non trovato"}
        
        status = str(proj.get("status") or "").strip()
        status_norm = "Attivo" if status == "Active" else status
        if status_norm not in WorkService.ALLOWED_ASSIGN_STATES:
             return {"ok": False, "error": f"Stato {status} non valido per assegnazione"}
             
        all_works = list(proj.get("works") or [])
        # Normalizza struttura works (compatibilità con seed/vecchi documenti)
        for ww in all_works:
            ww.setdefault("workers", [])
            ww.setdefault("workers_meta", [])
        works = [w for w in all_works if w.get("start_date_planned")]
        # Normalizza date (alcuni flussi salvano datetime, altri stringhe)
        for ww in works:
            ww["start_date_planned"] = WorkService._date_to_ymd(ww.get("start_date_planned"))
            ww["end_date_planned"] = WorkService._date_to_ymd(ww.get("end_date_planned"))
        works = [w for w in works if w.get("start_date_planned") and w.get("end_date_planned")]
        works.sort(key=lambda x: (x.get("start_date_planned"), x.get("end_date_planned")))

        if not works:
            return {"ok": False, "error": "Nessun lavoro pianificato con date (start/end). Prima esegui Pianifica/Sequenza lavori."}

        # Prima di ricalcolare, rimuovi vecchie prenotazioni di questo progetto per evitare "effetto saturazione"
        try:
            db["workers"].update_many(
                {"bookings.project_id": str(pid)},
                {"$pull": {"bookings": {"project_id": str(pid)}}},
            )
        except Exception:
            pass

        # Preferisci disponibili se il campo esiste, altrimenti prendi tutti
        workers = list(db["workers"].find({"available": True}))
        if not workers:
            workers = list(db["workers"].find({}))

        by_role: Dict[str, list] = {}
        for wkr in workers:
            keys = set()

            # ruolo principale
            keys.add(WorkService._norm_role(wkr.get("role")))

            # aliases opzionali
            for a in (wkr.get("aliases") or []):
                keys.add(WorkService._norm_role(a))

            # skills opzionali (fondamentali per specialisti)
            for s in (wkr.get("skills") or []):
                keys.add(WorkService._norm_role(s))

            # tieni anche raw (se già normalizzato)
            raw_role = (wkr.get("role") or "").strip().lower()
            if raw_role:
                keys.add(raw_role)

            for k in [kk for kk in keys if kk]:
                # indicizza anche alias (es. operaio/operaio edile/manovale)
                for alias in WorkService._role_aliases(k):
                    by_role.setdefault(alias, []).append(wkr)

        assignments = []

        def _overlaps(s1, e1, s2, e2):
            return not (e1 < s2 or e2 < s1)
            
        def _is_free(w, s_str, e_str):
            s_str = WorkService._date_to_ymd(s_str)
            e_str = WorkService._date_to_ymd(e_str)
            if not s_str or not e_str:
                return False
            try:
                s, e = datetime.strptime(s_str, "%Y-%m-%d"), datetime.strptime(e_str, "%Y-%m-%d")
            except Exception:
                return False

            for b in w.get("bookings", []):
                try:
                    bs_raw = b.get("from") or b.get("start") or b.get("date_from")
                    be_raw = b.get("to") or b.get("end") or b.get("date_to")
                    bs_s = WorkService._date_to_ymd(bs_raw)
                    be_s = WorkService._date_to_ymd(be_raw)
                    if not bs_s or not be_s:
                        continue
                    bs, be = datetime.strptime(bs_s, "%Y-%m-%d"), datetime.strptime(be_s, "%Y-%m-%d")
                    if _overlaps(s, e, bs, be):
                        return False
                except Exception:
                    continue
            return True

        # Vincolo: ogni cantiere deve avere almeno 1 capo cantiere sull'intero periodo
        proj_start = min(w.get("start_date_planned") for w in works)
        proj_end = max(w.get("end_date_planned") for w in works)

        foreman_roles = [
            "capo cantiere",
            "capocantiere",
            "responsabile cantiere",
            "foreman",
        ]

        foreman_pool = []
        for rk in foreman_roles:
            foreman_pool.extend(by_role.get(rk, []))
        # fallback: contiene 'cantiere' e 'capo'
        if not foreman_pool:
            for k, vals in by_role.items():
                if "cantiere" in k and ("capo" in k or "responsabile" in k):
                    foreman_pool.extend(vals)

        foreman_pool = sorted(list({str(w.get("_id")): w for w in foreman_pool}.values()), key=lambda x: len(x.get("bookings") or []))

        foreman_assigned = False
        for cand in foreman_pool:
            if _is_free(cand, proj_start, proj_end):
                booking = {"project_id": str(pid), "work_name": "CAPO_CANTIERE", "from": proj_start, "to": proj_end}
                db["workers"].update_one({"_id": cand["_id"]}, {"$push": {"bookings": booking}})
                cand.setdefault("bookings", []).append(booking)
                assignments.append({
                    "worker_id": str(cand.get("_id")),
                    "worker_name": cand.get("name"),
                    "role": "capo cantiere",
                    "work_name": "CAPO_CANTIERE",
                    "start": proj_start,
                    "end": proj_end,
                })
                # Work sintetico per farlo comparire nel grafico (UI legge works[*].workers)
                capo_wid = str(cand.get("_id"))
                synthetic = {
                    "work_code": "CAPO_CANTIERE",
                    "work_name": "CAPO CANTIERE",
                    "qty": 1,
                    "unit": "pz",
                    "primary_role": "capo cantiere",
                    "roles_allowed": ["capo cantiere"],
                    "status": "planned",
                    "crew_size_planned": 1,
                    "hours_estimated": None,
                    "start_date_planned": proj_start,
                    "end_date_planned": proj_end,
                    "notes": "Assegnazione minima obbligatoria",
                    "workers": [capo_wid],
                    "workers_meta": [
                        {
                            "worker_id": capo_wid,
                            "worker_name": cand.get("name"),
                            "role": "capo cantiere",
                        }
                    ],
                }

                replaced = False
                for i, ww in enumerate(all_works):
                    if (ww.get("work_code") == "CAPO_CANTIERE") or (str(ww.get("work_name") or "").upper() in ["CAPO CANTIERE", "CAPO_CANTIERE"]):
                        all_works[i] = synthetic
                        replaced = True
                        break
                if not replaced:
                    all_works.insert(0, synthetic)
                foreman_assigned = True

                # Persisti anche sul progetto per UI/Chat (compatibilità)
                try:
                    db["projects"].update_one(
                        WorkService._project_query(str(pid)),
                        {"$set": {
                            "meta_extra.foreman_id": str(cand.get("_id")),
                            "meta_extra.capo_cantiere_id": str(cand.get("_id")),
                            "foreman_id": str(cand.get("_id")),
                            "capo_cantiere_id": str(cand.get("_id")),
                        }}
                    )
                except Exception:
                    pass
                break

        if not foreman_assigned:
            return {"ok": False, "error": f"Nessun capo cantiere disponibile per il periodo {proj_start} → {proj_end}."}

        for w in works:
            if (w.get("work_code") == "CAPO_CANTIERE") or (str(w.get("work_name") or "").upper() in ["CAPO CANTIERE", "CAPO_CANTIERE"]):
                continue
            # reset workers per ricalcolo assegnazioni (click ripetuti)
            w["workers"] = []
            w["workers_meta"] = []
            need = int(w.get("number_of_workers") or w.get("crew_size_planned") or 1)
            roles = [WorkService._norm_role(r) for r in (w.get("roles_allowed") or []) if str(r).strip()]
            primary = WorkService._norm_role(w.get("primary_role"))
            if primary and primary not in roles:
                roles.insert(0, primary)
            if not roles:
                roles = WorkService._infer_roles_from_work_name(WorkService._work_display_name(w))
            
            taken = 0
            start, end = w["start_date_planned"], w["end_date_planned"]
            
            for r in roles:
                pool = by_role.get(r)
                if not pool:
                    # prova alias del ruolo
                    pool = []
                    for rr in WorkService._role_aliases(r):
                        pool.extend(by_role.get(rr, []))
                # fallback: match per contenimento (es. "operaio edile" contiene "operaio")
                if not pool:
                    for k, vals in by_role.items():
                        try:
                            if r and r in k:
                                pool.extend(vals)
                        except Exception:
                            continue
                pool = sorted(pool, key=lambda x: len(x.get("bookings") or []))
                for cand in pool:
                    if taken >= need: break
                    if _is_free(cand, start, end):
                        # Assegna (Aggiorna DB worker)
                        booking = {"project_id": str(pid), "work_name": w.get("work_name"), "from": start, "to": end}
                        db["workers"].update_one({"_id": cand["_id"]}, {"$push": {"bookings": booking}})
                        cand.setdefault("bookings", []).append(booking)
                        wid = str(cand.get("_id"))
                        # scrivi anche nel work (serve per grafico UI)
                        w.setdefault("workers", [])
                        if wid not in w["workers"]:
                            w["workers"].append(wid)
                        w.setdefault("workers_meta", [])
                        w["workers_meta"].append(
                            {
                                "worker_id": wid,
                                "worker_name": cand.get("name"),
                                "role": r,
                            }
                        )

                        assignments.append({
                            "worker_id": wid,
                            "worker_name": cand.get("name"),
                            "role": r,
                            "work_name": w.get("work_name"),
                            "start": start,
                            "end": end,
                        })
                        taken += 1
                if taken >= need: break

            if taken < need:
                assignments.append({
                    "worker_id": None,
                    "worker_name": None,
                    "role": roles[0] if roles else None,
                    "work_name": w.get("work_name"),
                    "start": start,
                    "end": end,
                    "needed": need,
                    "found": taken,
                    "deficit": need - taken,
                })
        
        # Salva su progetto: works aggiornati + assignments
        WorkService._save_works(pid, all_works)

        me = proj.get("meta_extra") or {}
        me["assignments"] = assignments
        db["projects"].update_one(WorkService._project_query(str(pid)), {"$set": {"meta_extra": me}})

        real_assigned = [a for a in assignments if a.get("worker_id")]
        deficits = [a for a in assignments if a.get("deficit")]

        return {"ok": True, "assigned": len(real_assigned), "deficits": deficits, "items": real_assigned}