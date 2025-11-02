# utils/intents.py
from dataclasses import dataclass
from typing import Optional, Literal, Dict, Any

IntentKind = Literal[
    "MATERIALS_SEARCH",     # elenco materiali con filtri
    "MATERIALS_LOOKUP",     # lookup per SKU o nome preciso
    "WORKERS_SEARCH",       # elenco operai/ruoli con filtri
    "WORKERS_COUNT",        # conteggio
    "UNKNOWN"               # lascia al modello
]

@dataclass
class RoutedIntent:
    kind: IntentKind
    query: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None