# utils/web_retriever.py
from __future__ import annotations

from ddgs import DDGS
import trafilatura
from urllib.parse import urlparse
from typing import List, Dict, Optional
import os
import re

# -------------------------------------------------
# Configurazione Domini
# -------------------------------------------------
DEFAULT_ALLOWED = {
    "edilportale.com", "ingenio-web.it", "ediltecnico.it", "biblus-net.it", "lavoripubblici.it",
    "camcom.it", "uni.com", "mims.gov.it", "mit.gov.it", "istat.it", "gazzettaufficiale.it",
    "ilsole24ore.com", "ansa.it", "repubblica.it", "corriere.it",
    "leroymerlin.it", "manomano.it", "bricoman.it", "tecnoedil.it",
    "ilmeteo.it", "3bmeteo.com", "meteo.it", "aeronautica.difesa.it"
    "habitissimo.it", "prontopro.it", "instapro.it" # Aggiunti portali preventivi utili
}

# Blocklist aggressiva per evitare risultati cinesi/spam
DEFAULT_BLOCKED = {
    "reddit", "quora", "pinterest", "facebook", "instagram",
    "tiktok", "x.com", "twitter", "youtube", "vimeo",
    "zhihu", "baidu", "weibo", "qq.com", "163.com", "sohu", "douban",
    "tripadvisor", "booking", "alibaba", "temu", "shein"
    # --- Nuovi filtri anti-spam e anti-cookie ---
    "consent.", "accounts.", "login.", "signup.", "auth.", "support.", "help."
}

ENV_ALLOWED = {d.strip().lower() for d in os.getenv("WEB_ALLOWED_DOMAINS", "").split(",") if d.strip()}
ENV_BLOCKED = {d.strip().lower() for d in os.getenv("WEB_BLOCKED_DOMAINS", "").split(",") if d.strip()}

ALLOWED_DOMAINS = (ENV_ALLOWED or DEFAULT_ALLOWED)
BLOCKED_DOMAINS = (ENV_BLOCKED or DEFAULT_BLOCKED)

MAX_TEXT_CHARS = int(os.getenv("WEB_MAX_TEXT_CHARS", "8000"))
SAFESEARCH = os.getenv("WEB_SAFESEARCH", "moderate")
REGION = os.getenv("WEB_REGION", "it-it")
TIME_LIMIT = os.getenv("WEB_TIME_LIMIT", None)
STRICT_ALLOWLIST = os.getenv("WEB_STRICT_ALLOWLIST", "false").lower() == "true"
DEBUG_LOG = True

def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except:
        return ""

def _blocked(url: str) -> bool:
    host = _host(url)
    return any(b in host for b in BLOCKED_DOMAINS)

def _allowed(url: str) -> bool:
    host = _host(url)
    return any(d in host for d in ALLOWED_DOMAINS)

def _dedup_keep_best(items: List[Dict], key: str = "url") -> List[Dict]:
    seen = set()
    out = []
    for it in items:
        u = it.get(key)
        if not u or u in seen: continue
        seen.add(u)
        out.append(it)
    return out

def _focus_query(query: str, focus: Optional[str] = None) -> str:
    # 1. Pulizia caratteri
    safe_q = query.replace("è", "e").replace("à", "a").replace("ò", "o").replace("ù", "u").replace("ì", "i")
    base = safe_q.strip()

    # NOTA: Abbiamo RIMOSSO l'aggiunta forzata di "site:it". 
    # Lasciamo che sia il parametro region="it-it" a fare il lavoro sporco.
    # L'aggiunta manuale di site:it causava il ritorno di 0 risultati su query complesse.
            
    return base

# -------------------------------------------------
# Retriever
# -------------------------------------------------
class WebRetriever:
    def __init__(self, max_results: int = 5, timeout: float = 6.0):
        self.max_results = max_results
        self.timeout = timeout

    def search(self, query: str, focus: str | None = None) -> List[Dict]:
        q = _focus_query(query, focus)
        if DEBUG_LOG:
            print(f"[WebRetriever] 🔎 Query: {q}")
        
        raw: List[Dict] = []
        
        # Parole STOP italiane: usate come firewall per scartare risultati esteri/cinesi
        # che sfuggono al filtro region="it-it"
        ITA_STOPWORDS = {
            " il ", " lo ", " la ", " i ", " gli ", " le ", " di ", " a ", " da ", 
            " in ", " con ", " su ", " per ", " è ", " e ", " o ", " del ", " al ", 
            " sono ", " hanno ", " normativa ", " legge ", " decreto ", " art ",
            " euro ", " prezzo ", " costo ", " meteo ", " gradi "
        }

        try:
            with DDGS() as ddgs:
                # Richiediamo più risultati (20) perché il filtro lingua ne scarterà alcuni
                results = ddgs.text(
                    q,
                    max_results=20, 
                    safesearch=SAFESEARCH,
                    region=REGION, # Qui agisce il filtro Italia
                    timelimit=TIME_LIMIT
                )
                
                for r in results:
                    url = r.get("href") or r.get("url")
                    if not url: continue
                    
                    title = r.get("title", "")
                    snippet = r.get("body") or r.get("snippet", "")
                    
                    # 1. Blocklist (Zhihu, ecc.)
                    if _blocked(url): continue

                    # 2. FILTRO LINGUA (Il Firewall)
                    content_check = (title + " " + snippet).lower()
                    
                    # Logica:
                    # - Se lo snippet è molto breve (< 50 chars) e contiene numeri (es. prezzi/meteo), lo accettiamo (rischio basso).
                    # - Altrimenti, DEVE contenere almeno una stopword italiana.
                    is_short_numeric = len(snippet) < 50 and any(c.isdigit() for c in snippet)
                    
                    if not is_short_numeric:
                        # Controlla presenza di parole italiane
                        if not any(sw in content_check for sw in ITA_STOPWORDS):
                            # Se non ha nemmeno una parola italiana comune, è probabilmente spam estero
                            continue

                    raw.append({
                        "title": title,
                        "url": url,
                        "snippet": snippet
                    })

        except Exception as e:
            print(f"[WebRetriever] ❌ Errore DDG: {e}")
            return []

        # Allowlist ordering
        clean = raw
        if STRICT_ALLOWLIST:
            final_list = [it for it in clean if _allowed(it["url"])]
        else:
            trusted = [it for it in clean if _allowed(it["url"])]
            others = [it for it in clean if not _allowed(it["url"])]
            final_list = trusted + others

        final_list = _dedup_keep_best(final_list)[:self.max_results]

        # Fetch Content
        out: List[Dict] = []
        for it in final_list:
            url = it["url"]
            text_content = ""
            
            # Tentativo di scaricare il contenuto completo
            try:
                downloaded = trafilatura.fetch_url(url, timeout=self.timeout)
                if downloaded:
                    text_content = trafilatura.extract(downloaded) or ""
            except Exception:
                pass
            
            # Fallback sullo snippet se il download fallisce o è vuoto
            # (Molto importante per meteo e prezzi rapidi)
            if not text_content or len(text_content) < 100:
                text_content = it["snippet"]
            
            out.append({
                "title": it["title"],
                "url": it["url"],
                "text": text_content[:MAX_TEXT_CHARS],
                "snippet": it["snippet"]
            })

        if DEBUG_LOG:
            print(f"[WebRetriever] ➜ Trovati {len(out)} risultati validi.")
        return out