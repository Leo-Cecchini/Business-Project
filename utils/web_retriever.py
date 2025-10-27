# utils/web_retriever.py
from __future__ import annotations

from duckduckgo_search import DDGS
import trafilatura
from urllib.parse import urlparse
from typing import List, Dict, Optional
import os

# -------------------------------------------------
# Config (override da ENV se presenti)
# -------------------------------------------------
DEFAULT_ALLOWED = {
    # Portali e testate tecniche
    "edilportale.com", "ingenio-web.it", "ediltecnico.it", "biblus-net.it", "lavoripubblici.it",
    # Istituzionali / norme / dati
    "camcom.it", "uni.com", "mims.gov.it", "mit.gov.it", "mase.gov.it", "istat.it",
    # News economiche utili per prezzi
    "ilsole24ore.com", "ansa.it", "repubblica.it", "corriere.it",
    # Prezzari e PA locali
    "prezzario", "regione.", "provincia.", "comune.", "sardegnacat.it", "arpa.", "cittametropolitana.",
    # Retail/grandi catene (come backup)
    "leroymerlin.it", "selfitalia.it", "bricocenter.it", "bricobravo.com", "manomano.it",
}
DEFAULT_BLOCKED = {
    "reddit.", "quora.", "pinterest.", "facebook.", "instagram.",
    "tiktok.", "x.com", "twitter.com", "youtube."
}

# override opzionali da ENV (virgola-separati)
ENV_ALLOWED = {d.strip().lower() for d in os.getenv("WEB_ALLOWED_DOMAINS", "").split(",") if d.strip()}
ENV_BLOCKED = {d.strip().lower() for d in os.getenv("WEB_BLOCKED_DOMAINS", "").split(",") if d.strip()}

ALLOWED_DOMAINS = (ENV_ALLOWED or DEFAULT_ALLOWED)
BLOCKED_DOMAINS = (ENV_BLOCKED or DEFAULT_BLOCKED)

MAX_TEXT_CHARS = int(os.getenv("WEB_MAX_TEXT_CHARS", "6000"))
SAFESEARCH = os.getenv("WEB_SAFESEARCH", "moderate")    # "off" | "moderate" | "strict"
REGION = os.getenv("WEB_REGION", "it-it")               # area/language per la ricerca
TIME_LIMIT = os.getenv("WEB_TIME_LIMIT", None)          # es. "y" (year), "m" (month), "w" (week), "d" (day)
STRICT_ALLOWLIST = os.getenv("WEB_STRICT_ALLOWLIST", "false").lower() == "true"
DEBUG_LOG = os.getenv("WEB_DEBUG_LOG", "true").lower() == "true"

# -------------------------------------------------
# Utils
# -------------------------------------------------
def _host(url: str) -> str:
    return urlparse(url).netloc.lower()

def _blocked(url: str) -> bool:
    host = _host(url)
    return any(b in host for b in BLOCKED_DOMAINS)

def _allowed(url: str) -> bool:
    host = _host(url)
    return (any(d in host for d in ALLOWED_DOMAINS) and not _blocked(url))

def _dedup_keep_best(items: List[Dict], key: str = "url") -> List[Dict]:
    seen = set()
    out = []
    for it in items:
        u = it.get(key)
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out

# parole chiave materiali per “liberare” i filtri quando cerchiamo prezzi
MATERIAL_WORDS = {
    "cemento", "calcestruzzo", "cls", "acciaio", "ferro", "bitume", "asfalto",
    "rame", "sabbia", "ghiaia", "inerti", "malta", "premiscelato"
}

def _is_relevant(text: str, snippet: str, focus: Optional[str]) -> bool:
    """
    Heuristica più permissiva:
    - se focus=price: accetta se testo O snippet contengono pattern prezzo O parole materiale
    - altri focus: usa chiavi classiche
    - se non c'è focus: accetta (lascia al modello fare il resto)
    """
    low = (text or "").lower()
    sn = (snippet or "").lower()

    if focus == "price":
        price_terms = ["€/kg", "€/m3", "euro/kg", "euro/m3", "listino", "prezzo", "costo", "quotazione"]
        if any(w in low or w in sn for w in price_terms):
            return True
        if any(w in low or w in sn for w in MATERIAL_WORDS):
            return True
        return False

    if focus == "weather":
        return any(w in low or w in sn for w in ["meteo", "precipitazioni", "vento", "temperature", "allerte"])

    if focus == "duration":
        return any(w in low or w in sn for w in ["giorni", "settimane", "mesi", "ore", "durata", "lead time", "programmazione", "cronoprogramma"])

    if focus == "standard":
        return any(w in low or w in sn for w in ["uni", "classe", "resistenza", "norma", "cam", "mit", "mims"])

    # no focus -> non filtrare
    return True

def _focus_query(query: str, focus: Optional[str]) -> str:
    # mantieni la query originale; aggiungi booster per l'Italia e unità dove utile
    base = query
    if focus == "price":
        base += " prezzo €/kg €/m3 listino materiale fornitore site:it"
    elif focus == "weather":
        base += " meteo previsioni lavori cantiere eseguibilità site:it"
    elif focus == "duration":
        base += " durata giorni settimane mesi tempi esecuzione cantiere site:it"
    elif focus == "standard":
        base += " norma UNI classe resistenza CAM MIT MIMS requisiti site:it"
    return base

# -------------------------------------------------
# Retriever
# -------------------------------------------------
class WebRetriever:
    """Retriever web 'libero' ma senza mischiare i dati:
       - allowlist NON obbligatoria (si può allentare), blocklist sempre attiva
       - rilevanza più permissiva per focus=price (accetta materiali)
       - il payload web resta separato; l'unione con i documenti interni è gestita dalla UI/modello.
    """

    def __init__(self, max_results: int = 5, timeout: float = 6.0):
        self.max_results = max_results
        self.timeout = timeout

    def search(self, query: str, focus: str | None = None) -> List[Dict]:
        q = _focus_query(query, focus)
        if DEBUG_LOG:
            print(f"[WebRetriever] 🔎 Query: {q} (focus={focus})  region={REGION} timelimit={TIME_LIMIT} strict={STRICT_ALLOWLIST}")
        raw: List[Dict] = []

        # 1) Cerca con DuckDuckGo (aumentiamo un po' i risultati grezzi)
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(
                    q,
                    max_results=max(self.max_results * 3, 12),
                    safesearch=SAFESEARCH,
                    region=REGION,
                    timelimit=TIME_LIMIT
                ):
                    url = r.get("href") or r.get("url")
                    if not url:
                        continue
                    title = r.get("title") or url
                    snippet = r.get("body") or r.get("snippet") or ""
                    raw.append({"title": title, "url": url, "snippet": snippet})
        except Exception as e:
            if DEBUG_LOG:
                print(f"[WebRetriever] ❌ Errore DDG: {e}")
            return []

        # 2) Filtro domini: usa allowlist, ma se vuota e non strict, accetta tutto tranne i bloccati
        filtered = [it for it in raw if _allowed(it["url"])]
        if not filtered and not STRICT_ALLOWLIST:
            filtered = [it for it in raw if not _blocked(it["url"])]

        # 3) Deduplica
        filtered = _dedup_keep_best(filtered, key="url")

        # 4) Fetch contenuto e filtro di rilevanza (più permissivo su price/materiali)
        out: List[Dict] = []
        for it in filtered[: self.max_results]:
            url = it["url"]
            try:
                html = trafilatura.fetch_url(url, timeout=self.timeout)
                text = trafilatura.extract(html) or ""
            except Exception:
                text = ""
            # se non c'è testo estratto, usiamo almeno lo snippet
            if not text and it.get("snippet"):
                text = it["snippet"]

            if not _is_relevant(text, it.get("snippet", ""), focus):
                continue

            item = {
                "title": it["title"],
                "url": url,
                "text": (text or "")[:MAX_TEXT_CHARS],
                "snippet": (it.get("snippet") or "")[:300],
            }
            out.append(item)

        if DEBUG_LOG:
            print(f"[WebRetriever] ➜ risultati finali: {len(out)}")
            for i, o in enumerate(out, 1):
                print(f"  {i}. {o['title']}  ({o['url']})")

        return out