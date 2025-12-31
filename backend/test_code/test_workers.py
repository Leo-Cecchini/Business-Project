# test_workers_refactoring.py
import requests
import json
import random
import string

BASE_URL = "http://localhost:5001"  # Cambia porta se necessario

def get_random_string(length=6):
    return ''.join(random.choices(string.ascii_letters, k=length))

def print_res(name, r):
    if r.status_code in [200, 201]:
        print(f"✅ {name}: OK ({r.status_code})")
    else:
        print(f"❌ {name}: ERROR {r.status_code}")
        print(f"   Response: {r.text}")

def run_tests():
    print("=== TEST REFACTORING WORKERS ===")

    # 1. CREAZIONE (Create)
    # ---------------------------------------------------------
    new_name = f"TestWorker_{get_random_string()}"
    payload = {
        "name": new_name,
        "role": "elettricista",
        "home_city": "Milano",
        "hourly_rate": 35.0,
        "available": True,
        "skills": ["cablaggio", "quadri"]
    }
    print(f"\n🔹 Creazione worker: {new_name}")
    r = requests.post(f"{BASE_URL}/api/workers", json=payload)
    print_res("Create Worker", r)
    
    if r.status_code != 201:
        print("STOP: Impossibile creare worker per i test successivi.")
        return

    data = r.json()
    w_id = data.get("worker", {}).get("id")
    print(f"   ID creato: {w_id}")

    # 2. LETTURA (Read & List)
    # ---------------------------------------------------------
    print(f"\n🔹 Verifica Lista e Paginazione")
    r = requests.get(f"{BASE_URL}/api/workers?page=1&per_page=10&role=elettricista")
    print_res("List Workers (Filtered)", r)
    if r.status_code == 200:
        d = r.json()
        print(f"   Totale trovati: {d.get('total')}")
        print(f"   Items in pagina: {len(d.get('workers', []))}")

    print(f"\n🔹 Verifica Dettaglio Singolo")
    r = requests.get(f"{BASE_URL}/api/workers/{w_id}")
    print_res("Get Worker", r)

    # 3. AGGIORNAMENTO (Update & Patch)
    # ---------------------------------------------------------
    print(f"\n🔹 Aggiornamento (PUT)")
    update_payload = {"hourly_rate": 40.0, "home_city": "Torino"}
    r = requests.put(f"{BASE_URL}/api/workers/{w_id}", json=update_payload)
    print_res("Update Worker", r)
    
    print(f"\n🔹 Toggle Disponibilità (PATCH)")
    r = requests.patch(f"{BASE_URL}/api/workers/{w_id}/availability")
    print_res("Toggle Availability", r)
    if r.status_code == 200:
        new_avail = r.json().get("worker", {}).get("available")
        print(f"   Nuovo stato available: {new_avail}")

    # 4. STATISTICHE (Aggregazioni)
    # ---------------------------------------------------------
    print(f"\n🔹 Test Stats & Roles")
    r = requests.get(f"{BASE_URL}/api/workers/stats")
    print_res("Stats", r)
    
    r = requests.get(f"{BASE_URL}/api/workers/roles")
    print_res("Roles List", r)

    # 5. ELIMINAZIONE (Delete)
    # ---------------------------------------------------------
    print(f"\n🔹 Eliminazione")
    # Primo tentativo senza conferma (dovrebbe fallire o richiedere confirm)
    r = requests.delete(f"{BASE_URL}/api/workers/{w_id}") 
    if r.status_code == 400:
         print("✅ Delete check (no confirm): OK (400 as expected)")
    else:
         print(f"⚠️ Delete check (no confirm): Unexpected {r.status_code}")

    # Secondo tentativo con conferma
    r = requests.delete(f"{BASE_URL}/api/workers/{w_id}?confirm=true")
    print_res("Delete Worker (Confirmed)", r)

    # Verifica finale
    r = requests.get(f"{BASE_URL}/api/workers/{w_id}")
    if r.status_code == 404:
        print("✅ Verifica eliminazione: OK (404)")
    else:
        print("❌ Verifica eliminazione: FALLITA (Worker esiste ancora)")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()