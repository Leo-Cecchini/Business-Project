# test_materials_refactoring.py
import requests
import json
import random
import string

BASE_URL = "http://localhost:5001"  # Assicurati che la porta sia corretta

def get_random_string(length=4):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

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
    print("=== TEST REFACTORING MATERIALS ===")

    # Dati di prova
    sku_test = f"TEST-MAT-{get_random_string()}"
    name_test = "Intonaco Premiscelato Test"
    
    # 1. CREAZIONE (Upsert - Nuovo)
    # ---------------------------------------------------------
    payload = {
        "sku": sku_test,
        "name": name_test,
        "unit": "kg",
        "category": "Edilizia",
        "subcategory": "Malte",
        "unit_price_eur_2025": 0.45,
        "stock_qty": 1000
    }
    
    print(f"\n🔹 Creazione Materiale (Upsert New): {sku_test}")
    r = requests.post(f"{BASE_URL}/api/materials/", json=payload)
    print_res("Create Material", r)
    
    if r.status_code != 201:
        print("STOP: Impossibile creare materiale.")
        return

    m_id = r.json().get("id")
    print(f"   ID creato: {m_id}")

    # 2. AGGIORNAMENTO (Upsert - Esistente)
    # ---------------------------------------------------------
    print(f"\n🔹 Aggiornamento Materiale (Upsert Existing)")
    # Cambiamo prezzo e nome mantenendo lo stesso SKU
    payload["name"] = f"{name_test} (Updated)"
    payload["unit_price_eur_2025"] = 0.50
    
    r = requests.post(f"{BASE_URL}/api/materials/", json=payload)
    print_res("Update Material", r)
    
    if r.status_code == 201:
        updated_id = r.json().get("id")
        if updated_id == m_id:
            print("   ✅ ID mantenuto corretto (Upsert ok)")
        else:
            print(f"   ⚠️ ATTENZIONE: ID cambiato? {m_id} -> {updated_id}")

    # 3. DETTAGLIO
    # ---------------------------------------------------------
    print(f"\n🔹 Verifica Dettaglio")
    r = requests.get(f"{BASE_URL}/api/materials/{m_id}")
    print_res("Get Material", r)
    if r.status_code == 200:
        d = r.json()
        print(f"   Nome: {d.get('name')}")
        print(f"   Prezzo: {d.get('unit_price_eur_2025')}")

    # 4. LISTA / RICERCA
    # ---------------------------------------------------------
    print(f"\n🔹 Verifica Lista e Ricerca")
    # Cerchiamo per parte del nome
    q_txt = "Intonaco"
    r = requests.get(f"{BASE_URL}/api/materials/?q={q_txt}&limit=10")
    print_res(f"Search '{q_txt}'", r)
    if r.status_code == 200:
        items = r.json()
        print(f"   Trovati: {len(items)}")
        found = any(i['sku'] == sku_test for i in items)
        if found:
            print("   ✅ Materiale test trovato nella ricerca")
        else:
            print("   ⚠️ Materiale test NON trovato (possibile ritardo indice o filtro errato)")

    # 5. LOOKUP SPECIFICO (Best Match)
    # ---------------------------------------------------------
    print(f"\n🔹 Verifica Lookup (Best Match)")
    # Simuliamo la chat che cerca "intonaco test" in kg
    r = requests.get(f"{BASE_URL}/api/materials/lookup?name=Intonaco&unit=kg")
    print_res("Lookup", r)
    if r.status_code == 200:
        d = r.json()
        if d.get("found"):
            print(f"   ✅ Match trovato: {d.get('material', {}).get('name')}")
            print(f"   Score matches: {d.get('matches')}")
        else:
            print("   ⚠️ Nessun match trovato")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()