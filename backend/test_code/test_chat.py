# test_refactoring.py
import requests
import json
import sys

BASE_URL = "http://localhost:5001"  # Cambia la porta se necessario

def test_chat(message, project_id=None, expected_intent_db=None, expected_text_part=None):
    url = f"{BASE_URL}/api/chat"
    payload = {"message": message}
    if project_id:
        payload["project_id"] = project_id
    
    print(f"🔹 Testing: '{message}' ...", end=" ")
    try:
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            print(f"❌ Error {r.status_code}: {r.text}")
            return False
        
        data = r.json()
        
        # Verifica Intent DB
        intent = data.get("intent")
        if expected_intent_db and intent != expected_intent_db:
             print(f"⚠️ Warning Intent: Got {intent}, expected {expected_intent_db}")
             # Non falliamo il test per questo, ma lo segnaliamo
        
        # Verifica Contenuto Risposta
        ans = data.get("answer") or data.get("reply") or ""
        if expected_text_part and expected_text_part.lower() not in ans.lower():
            print(f"❌ Failed Content match. Got: '{ans}'")
            return False
            
        print("✅ OK")
        return True
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def run_tests():
    print("=== VERIFICA REFACTORING CHAT ===")
    
    # 1. Saluto (Short circuit)
    test_chat("Ciao", expected_intent_db="GREETING", expected_text_part="Ciao")
    
    # 2. Skills Lavoratori (DB-First)
    test_chat("Quanti operai ci sono?", expected_intent_db="HEADCOUNT", expected_text_part="Totale")
    test_chat("Che lavoro fa Mario?", expected_intent_db="ROLE_LOOKUP")
    test_chat("Lista elettricisti", expected_intent_db="ROLE_LIST")
    test_chat("Quanti muratori disponibili in Lazio?", expected_intent_db="WORKERS_FREE_FILTERED", expected_text_part="Lazio")
    
    # 3. Skills Progetti
    test_chat("Quanti cantieri attivi?", expected_intent_db="PROJECT_COUNTS")
    test_chat("Ultimi 3 cantieri", expected_intent_db="RECENT_PROJECTS")
    
    # 4. Materiali (Service)
    test_chat("Quanto costa il gres 60x60?", expected_intent_db="MATERIAL_PRICE", expected_text_part="gres")
    
    # 5. Stima (LLM + EstimateService)
    test_chat("Fammi una stima per posa pavimento 100 mq gres", expected_text_part="stima")
    
    # 6. Action (richiede un project_id valido nel tuo DB, metti un ID reale se vuoi testarlo)
    # test_chat("Aggiungi posa pavimento 50 mq", project_id="P-1001", expected_intent_db="ACTION_ADD_WORK")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()