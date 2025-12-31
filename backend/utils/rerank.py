# utils/rerank.py
"""
Utility di reranking riusabili (opzionali).

Se non vuoi un file separato, puoi ignorarlo: la logica è già inclusa nel VectorStore.
"""

import math
import re

PRIORITY_SOURCES = [
    "capitolato", "computo", "computo metrico", "preventivo",
    "offerta", "contratto", "scheda tecnica", "analisi prezzi",
]

def priority_score(source: str) -> int:
    s = (source or "").lower()
    for i, key in enumerate(PRIORITY_SOURCES):
        if key in s:
            return 100 - i * 10  # 100, 90, 80, ...
    return 0

def keyword_boost(text: str, query: str) -> float:
    """Boost lessicale: +log(1+hits) sui token della query presenti nel testo."""
    if not text or not query:
        return 0.0
    q_tokens = [t for t in re.findall(r"[a-zà-ù0-9]+", query.lower()) if len(t) > 2]
    if not q_tokens:
        return 0.0
    t = (text or "").lower()
    hits = sum(1 for qt in q_tokens if qt in t)
    return math.log(1 + hits)
