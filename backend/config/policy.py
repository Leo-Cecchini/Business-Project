# utils/policy.py
from dataclasses import dataclass
from enum import Enum, auto

class Intent(Enum):
    DOC_QA = auto()         # domanda sui documenti interni
    VERIFY_PRICE = auto()   # verifica prezzi materiali
    WEATHER = auto()        # meteo
    SCHEDULING = auto()     # pianificazione lavori (può usare meteo)
    OFFTOPIC = auto()

@dataclass
class PolicyDecision:
    allow_web: bool
    allow_local: bool
    reason: str
    blocked: bool = False

PRICE_WORDS = {"prezzo","costo","listino","quotazione","€/kg","€/m3","€/mc","cemento","calcestruzzo","cls","acciaio","rame","bitume"}
WEATHER_WORDS = {"meteo","pioggia","vento","temperatura","temporale","neve","allerta"}
OUTDOOR_WORDS = {"esterno","all'aperto","cantiere","tetto","facciata","posa","scavo","asfalto","impermeabilizzazione"}
LOCATION_HINTS = {" via "," viale "," piazza "," cantiere "," indirizzo"," cap "," comune "," provincia "}

def _has_any(q: str, words: set) -> bool:
    ql = f" {q.lower()} "
    return any(w in ql for w in words)

def _has_location(q: str) -> bool:
    return _has_any(q, LOCATION_HINTS)

def _is_outdoor(q: str) -> bool:
    return _has_any(q, OUTDOOR_WORDS)

def classify_intent(q: str) -> Intent:
    if _has_any(q, WEATHER_WORDS):
        return Intent.WEATHER
    if _has_any(q, PRICE_WORDS):
        return Intent.VERIFY_PRICE
    if any(w in q.lower() for w in ("programma","pianifica","schedula","scadenza")) and _is_outdoor(q):
        return Intent.SCHEDULING
    if q.strip():
        return Intent.DOC_QA
    return Intent.OFFTOPIC

def decide_policy(question: str) -> PolicyDecision:
    intent = classify_intent(question)
    q = question.lower()

    if intent == Intent.WEATHER:
        if not (_is_outdoor(q) and _has_location(q)):
            return PolicyDecision(False, False, "Meteo non collegato a lavoro outdoor e luogo specifico.", True)
        return PolicyDecision(True, True, "Meteo ammesso solo per valutare eseguibilità lavori outdoor in luogo/periodo specifici.")

    if intent == Intent.VERIFY_PRICE:
        return PolicyDecision(True, True, "Verifica prezzi materiali via fonti affidabili e confronto con dati interni.")

    if intent == Intent.SCHEDULING:
        return PolicyDecision(True, True, "Pianificazione lavori: ammesso meteo/norme con fonti separate.")

    if intent == Intent.DOC_QA:
        return PolicyDecision(False, True, "Domanda su documenti interni: usa solo il vector store.")

    return PolicyDecision(False, False, "Richiesta fuori contesto.", True)