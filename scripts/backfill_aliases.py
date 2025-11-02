# scripts/backfill_aliases.py
from unidecode import unidecode
from models_mongo.worker import WorkerDoc
from models_mongo.material import MaterialDoc
from utils.intent_router import ROLE_ALIASES
from routes.chat import MATERIAL_SYNONYM_GROUPS

def _norm(s: str) -> str:
    return unidecode((s or "").lower().strip())

def build_material_aliases():
    # mappa rapida da token -> radice
    syn_to_root = {}
    for g in MATERIAL_SYNONYM_GROUPS:
        root = sorted(g, key=len)[0]
        for s in g:
            syn_to_root[_norm(s)] = root

    for m in MaterialDoc.objects:
        aliases = set(m.aliases or [])
        # name, category, subcategory tokenizzati
        for raw in filter(None, [m.name, m.category, m.subcategory]):
            for tok in _norm(raw).split():
                if tok in syn_to_root:
                    aliases.add(syn_to_root[tok])
                aliases.add(tok)
        m.aliases = sorted(aliases)
        m.save()

def build_worker_aliases():
    # role aliases
    role_map = {k: set(v) for k, v in ROLE_ALIASES.items()}
    for w in WorkerDoc.objects:
        aliases = set(w.aliases or [])
        r = _norm(w.role)
        aliases.add(r)
        for base, variants in role_map.items():
            if r == _norm(base) or r in {_norm(x) for x in variants}:
                aliases.update({_norm(x) for x in variants})
                aliases.add(_norm(base))
        w.aliases = sorted(aliases)
        w.save()

if __name__ == "__main__":
    build_material_aliases()
    build_worker_aliases()
    print("Done.")