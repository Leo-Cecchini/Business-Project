# test_projects_refactoring.py
import requests
import json
import random
import string
import io

BASE_URL = "http://localhost:5001"  # Assicurati che la porta sia corretta

def get_random_string(length=6):
    return ''.join(random.choices(string.ascii_letters, k=length))

def print_res(name, r):
    if r.status_code in [200, 201]:
        print(f"✅ {name}: OK ({r.status_code})")
    else:
        print(f"❌ {name}: ERROR {r.status_code}")
        try:
            print(f"   Response: {r.json()}")
        except:
            print(f"   Response: {r.text}")

def run_tests():
    print("=== TEST REFACTORING PROJECTS ===")

    # 1. CREAZIONE (Create)
    # ---------------------------------------------------------
    new_name = f"Cantiere Test {get_random_string()}"
    city = "Milano"
    payload = {
        "name": new_name,
        "status": "Preventivo",
        "city": city,
        "project_address": "Via Roma 1",
        "start_date_estimated": "2025-01-01"
    }
    
    print(f"\n🔹 Creazione progetto: {new_name}")
    r = requests.post(f"{BASE_URL}/api/projects", json=payload)
    print_res("Create Project", r)
    
    if r.status_code != 201:
        print("STOP: Impossibile creare progetto.")
        return

    data = r.json()
    p_id = data.get("project", {}).get("id")
    print(f"   ID creato: {p_id}")

    # 2. LETTURA (Read & List)
    # ---------------------------------------------------------
    print(f"\n🔹 Verifica Lista e Paginazione")
    # Testiamo filtri (status) e paginazione
    r = requests.get(f"{BASE_URL}/api/projects?status=Preventivo&page=1&per_page=10")
    print_res("List Projects (Filtered)", r)
    if r.status_code == 200:
        d = r.json()
        total = d.get('total')
        print(f"   Totale trovati: {total}")
        
        # Verifica che il nostro progetto sia nella lista
        found = any(p['id'] == p_id for p in d.get('projects', []))
        if found:
            print("   ✅ Progetto appena creato trovato nella lista")
        else:
            print("   ⚠️ Progetto creato NON trovato nella prima pagina (potrebbe essere corretto se hai molti progetti)")

    print(f"\n🔹 Verifica Dettaglio Singolo")
    r = requests.get(f"{BASE_URL}/api/projects/{p_id}")
    print_res("Get Project", r)

    # 3. STATISTICHE
    # ---------------------------------------------------------
    print(f"\n🔹 Statistiche Progetti")
    r = requests.get(f"{BASE_URL}/api/projects/stats")
    print_res("Project Stats", r)
    if r.status_code == 200:
        stats = r.json()
        print(f"   Totale: {stats.get('total')}")
        print(f"   Per stato: {stats.get('by_status')}")

    # 4. TOGGLE STATUS
    # ---------------------------------------------------------
    print(f"\n🔹 Cambio Stato (Toggle)")
    r = requests.post(f"{BASE_URL}/api/projects/{p_id}/status")
    print_res("Toggle Status", r)
    if r.status_code == 200:
        new_status = r.json().get("project", {}).get("status")
        print(f"   Nuovo stato: {new_status} (dovrebbe essere 'Confermato')")

    # 5. DOCUMENTI (Upload & List)
    # ---------------------------------------------------------
    print(f"\n🔹 Upload Documento (Mock)")
    # Creiamo un file finto in memoria
    file_content = b"Contenuto di prova del capitolato."
    files = {
        'file': ('capitolato_test.txt', io.BytesIO(file_content), 'text/plain')
    }
    r = requests.post(f"{BASE_URL}/api/projects/{p_id}/documents", files=files)
    print_res("Upload Document", r)

    print(f"\n🔹 Lista Documenti")
    r = requests.get(f"{BASE_URL}/api/projects/{p_id}/documents")
    print_res("List Documents", r)
    if r.status_code == 200:
        docs = r.json().get("documents", [])
        print(f"   Documenti trovati: {len(docs)}")
        if any(d['name'] == 'capitolato_test.txt' for d in docs):
            print("   ✅ File caricato presente nella lista")

    # 6. ELIMINAZIONE (Delete)
    # ---------------------------------------------------------
    print(f"\n🔹 Eliminazione Progetto")
    r = requests.delete(f"{BASE_URL}/api/projects/{p_id}")
    print_res("Delete Project", r)

    # Verifica finale
    r = requests.get(f"{BASE_URL}/api/projects/{p_id}")
    if r.status_code == 404:
        print("✅ Verifica eliminazione: OK (404)")
    else:
        print("❌ Verifica eliminazione: FALLITA (Progetto esiste ancora)")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()