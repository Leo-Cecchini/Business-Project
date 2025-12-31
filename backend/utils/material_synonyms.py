# utils/material_synonyms.py
"""
Gruppi di sinonimi per materiali edili.
Usato per ricerca fuzzy e normalizzazione nomi materiali.
"""

MATERIAL_SYNONYM_GROUPS = [
    {"cemento", "cem", "portland"},
    {"calcestruzzo", "cls"},
    {"malta", "premiscelato", "m5"},
    {"intonaco", "civile"},
    {"calce", "idrata", "idratazione"},
    {"cartongesso", "gkb", "lastra"},
    {"rete", "elettrosaldata", "rete6", "rete 6"},
    {"acciaio", "barra", "tondino", "b450", "b450c", "b450d"},
    {"pittura", "lavabile", "smalto", "idropittura"},
    {"stucco", "fughe"},
    {"primer", "bituminoso", "poliuretanico"},
    {"guaina", "bituminosa", "ardesiata", "epdm"},
    {"eps", "polistirene", "isolante"},
    {"xps", "polistirene", "isolante"},
    {"lana", "roccia", "isolante"},
    {"nastro", "butilico"},
    {"additivo", "antigelo", "fluidificante"},
    {"sabbia"},
    {"ghiaia", "pietrisco"},
    {"piastrella", "gres"},
    {"colla", "c2te", "adesivo"},
    {"vite"},
    {"tassello"},
    {"taglierino"},
    {"tubo", "corrugato"},
    {"cavo", "fg16or"},
    {"scatola", "503"},
    {"placca"},
    {"interruttore"},
    {"presa", "schuko"},
    {"quadro", "elettrico"},
    {"magnetotermico"},
    {"differenziale", "rcd"},
    {"multistrato", "raccordo", "press"},
    {"valvola", "sfera"},
    {"rubinetto", "lavabo", "piletta"},
    {"frattazzo", "spugna"},
    {"mazzetta"},
    {"detergente", "cementizio"},
    {"scopa", "industriale"},
]

# Pre-build synonym lookup
SYNONYM_TO_ROOT = {}
for group in MATERIAL_SYNONYM_GROUPS:
    root = sorted(group, key=len)[0]
    for s in group:
        SYNONYM_TO_ROOT[s] = root

__all__ = ['MATERIAL_SYNONYM_GROUPS', 'SYNONYM_TO_ROOT']