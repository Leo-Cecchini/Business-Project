# utils/normalization.py
from unidecode import unidecode

def norm(s: str) -> str:
    return unidecode((s or "").strip().lower())

def normalize_role(role: str, role_aliases: dict[str, list[str]] | None = None) -> str:
    r = norm(role)
    if not role_aliases:
        return r
    # trova la forma “canonica” usando ROLE_ALIASES
    for base, variants in role_aliases.items():
        if r == norm(base) or r in {norm(v) for v in variants}:
            return norm(base)
    return r

def generate_role_aliases(canonical_role: str, role_aliases: dict[str, list[str]] | None = None) -> set[str]:
    r = norm(canonical_role)
    out = {r}
    if not role_aliases:
        return out
    for base, variants in role_aliases.items():
        if r == norm(base):
            out.update({norm(v) for v in variants})
            out.add(norm(base))
            break
    return out