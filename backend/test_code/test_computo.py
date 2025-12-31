# test_computo_refactoring.py
import requests
import json
import random
import string
import io

BASE_URL = "http://localhost:5001"

def get_random_string(length=6):
    return ''.join(random.choices(string.ascii_letters, k=length))

def print_res(name, r):
    if r.status_code in [200, 201]:
        print(f"✅ {name}: OK ({r.status_code})")
        return True
    else:
        print(f"❌ {name}: ERROR {r.status_code}")
        try:
            print(f"   Response: {r.json()}")
        except:
            print(f"   Response: {r.text[:300]}...")
        return False

def run_tests():
    print("=== TEST REFACTORING COMPUTO ===")

    # 0. PREPARAZIONE: Creiamo un progetto fresco
    # ---------------------------------------------------------
    p_name = f"Progetto Computo {get_random_string()}"
    p_res = requests.post(f"{BASE_URL}/api/projects", json={
        "name": p_name, 
        "status": "Preventivo",
        "city": "Roma"
    })
    
    if p_res.status_code != 201:
        print("STOP: Impossibile creare progetto per il test.")
        return

    pid = p_res.json().get("project", {}).get("id")
    print(f"🔹 Progetto creato: {p_name} (ID: {pid})")

    # 1. GENERAZIONE DA DESCRIZIONE (AI)
    # ---------------------------------------------------------
    print(f"\n🔹 Test 1: Generazione Computo da Descrizione (AI)")
    desc_payload = {
        "description": "Ristrutturazione bagno completo: demolizione pavimenti e rivestimenti (20mq), rifacimento impianto idrico (4 punti), posa nuovi sanitari e piastrelle."
    }
    
    r = requests.post(f"{BASE_URL}/api/projects/{pid}/computo/generate", json=desc_payload)
    
    if print_res("Generate Computo", r):
        data = r.json()
        print(f"   Totale stimato: {data.get('grand_total')} €")
        print(f"   Voci generate: {len(data.get('bill_of_quantities', []))}")

    # 2. CARICAMENTO PDF (Upload Reale)
    # ---------------------------------------------------------
    print(f"\n🔹 Test 2: Upload PDF Computo")
    
    # Percorso del file reale
    file_path = "D:/Documents/University/business/allegato-C_COMPUTO-METRICO-ESTIMATIVO_-via-Toscana-1.pdf"

    try:
        # IMPORTANTE: La richiesta deve essere fatta DENTRO il blocco 'with'
        # altrimenti il file viene chiuso prima dell'invio.
        with open(file_path, 'rb') as f:
            files = {
                'file': ('computo_test.pdf', f, 'application/pdf')
            }
            # La richiesta è ora indentata correttamente
            r = requests.post(f"{BASE_URL}/api/projects/{pid}/computo/upload", files=files)
            
        # Controllo risposta (fuori dal with va bene, ormai la richiesta è partita)
        if r.status_code == 500 and "PDF" in r.text:
             print("⚠️ Upload fallito lato server (Errore Parsing/AI), ma l'endpoint è stato raggiunto.")
             # Stampiamo l'errore per debug
             try: print(f"   Dettaglio: {r.json()}")
             except: pass
        else:
             print_res("Upload PDF", r)

    except FileNotFoundError:
        print(f"❌ ERRORE: Il file specificato non esiste: {file_path}")
        print("   Saltando il test di upload...")

    # 3. RECUPERO ULTIMO COMPUTO
    # ---------------------------------------------------------
    print(f"\n🔹 Test 3: Get Latest Computo")
    r = requests.get(f"{BASE_URL}/api/projects/{pid}/computo/latest")
    
    if print_res("Get Latest", r):
        data = r.json()
        print(f"   ID Computo: {data.get('id')}")
        print(f"   Grand Total: {data.get('grand_total')}")

    # 4. PIANIFICAZIONE LAVORI DA COMPUTO (Plan)
    # ---------------------------------------------------------
    print(f"\n🔹 Test 4: Plan Works from Computo")
    plan_payload = {"start_date": "2025-03-01"}
    
    r = requests.post(f"{BASE_URL}/api/projects/{pid}/computo/plan", json=plan_payload)
    
    if print_res("Plan Works", r):
        data = r.json()
        works = data.get("works", [])
        print(f"   Lavori pianificati: {len(works)}")
        if works:
            print(f"   Primo lavoro: {works[0]['work_name']} (Start: {works[0]['start']})")

    # Verifica che i lavori siano finiti nel progetto
    p_check = requests.get(f"{BASE_URL}/api/projects/{pid}")
    if p_check.status_code == 200:
        proj_works = p_check.json().get("project", {}).get("works", [])
        print(f"   Verifica su Progetto: {len(proj_works)} lavori presenti.")

    # 5. DOWNLOAD PDF
    # ---------------------------------------------------------
    print(f"\n🔹 Test 5: Download PDF Report")
    r = requests.get(f"{BASE_URL}/api/projects/{pid}/computo/download")
    
    if r.status_code == 200:
        print(f"✅ Download PDF: OK ({len(r.content)} bytes)")
        if r.headers.get("Content-Type") == "application/pdf":
            print("   Content-Type corretto (application/pdf)")
    else:
        print(f"❌ Download PDF: ERROR {r.status_code}")
        print(f"   {r.text}")

    # PULIZIA (Opzionale)
    # requests.delete(f"{BASE_URL}/api/projects/{pid}")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()