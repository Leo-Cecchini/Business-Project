# routes/work_catalog.py
from flask import Blueprint, jsonify, request
from mongoengine.connection import get_db
from datetime import datetime

workcat_bp = Blueprint("work_catalog", __name__, url_prefix="/api/catalog/works")

@workcat_bp.post("/seed")
def seed_work_catalog():
    """
    Popola/aggiorna il catalogo lavori (idempotente).
    Etichette in inglese, contenuti in italiano.
    """
    db = get_db()
    items = [
        {
            "code": "ELEC_ROUGH",
            "name": "Impianto elettrico - tracce/cablaggio",
            "synonyms": ["cablaggio", "impianto elettrico", "tracce elettriche", "wiring"],
            "primary_role": "elettricista",
            "roles_allowed": ["elettricista"],
            "unit": "m",
            "productivity_per_worker_per_hour": 12,
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"elettricista": 2},
            "pairing_rule": "two-person",
            "prerequisites": [],
            "notes": "Tracciati definiti; accesso ai locali garantito."
        },
        {
            "code": "PLUMB_ROUGH",
            "name": "Impianto idraulico - tubazioni",
            "synonyms": ["tubazioni", "impianto idraulico", "posa tubi"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico"],
            "unit": "m",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"idraulico": 2},
            "pairing_rule": "two-person",
            "prerequisites": [],
            "notes": "Percorsi approvati; materiali disponibili."
        },
        {
            "code": "WALL_BUILD",
            "name": "Costruzione pareti in muratura",
            "synonyms": ["alzare muri", "pareti", "muratura", "tramezzi"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 5,
            "min_crew": 1,
            "max_crew": 4,
            "prerequisites": [],
            "notes": "Tracciamenti a pavimento completati."
        },
        {
            "code": "PLASTER",
            "name": "Intonaco / Rasatura",
            "synonyms": ["intonaco", "rasatura", "finitura pareti"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "cartongessista"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 12,
            "min_crew": 1,
            "max_crew": 4,
            "prerequisites": ["WALL_BUILD"],
            "notes": "Supporti asciutti e puliti."
        },
        {
            "code": "FLOOR_TILE",
            "name": "Posa pavimento (Piastrelle/Gres)",
            "synonyms": ["posa piastrelle", "piastrellatura", "pavimentazione gres"],
            "primary_role": "piastrellista",
            "roles_allowed": ["piastrellista", "muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 8,
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"piastrellista": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["STRU_SCREED", "PLASTER"],
            "notes": "Massetto pronto e asciutto; locali sgombri."
        },
        {
            "code": "PAINT",
            "name": "Tinteggiatura",
            "synonyms": ["imbiancatura", "verniciatura", "pittura pareti"],
            "primary_role": "imbianchino",
            "roles_allowed": ["imbianchino"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 20,
            "min_crew": 1,
            "max_crew": 3,
            "prerequisites": ["PLASTER", "WALL_DRY_FINISH"],
            "notes": "Superfici asciutte; protezioni posate."
        },
        {
            "code": "DEM_WALL",
            "name": "Demolizione tramezzi",
            "synonyms": ["demolizione", "rimozione muri", "buttare giù muro", "demolizioni"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "operaio"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 8,
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"muratore": 2},
            "pairing_rule": "two-person",
            "prerequisites": [],
            "notes": "Verificare assenza impianti; protezione aree."
        },
        {
            "code": "DEM_FLOOR",
            "name": "Rimozione pavimentazione esistente",
            "synonyms": ["rimozione piastrelle", "togliere pavimento", "demolizione pavimento"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "operaio", "piastrellista"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"muratore": 2},
            "pairing_rule": "two-person",
            "prerequisites": [],
            "notes": "Attenzione a non danneggiare il massetto sottostante, se da conservare."
        },
        {
            "code": "DEM_PLUMB",
            "name": "Rimozione vecchi impianti idraulici",
            "synonyms": ["sfilaggio tubi", "rimozione sanitari", "demolizione bagno"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico", "muratore"],
            "unit": "pz", # Spesso a corpo o per punto impianto
            "productivity_per_worker_per_hour": 2, # Punti impianto rimossi
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": [],
            "notes": "Acqua chiusa e impianto scaricato."
        },
        {
            "code": "WALL_DRY_FRAME",
            "name": "Posa struttura cartongesso",
            "synonyms": ["struttura cartongesso", "montanti", "guide cartongesso", "drywall frame"],
            "primary_role": "cartongessista",
            "roles_allowed": ["cartongessista", "muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": [],
            "notes": "Tracciamento a laser o filo."
        },
        {
            "code": "WALL_DRY_PANEL",
            "name": "Posa lastre cartongesso",
            "synonyms": ["chiusura cartongesso", "lastre", "pannelli", "drywall panel"],
            "primary_role": "cartongessista",
            "roles_allowed": ["cartongessista", "muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 15,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["WALL_DRY_FRAME", "ELEC_ROUGH", "PLUMB_ROUGH"],
            "notes": "Verificare passaggio impianti prima di chiudere. Includere eventuale isolante."
        },
        {
            "code": "WALL_DRY_FINISH",
            "name": "Stuccatura e finitura cartongesso",
            "synonyms": ["stuccatura", "rasatura cartongesso", "nastri cartongesso", "finitura drywall"],
            "primary_role": "cartongessista",
            "roles_allowed": ["cartongessista", "imbianchino"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["WALL_DRY_PANEL"],
            "notes": "Richiede tempi di asciugatura tra le mani (solitamente 3 mani)."
        },
        {
            "code": "STRU_SCREED",
            "name": "Realizzazione massetto",
            "synonyms": ["massetto", "sottofondo", "posa massetto", "caldana"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "piastrellista"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 8,
            "min_crew": 2,
            "max_crew": 4,
            "crew_roles": {"muratore": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["ELEC_ROUGH", "PLUMB_ROUGH"],
            "notes": "Rispettare tempi di asciugatura (es. 1 sett/cm) prima di posare legno."
        },
        {
            "code": "PLUMB_FIXTURE",
            "name": "Montaggio sanitari e rubinetteria",
            "synonyms": ["posa sanitari", "wc", "bidet", "lavandino", "montaggio rubinetti", "doccia"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico"],
            "unit": "pz",
            "productivity_per_worker_per_hour": 2, # N. pezzi (sanitari o rubinetti)
            "min_crew": 2,
            "max_crew": 2,
            "crew_roles": {"idraulico": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["PLUMB_ROUGH", "FLOOR_TILE", "WALL_TILE"], # Assumendo ci siano piastrelle a muro
            "notes": "Test di tenuta e scarico."
        },
        {
            "code": "ELEC_FIXTURE",
            "name": "Montaggio frutti e punti luce",
            "synonyms": ["placche", "interruttori", "prese", "montaggio lampadari", "frutti elettrici"],
            "primary_role": "elettricista",
            "roles_allowed": ["elettricista"],
            "unit": "pz",
            "productivity_per_worker_per_hour": 10, # N. punti
            "min_crew": 2,
            "max_crew": 2,
            "crew_roles": {"elettricista": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["ELEC_ROUGH", "PAINT"],
            "notes": "Collegamento e test. Da fare dopo tinteggiatura."
        },
        {
            "code": "HVAC_SPLIT",
            "name": "Installazione climatizzatore split",
            "synonyms": ["condizionatore", "split", "clima", "posa clima", "HVAC"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico", "frigorista", "elettricista"],
            "unit": "pz", # Per ogni split (UI+UE)
            "productivity_per_worker_per_hour": 0.25, # 4 ore per uno split completo
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["ELEC_ROUGH", "PLUMB_ROUGH", "PLASTER"],
            "notes": "Include posa UI, UE, tubi rame, scarico condensa, vuoto e carica."
        },
        {
            "code": "FIN_WINDOW",
            "name": "Posa serramenti / finestre",
            "synonyms": ["finestre", "serramenti", "infissi", "montaggio finestre"],
            "primary_role": "serramentista",
            "roles_allowed": ["serramentista", "falegname", "posatore"],
            "unit": "pz",
            "productivity_per_worker_per_hour": 0.5, # 2 ore a finestra
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"serramentista": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["PLASTER"], # O su controtelaio pre-intonaco
            "notes": "Posa su controtelaio; sigillatura interna ed esterna."
        },
        {
            "code": "FIN_DOOR",
            "name": "Posa porte interne",
            "synonyms": ["porte", "montaggio porte", "telaio", "falsitelaio"],
            "primary_role": "falegname",
            "roles_allowed": ["falegname", "posatore"],
            "unit": "pz",
            "productivity_per_worker_per_hour": 0.7, # Circa 1.5 ore a porta
            "min_crew": 2,
            "max_crew": 2,
            "crew_roles": {"falegname": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["FLOOR_TILE", "PAINT"],
            "notes": "Verifica livelli e squadro vano porta. Da posare dopo pavimenti e pittura."
        },
        {
            "code": "FLOOR_PARQUET",
            "name": "Posa parquet",
            "synonyms": ["parquet", "pavimento in legno", "posa legno"],
            "primary_role": "parquettista",
            "roles_allowed": ["parquettista", "falegname"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 3,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["STRU_SCREED"],
            "notes": "Verifica umidità massetto (max 2%). Posa flottante o incollata."
        },
        {
            "code": "FIN_SKIRTING",
            "name": "Posa battiscopa",
            "synonyms": ["battiscopa", "zoccolino"],
            "primary_role": "parquettista",
            "roles_allowed": ["parquettista", "falegname", "piastrellista", "imbianchino"],
            "unit": "m",
            "productivity_per_worker_per_hour": 20,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["FLOOR_TILE", "FLOOR_PARQUET", "PAINT"],
            "notes": "Tagli a 45° per angoli. Solitamente una delle ultime lavorazioni."
        },
        {
            "code": "WATERPROOF",
            "name": "Impermeabilizzazione (es. doccia)",
            "synonyms": ["guaina", "impermeabilizzazione doccia", "mapelastic", "guaina liquida"],
            "primary_role": "piastrellista",
            "roles_allowed": ["piastrellista", "muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["PLASTER", "STRU_SCREED"],
            "notes": "Applicare prima della posa piastrelle in zone umide."
        },
        {
            "code": "SITE_PREP",
            "name": "Approntamento cantiere e protezioni",
            "synonyms": ["protezioni", "allestimento cantiere", "cartoni", "nylon", "delimitazione area"],
            "primary_role": "operaio",
            "roles_allowed": ["operaio", "muratore"],
            "unit": "m2", # m2 di area protetta
            "productivity_per_worker_per_hour": 50,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": [],
            "notes": "Protezione pavimenti esistenti, parti comuni, ascensori."
        },
        {
            "code": "SITE_WASTE",
            "name": "Carico e trasporto macerie a discarica",
            "synonyms": ["macerie", "rifiuti", "discarica", "smaltimento", "calcinacci"],
            "primary_role": "operaio",
            "roles_allowed": ["operaio", "muratore"],
            "unit": "m3", # m3 di macerie
            "productivity_per_worker_per_hour": 1, # Molto variabile, include carico e trasporto
            "min_crew": 2,
            "max_crew": 3,
            "crew_roles": {"operaio": 2},
            "pairing_rule": "two-person",
            "prerequisites": ["DEM_WALL", "DEM_FLOOR"],
            "notes": "Include oneri di discarica. Necessario formulario FIR."
        },
        {
            "code": "HVAC_FLOOR_HEAT",
            "name": "Posa impianto riscaldamento a pavimento",
            "synonyms": ["riscaldamento a pavimento", "serpentine", "pannelli radianti"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico", "termoidraulico"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["PLUMB_ROUGH"],
            "notes": "Da posare prima del massetto. Include posa collettore."
        },
        {
            "code": "STRU_SCREED_REINF",
            "name": "Realizzazione massetto armato",
            "synonyms": ["massetto armato", "rete elettrosaldata", "massetto con rete"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 6, # Più lento per via della rete
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": ["HVAC_FLOOR_HEAT"], # Spesso posato sopra il radiante
            "notes": "Rispettare tempi di asciugatura."
        },
        {
            "code": "HVAC_BOILER",
            "name": "Installazione caldaia / pompa di calore",
            "synonyms": ["caldaia", "pompa di calore", "scaldabagno", "centrale termica"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico", "termoidraulico", "frigorista"],
            "unit": "pz",
            "productivity_per_worker_per_hour": 0.2, # Circa 5 ore per installazione
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["PLUMB_ROUGH", "ELEC_ROUGH"],
            "notes": "Richiede collaudo e certificazione (es. F-GAS per PdC)."
        },
        {
            "code": "ELEC_PANEL",
            "name": "Installazione e cablaggio quadro elettrico",
            "synonyms": ["quadro elettrico", "centralino", "salvavita", "magnetotermici"],
            "primary_role": "elettricista",
            "roles_allowed": ["elettricista"],
            "unit": "pz",
            "productivity_per_worker_per_hour": 0.25, # Circa 4 ore per un quadro standard
            "min_crew": 1,
            "max_crew": 1,
            "prerequisites": ["ELEC_ROUGH", "PLASTER"],
            "notes": "Dimensionamento in base al carico. Include test differenziali."
        },
        {
            "code": "CEIL_SUSPEND",
            "name": "Realizzazione controsoffitto (lastre)",
            "synonyms": ["controsoffitto", "falso soffitto", "veletta", "botola"],
            "primary_role": "cartongessista",
            "roles_allowed": ["cartongessista", "muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 8, # Include struttura e lastre
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["PLASTER"], # Solitamente dopo intonaci
            "notes": "Includere eventuali botole di ispezione. Stuccatura a parte (vedi WALL_DRY_FINISH)."
        },
        {
            "code": "EXT_EIFS",
            "name": "Posa cappotto termico (EIFS)",
            "synonyms": ["cappotto termico", "isolamento esterno", "ETICS", "rasatura armata"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "facciatista"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 4, # Processo multi-fase
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": [], # Si fa su facciata esistente
            "notes": "Include pannello isolante, tassellatura, rete, rasatura e finitura."
        },
        {
            "code": "ROOF_WATERPROOF",
            "name": "Impermeabilizzazione copertura piana",
            "synonyms": ["guaina tetto", "impermeabilizzazione", "membrana bituminosa", "tetto piano"],
            "primary_role": "impermeabilizzatore",
            "roles_allowed": ["impermeabilizzatore", "muratore", "coperturista"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 15,
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": [], # Su supporto pulito
            "notes": "Posa a fiamma o autoadesiva. Attenzione ai risvolti."
        },
        {
            "code": "ROOF_TILE",
            "name": "Posa manto di copertura (tegole/coppi)",
            "synonyms": ["tegole", "coppi", "copertura tetto", "manto", "tetto falda"],
            "primary_role": "coperturista",
            "roles_allowed": ["coperturista", "muratore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 10,
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": ["ROOF_WATERPROOF"], # O su struttura/isolamento
            "notes": "Include listellatura e fissaggio elementi."
        },
        {
            "code": "SITE_CLEAN_FINAL",
            "name": "Pulizie finali di cantiere",
            "synonyms": ["pulizia finale", "pulizie post-cantiere", "sgrosso"],
            "primary_role": "operaio",
            "roles_allowed": ["operaio", "addetto pulizie"],
            "unit": "m2", # m2 di area da pulire
            "productivity_per_worker_per_hour": 30,
            "min_crew": 1,
            "max_crew": 4,
            "prerequisites": ["FIN_DOOR", "ELEC_FIXTURE", "PLUMB_FIXTURE", "FIN_SKIRTING"],
            "notes": "Rimozione polvere fine, macchie pittura, etichette serramenti."
        },
        {
            "code": "EXT_EXCAV",
            "name": "Scavo di sbancamento o a sezione",
            "synonyms": ["scavo", "sbancamento", "movimento terra", "scavi"],
            "primary_role": "escavatorista",
            "roles_allowed": ["escavatorista", "operaio"],
            "unit": "m3",
            "productivity_per_worker_per_hour": 20, # Molto dipendente dal mezzo meccanico
            "min_crew": 1, # 1 operatore macchina
            "max_crew": 2, # + 1 operaio a terra
            "prerequisites": [],
            "notes": "Tracciamento e quote definite. Sicurezza scavi."
        },
        {
            "code": "STRU_FOUND_FORM",
            "name": "Posa casseforme per fondazioni",
            "synonyms": ["casseforme", "casseratura", "armatura fondazioni"],
            "primary_role": "carpentiere",
            "roles_allowed": ["carpentiere", "muratore"],
            "unit": "m2", # m2 di cassaforma
            "productivity_per_worker_per_hour": 4,
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": ["EXT_EXCAV"],
            "notes": "Pulizia fondo scavo. Utilizzo di disarmante."
        },
        {
            "code": "STRU_FOUND_REBAR",
            "name": "Posa armatura (ferro) per fondazioni",
            "synonyms": ["ferro", "gabbie", "armatura", "posa ferro", "ferraiolo"],
            "primary_role": "ferraiolo",
            "roles_allowed": ["ferraiolo", "carpentiere"],
            "unit": "kg",
            "productivity_per_worker_per_hour": 40,
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": ["STRU_FOUND_FORM"],
            "notes": "Distanziali e legature come da progetto strutturale."
        },
        {
            "code": "STRU_FOUND_POUR",
            "name": "Getto calcestruzzo per fondazioni",
            "synonyms": ["getto", "calcestruzzo", "cls", "betoniera", "pompa cls"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "operaio", "carpentiere"],
            "unit": "m3",
            "productivity_per_worker_per_hour": 5, # Produttività della squadra (non della pompa)
            "min_crew": 3,
            "max_crew": 6,
            "prerequisites": ["STRU_FOUND_REBAR"],
            "notes": "Include vibrazione del calcestruzzo. Rispettare maturazione."
        },
        {
            "code": "STRU_SLAB",
            "name": "Realizzazione solaio (es. laterocemento)",
            "synonyms": ["solaio", "travetti e pignatte", "predalles", "posa solaio"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "carpentiere"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 6,
            "min_crew": 2,
            "max_crew": 5,
            "prerequisites": ["WALL_BUILD"], # O su travi
            "notes": "Include puntellatura, posa travetti, pignatte e rete. Escluso getto."
        },
        {
            "code": "STRU_STEEL",
            "name": "Montaggio carpenteria metallica (travi/colonne)",
            "synonyms": ["travi acciaio", "colonne acciaio", "carpenteria", "struttura metallica", "putrelle"],
            "primary_role": "carpentiere metallico",
            "roles_allowed": ["carpentiere metallico", "fabbro"],
            "unit": "kg", # Spesso misurata in kg o tonnellate
            "productivity_per_worker_per_hour": 100, # kg/ora per operaio
            "min_crew": 2,
            "max_crew": 4,
            "prerequisites": ["STRU_FOUND_POUR"],
            "notes": "Necessario mezzo di sollevamento. Include serraggio bulloni."
        },
        {
            "code": "EXT_SEWER",
            "name": "Posa rete fognaria esterna",
            "synonyms": ["fognatura", "scarichi esterni", "tubi PVC rossi", "allaccio fogna", "pozzetti"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico", "muratore", "escavatorista"],
            "unit": "m",
            "productivity_per_worker_per_hour": 5,
            "min_crew": 2,
            "max_crew": 3,
            "prerequisites": ["EXT_EXCAV"],
            "notes": "Verificare pendenze (min 1-2%) e quote di allaccio. Include posa pozzetti."
        },
        {
            "code": "INS_ACOUSTIC",
            "name": "Posa isolante acustico (pareti/soffitto)",
            "synonyms": ["fonoisolante", "fonoassorbente", "lana di roccia", "isolamento acustico"],
            "primary_role": "cartongessista",
            "roles_allowed": ["cartongessista", "isolatore"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 15,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["WALL_DRY_FRAME"], # Inserito nell'intercapedine
            "notes": "Da inserire prima della chiusura delle lastre di cartongesso."
        },
        {
            "code": "HVAC_VMC",
            "name": "Installazione impianto VMC (Ventilazione Meccanica)",
            "synonyms": ["VMC", "ventilazione meccanica", "ricambio aria", "bocchette vmc", "recuperatore calore"],
            "primary_role": "idraulico",
            "roles_allowed": ["idraulico", "installatore vmc", "cartongessista"],
            "unit": "pz", # Per punto (bocchetta) o a corpo
            "productivity_per_worker_per_hour": 0.5, # 2 ore a punto (include posa tubi flessibili)
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["CEIL_SUSPEND"], # Spesso posata nel controsoffitto
            "notes": "Include posa tubazioni flessibili e bocchette. Macchina a parte."
        },
        {
            "code": "ELEC_ALARM",
            "name": "Installazione impianto allarme",
            "synonyms": ["allarme", "antifurto", "sensori volumetrici", "contatti magnetici", "security"],
            "primary_role": "elettricista",
            "roles_allowed": ["elettricista", "tecnico sicurezza"],
            "unit": "pz", # Per sensore/contatto installato
            "productivity_per_worker_per_hour": 3, # 3 punti/ora
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["ELEC_ROUGH", "PAINT"],
            "notes": "Posa componenti finali. Il cablaggio deve essere predisposto in ELEC_ROUGH."
        },
        {
            "code": "ELEC_DOMOTICS",
            "name": "Installazione e configurazione Domotica",
            "synonyms": ["domotica", "smart home", "automazione", "KNX", "attuatori"],
            "primary_role": "elettricista",
            "roles_allowed": ["elettricista", "tecnico domotica"],
            "unit": "pz", # Per punto/attuatore
            "productivity_per_worker_per_hour": 1.5, # Include la configurazione base
            "min_crew": 1,
            "max_crew": 1,
            "prerequisites": ["ELEC_PANEL", "ELEC_FIXTURE"],
            "notes": "Richiede programmazione software specifica. Sostituisce/integra i frutti."
        },
        {
            "code": "FLOOR_RESIN",
            "name": "Posa pavimento/rivestimento in resina",
            "synonyms": ["resina", "pavimento resina", "spatolato", "rivestimento bagno resina"],
            "primary_role": "posatore resina",
            "roles_allowed": ["posatore resina", "imbianchino"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 3, # Lavoro lento e multi-strato
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["STRU_SCREED"],
            "notes": "Richiede primer, più mani e finitura protettiva. Supporto deve essere perfetto."
        },
        {
            "code": "FIN_RAILING",
            "name": "Montaggio ringhiere / parapetti",
            "synonyms": ["ringhiera", "parapetto", "balaustra", "fabbro", "corrimano"],
            "primary_role": "fabbro",
            "roles_allowed": ["fabbro", "carpentiere metallico", "serramentista"],
            "unit": "m", # Metri lineari
            "productivity_per_worker_per_hour": 3,
            "min_crew": 2,
            "max_crew": 3,
            "prerequisites": ["FLOOR_TILE", "PAINT"], # O su struttura grezza
            "notes": "Fissaggio a pavimento o parete. Include verifica piombo e sicurezza."
        },
        {
            "code": "WALL_COVER",
            "name": "Posa rivestimento murale (Carta da parati / Boiserie)",
            "synonyms": ["carta da parati", "boiserie", "rivestimento legno", "wall covering"],
            "primary_role": "posatore",
            "roles_allowed": ["posatore", "imbianchino", "falegname"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 5,
            "min_crew": 1,
            "max_crew": 2,
            "prerequisites": ["PLASTER", "PAINT"], # O su fondo preparato
            "notes": "Richiede parete perfettamente liscia e preparata (fondo/primer)."
        },
        {
            "code": "EXT_PAVING",
            "name": "Posa pavimentazione esterna (autobloccanti/pietre)",
            "synonyms": ["autobloccanti", "pavimentazione esterna", "porfido", "posa sassi", "vialetto"],
            "primary_role": "muratore",
            "roles_allowed": ["muratore", "piastrellista", "giardiniere"],
            "unit": "m2",
            "productivity_per_worker_per_hour": 6,
            "min_crew": 1,
            "max_crew": 3,
            "prerequisites": ["EXT_EXCAV"], # Richiede sottofondo preparato
            "notes": "Include preparazione letto di posa (sabbia/ghiaietto) e sigillatura."
        }
                                    # --- FINE BLOCCO ---
    ]

    for it in items:
        db["work_catalog"].update_one(
            {"code": it["code"]},
            {"$set": {
                "name": it["name"],
                "synonyms": it["synonyms"],
                "primary_role": it["primary_role"],
                "roles_allowed": it["roles_allowed"],
                "unit": it["unit"],
                "productivity_per_worker_per_hour": it["productivity_per_worker_per_hour"],
                "min_crew": it["min_crew"],
                "max_crew": it["max_crew"],
                "prerequisites": it["prerequisites"],
                "notes": it["notes"],
                "crew_roles": it.get("crew_roles"),
                "pairing_rule": it.get("pairing_rule"),
            }, "$setOnInsert": {"code": it["code"]}},
            upsert=True
        )

    return jsonify({"ok": True, "seeded": len(items)}), 200



@workcat_bp.get("/")
def list_work_catalog():
    db = get_db()
    docs = list(db["work_catalog"].find({}, {"_id": 0}))
    return jsonify({"ok": True, "items": docs}), 200


# --- Additional endpoints ---

# 1) GET endpoint to fetch a single work item by code (case-insensitive)
@workcat_bp.get("/<code>")
def get_work_item(code: str):
    db = get_db()
    code = (code or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    doc = db["work_catalog"].find_one({"code": {"$regex": f"^{code}$", "$options": "i"}}, {"_id": 0})
    if not doc:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "item": doc}), 200


# 2) GET endpoint to search by text/role/unit with limit
@workcat_bp.get("/search")
def search_work_catalog():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip().lower()
    unit = (request.args.get("unit") or "").strip().lower()
    limit = int(request.args.get("limit") or 50)

    filt = {}
    and_terms = []

    if q:
        or_terms = [
            {"code": {"$regex": q, "$options": "i"}},
            {"name": {"$regex": q, "$options": "i"}},
            {"synonyms": {"$elemMatch": {"$regex": q, "$options": "i"}}},
        ]
        and_terms.append({"$or": or_terms})

    if role:
        and_terms.append({"$or": [
            {"primary_role": {"$regex": f"^{role}$", "$options": "i"}},
            {"roles_allowed": {"$elemMatch": {"$regex": f"^{role}$", "$options": "i"}}},
        ]})

    if unit:
        and_terms.append({"unit": {"$regex": f"^{unit}$", "$options": "i"}})

    if and_terms:
        filt = {"$and": and_terms}

    cur = db["work_catalog"].find(filt, {"_id": 0}).sort("name", 1).limit(limit)
    items = list(cur)
    return jsonify({"ok": True, "total": len(items), "items": items}), 200


# 3) GET endpoint to retrieve only crew requirements for a given code
@workcat_bp.get("/crew/<code>")
def get_work_crew_requirements(code: str):
    db = get_db()
    code = (code or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    proj = {"_id": 0, "code": 1, "min_crew": 1, "max_crew": 1, "crew_roles": 1, "pairing_rule": 1}
    doc = db["work_catalog"].find_one({"code": {"$regex": f"^{code}$", "$options": "i"}}, proj)
    if not doc:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "crew": doc}), 200


@workcat_bp.post("/")
def upsert_work_catalog_item():
    """
    Crea/aggiorna una voce.
    Body minimo: { code, name, primary_role, roles_allowed[], unit, productivity_per_worker_per_hour, min_crew, max_crew }
    (tutti contenuti in italiano; etichette/chiavi in inglese)
    """
    db = get_db()
    data = request.get_json(force=True) or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": "code is required"}), 400

    payload = {
        "name": data.get("name"),
        "synonyms": data.get("synonyms") or [],
        "primary_role": data.get("primary_role"),
        "roles_allowed": data.get("roles_allowed") or [],
        "unit": data.get("unit"),
        "productivity_per_worker_per_hour": float(data.get("productivity_per_worker_per_hour") or 0) or 1.0,
        "min_crew": int(data.get("min_crew") or 1),
        "max_crew": int(data.get("max_crew") or 1),
        "prerequisites": data.get("prerequisites") or [],
        "notes": data.get("notes") or "",
        "crew_roles": data.get("crew_roles") or {},
        "pairing_rule": data.get("pairing_rule") or ""
    }

    db["work_catalog"].update_one(
        {"code": code},
        {"$set": payload, "$setOnInsert": {"code": code}},
        upsert=True
    )
    return jsonify({"ok": True, "code": code}), 200


# --- Pricelist endpoints ---

@workcat_bp.post("/seed_pricelist")
def seed_pricelist_from_catalog():
    """
    Crea/aggiorna un listino per regione/città a partire dal catalogo lavori.
    Body (minimo): { "region": "Lombardia", "city": "Milano" }
    Opzionali:    { "materials": {...}, "wages": {...}, "factors": {...} }

    - Se "materials" o "wages" non sono forniti, verranno proposti default intelligenti:
      * wages: ruoli derivati da work_catalog.roles_allowed + valori suggeriti
      * materials: codici minimi usati dalla preview (FLR-001, ADH-001, STU-001, BSK-001, WAS-001)
    - L'upsert è idempotente su (region, city).
    """
    db = get_db()
    payload = request.get_json(force=True) or {}
    region = (payload.get("region") or payload.get("regione") or "").strip()
    city = (payload.get("city") or payload.get("citta") or payload.get("città") or "").strip()
    if not region:
        return jsonify({"error": "region is required"}), 400

    # 1) Ruoli presenti nel catalogo (per proporre un wages base)
    roles = set()
    for doc in db["work_catalog"].find({}, {"_id": 0, "roles_allowed": 1, "primary_role": 1}):
        for r in (doc.get("roles_allowed") or []):
            if r: roles.add(r.lower())
        pr = doc.get("primary_role")
        if pr: roles.add(pr.lower())

    # 2) Wages proposti (se non forniti nel body)
    suggested_wages = {
        "muratore": 25.0,
        "piastrellista": 28.0,
        "imbianchino": 24.0,
        "cartongessista": 26.0,
        "idraulico": 30.0,
        "elettricista": 30.0,
        "manovale": 22.0,
        "falegname": 30.0,
        "serramentista": 30.0,
        "parquettista": 30.0,
        "posatore": 26.0,
        "posatore resina": 32.0,
        "impermeabilizzatore": 29.0,
        "facciatista": 28.0,
        "carpentiere": 27.0,
        "carpentiere metallico": 28.0,
        "fabbro": 28.0,
        "escavatorista": 26.0,
        "termoidraulico": 32.0,
        "frigorista": 32.0,
        "isolatore": 25.0,
        "installatore vmc": 30.0,
    }
    # limita ai ruoli effettivamente presenti
    base_wages = {r: suggested_wages.get(r, 25.0) for r in roles}

    # 3) Materiali minimi usati dalla preview (Punto 2)
    base_materials = {
        "FLR-001": 19.50,  # Piastrelle gres 60x60 €/m2
        "ADH-001": 0.00,   # Colla €/kg (a volte inclusa o molto variabile)
        "STU-001": 1.10,   # Stucco €/kg
        "BSK-001": 6.50,   # Battiscopa €/m
        "WAS-001": 3.00,   # Sacco macerie €/pz
        "EL-PL": 18.00,           # Materiali per 1 punto luce (€/pz)
        "EL-PP": 16.50,           # Materiali per 1 punto presa (€/pz)
        "IDR-BAGNO-PACK": 220.00, # Kit impianto idrico bagno (€/pz)

        # --- Elettrico (materiali generici) ---
        "EL-QUADRO-STD": 180.00,     # Quadro elettrico standard €/pz
        "EL-CAVO-3G1.5": 0.65,      # Cavo 3G1.5 €/m
        "EL-CAVO-3G2.5": 0.95,      # Cavo 3G2.5 €/m
        "EL-TUBO-20": 0.45,         # Tubu corrugato Ø20 €/m
        "EL-SCATOLA-503": 1.20,     # Scatola incasso 503 €/pz
        "EL-SCATOLA-DER": 3.50,     # Scatola derivazione €/pz
        "EL-SALVAVITA-25A": 28.00,  # Differenziale 25A €/pz
        "EL-MT-16A": 12.00,         # Magnetotermico 16A €/pz
        "EL-CANALINA-60x40": 3.20,  # Canalina 60x40 €/m

        # --- Idraulico (materiali generici) ---
        "IDR-TUBO-PPR-20": 1.10,    # Tubo PPR Ø20 €/m
        "IDR-TUBO-PPR-25": 1.50,    # Tubo PPR Ø25 €/m
        "IDR-RACCORDI-PACK": 4.00,  # Kit raccordi €/pz
        "IDR-SCARICO-HT-50": 3.20,  # Tubo scarico HT Ø50 €/m
        "IDR-COLLETTORE": 55.00,    # Collettore €/pz

        # --- Cartongesso / Isolanti ---
        "DRY-LASTRA-12_5": 6.50,    # Lastra 12.5 mm €/m2
        "DRY-STUCCO": 1.90,         # Stucco cartongesso €/kg
        "DRY-PROFILI-ML": 2.80,     # Profili/guide €/m
        "INS-LANA-ROCCIA-M2": 4.50, # Lana di roccia €/m2

        # --- Pitture / Protezioni ---
        "PNT-IDROPITTURA-LT": 2.80,     # Idropittura lavabile €/L
        "PNT-NASTRI-TELI-PACK": 5.00,   # Nastri/teli protezione €/pz

        # --- Impermeabilizzazioni / Smaltimenti ---
        "WATER-KIT-BOXDOC": 35.00,  # Kit impermeabilizzazione box doccia €/m2 o a corpo
        "DISP-SCARICO-M3": 35.00,   # Costo smaltimento in discarica €/m3
    }

    # 4) Fattori territoriali di esempio (coeff moltiplicativi)
    base_factors = {
        "historic_center": 1.05,
        "remote": 1.08,
    }

    # Usa ciò che arriva dal body se presente, altrimenti i default
    materials = dict(payload.get("materials") or base_materials)
    wages = dict(payload.get("wages") or base_wages)
    factors = dict(payload.get("factors") or base_factors)

    # 5) Upsert idempotente del listino
    key = {"region": region, "city": city}
    update = {
        "$set": {
            "region": region,
            "city": city,
            "materials": materials,
            "wages": wages,
            "factors": factors,
            "updated_at": datetime.utcnow(),
        },
        "$setOnInsert": {"created_at": datetime.utcnow()}
    }
    db["pricelists"].update_one(key, update, upsert=True)

    return jsonify({"ok": True, "region": region, "city": city, "materials": len(materials), "wages": len(wages)}), 200


@workcat_bp.get("/pricelist")
def get_pricelist():
    """Ritorna il listino per (region, city) con fallback per sola regione.
    Query: ?region=Lombardia&city=Milano
    """
    db = get_db()
    region = (request.args.get("region") or request.args.get("regione") or "").strip()
    city = (request.args.get("city") or request.args.get("citta") or request.args.get("città") or "").strip()
    if not region and not city:
        return jsonify({"error": "region or city is required"}), 400

    doc = None
    if region and city:
        doc = db["pricelists"].find_one({"region": {"$regex": f"^{region}$", "$options": "i"},
                                          "city": {"$regex": f"^{city}$", "$options": "i"}}, {"_id": 0})
    if not doc and region:
        doc = db["pricelists"].find_one({"region": {"$regex": f"^{region}$", "$options": "i"},
                                          "$or": [{"city": {"$exists": False}}, {"city": {"$in": [None, ""]}}]}, {"_id": 0})
    if not doc and city:
        doc = db["pricelists"].find_one({"city": {"$regex": f"^{city}$", "$options": "i"}}, {"_id": 0})

    return jsonify({"ok": True, "pricelist": doc}), 200

@workcat_bp.post("/pricelist/upsert_codes")
def upsert_pricelist_codes():
    """Upserta materiali/ruoli/fattori in un listino per (region, city).
    Body:
    {
      "region": "Lombardia",          # opzionale se city è fornita ma consigliato
      "city": "",                     # stringa vuota = listino regionale
      "materials": {"EL-PL": 18.0, "EL-PP": 16.5, "IDR-BAGNO-PACK": 220},
      "wages": {"elettricista": 32.0, "idraulico": 32.0},
      "factors": {"historic_center": 1.05}
    }
    """
    db = get_db()
    data = request.get_json(force=True) or {}
    region = (data.get("region") or data.get("regione") or "").strip()
    city = (data.get("city") or data.get("citta") or data.get("città") or "").strip()

    if not region and not city:
        return jsonify({"ok": False, "error": "region or city required"}), 422

    filt = {}
    if region:
        filt["region"] = {"$regex": f"^{region}$", "$options": "i"}
    if city != "":
        # city stringa vuota indica listino regionale → non filtriamo per city
        filt["city"] = {"$regex": f"^{city}$", "$options": "i"}
    if not filt:
        # fallback: consenti upsert su city-only se region non fornita
        filt["city"] = {"$regex": f"^{city}$", "$options": "i"}

    update = {"$set": {}}
    materials = data.get("materials") or {}
    wages = data.get("wages") or {}
    factors = data.get("factors") or {}

    for k, v in materials.items():
        try:
            update["$set"][f"materials.{k}"] = float(v)
        except Exception:
            pass
    for k, v in wages.items():
        try:
            update["$set"][f"wages.{k}"] = float(v)
        except Exception:
            pass
    for k, v in factors.items():
        try:
            update["$set"][f"factors.{k}"] = float(v)
        except Exception:
            pass

    if not update["$set"]:
        return jsonify({"ok": False, "error": "nothing to update"}), 400

    set_on_insert = {}
    if region: set_on_insert["region"] = region
    if city != "": set_on_insert["city"] = city

    update["$set"]["updated_at"] = datetime.utcnow()
    if set_on_insert:
        update["$setOnInsert"] = {"created_at": datetime.utcnow(), **set_on_insert}

    res = db["pricelists"].update_one(filt, update, upsert=True)
    return jsonify({
        "ok": True,
        "matched": res.matched_count,
        "modified": res.modified_count,
        "upserted_id": str(res.upserted_id) if res.upserted_id else None
    }), 200


@workcat_bp.post("/seed_pricelist_italy10")
def seed_pricelist_italy10():
    """
    Crea/aggiorna 10 prezzari regionali (senza city) con moltiplicatori macro-area.
    Regioni: Lombardia, Lazio, Campania, Sicilia, Veneto, Emilia-Romagna, Piemonte, Puglia, Toscana, Calabria.
    Wages/materials derivano dal catalogo + valori di base, poi moltiplicati per regione.
    """
    db = get_db()

    # 1) Ruoli effettivi dal catalogo
    roles = set()
    for doc in db["work_catalog"].find({}, {"_id": 0, "roles_allowed": 1, "primary_role": 1}):
        for r in (doc.get("roles_allowed") or []):
            if r: roles.add(r.lower())
        pr = doc.get("primary_role")
        if pr: roles.add(pr.lower())

    # 2) Wages base (€/h) suggeriti — verranno moltiplicati per regione
    base_wages_ref = {
        "muratore": 25.0,
        "piastrellista": 28.0,
        "imbianchino": 24.0,
        "cartongessista": 26.0,
        "idraulico": 30.0,
        "elettricista": 30.0,
        "manovale": 22.0,
        "falegname": 30.0,
        "serramentista": 30.0,
        "parquettista": 30.0,
        "posatore": 26.0,
        "posatore resina": 32.0,
        "impermeabilizzatore": 29.0,
        "facciatista": 28.0,
        "carpentiere": 27.0,
        "carpentiere metallico": 28.0,
        "fabbro": 28.0,
        "escavatorista": 26.0,
        "termoidraulico": 32.0,
        "frigorista": 32.0,
        "isolatore": 25.0,
        "installatore vmc": 30.0,
    }
    base_wages = {r: base_wages_ref.get(r, 25.0) for r in roles}

    # 3) Materiali minimi usati nel preview
    base_materials = {
        "FLR-001": 19.50,  # €/m2 piastrelle gres 60x60
        "ADH-001": 0.00,   # €/kg colla (variabile)
        "STU-001": 1.10,   # €/kg stucco
        "BSK-001": 6.50,   # €/m battiscopa
        "WAS-001": 3.00,   # €/pz sacco macerie
        "EL-PL": 18.00,           # € per punto luce
        "EL-PP": 16.50,           # € per punto presa
        "IDR-BAGNO-PACK": 220.00, # € per kit impianto idrico bagno

        # --- Elettrico (materiali generici) ---
        "EL-QUADRO-STD": 180.00,     # Quadro elettrico standard €/pz
        "EL-CAVO-3G1.5": 0.65,      # Cavo 3G1.5 €/m
        "EL-CAVO-3G2.5": 0.95,      # Cavo 3G2.5 €/m
        "EL-TUBO-20": 0.45,         # Tubu corrugato Ø20 €/m
        "EL-SCATOLA-503": 1.20,     # Scatola incasso 503 €/pz
        "EL-SCATOLA-DER": 3.50,     # Scatola derivazione €/pz
        "EL-SALVAVITA-25A": 28.00,  # Differenziale 25A €/pz
        "EL-MT-16A": 12.00,         # Magnetotermico 16A €/pz
        "EL-CANALINA-60x40": 3.20,  # Canalina 60x40 €/m

        # --- Idraulico (materiali generici) ---
        "IDR-TUBO-PPR-20": 1.10,    # Tubo PPR Ø20 €/m
        "IDR-TUBO-PPR-25": 1.50,    # Tubo PPR Ø25 €/m
        "IDR-RACCORDI-PACK": 4.00,  # Kit raccordi €/pz
        "IDR-SCARICO-HT-50": 3.20,  # Tubo scarico HT Ø50 €/m
        "IDR-COLLETTORE": 55.00,    # Collettore €/pz

        # --- Cartongesso / Isolanti ---
        "DRY-LASTRA-12_5": 6.50,    # Lastra 12.5 mm €/m2
        "DRY-STUCCO": 1.90,         # Stucco cartongesso €/kg
        "DRY-PROFILI-ML": 2.80,     # Profili/guide €/m
        "INS-LANA-ROCCIA-M2": 4.50, # Lana di roccia €/m2

        # --- Pitture / Protezioni ---
        "PNT-IDROPITTURA-LT": 2.80,     # Idropittura lavabile €/L
        "PNT-NASTRI-TELI-PACK": 5.00,   # Nastri/teli protezione €/pz

        # --- Impermeabilizzazioni / Smaltimenti ---
        "WATER-KIT-BOXDOC": 35.00,  # Kit impermeabilizzazione box doccia €/m2 o a corpo
        "DISP-SCARICO-M3": 35.00,   # Costo smaltimento in discarica €/m3
    }

    # 4) Fattori standard
    base_factors = {
        "historic_center": 1.05,
        "remote": 1.08,
    }

    # 5) 10 Regioni + moltiplicatori macro-area (indicativi)
    regions = {
        "Lombardia": 1.08,
        "Lazio": 1.05,
        "Veneto": 1.04,
        "Emilia-Romagna": 1.04,
        "Piemonte": 1.03,
        "Toscana": 1.04,
        "Campania": 0.96,
        "Puglia": 0.94,
        "Sicilia": 0.93,
        "Calabria": 0.92,
    }

    seeded = []
    from datetime import datetime
    for region, mult in regions.items():
        wages_r = {k: round(v * mult, 2) for k, v in base_wages.items()}
        materials_r = {k: round(v * mult, 2) for k, v in base_materials.items()}
        key = {"region": region, "city": ""}

        update = {
            "$set": {
                "region": region,
                "city": "",
                "materials": materials_r,
                "wages": wages_r,
                "factors": dict(base_factors),
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {"created_at": datetime.utcnow()}
        }
        db["pricelists"].update_one(key, update, upsert=True)
        seeded.append(region)

    return jsonify({"ok": True, "seeded_regions": seeded, "count": len(seeded)}), 200