# test_catalog_refactoring.py
import requests
import json

BASE_URL = "http://localhost:5001"

def run_tests():
    print("=== TEST REFACTORING CATALOGO ===")
    
    # 1. Crea voce manuale (sostituisce il seed)
    print("\n🔹 Test 1: Upsert Voce Manuale")
    item_payload = {
        "code": "TEST_ITEM_001",
        "name": "Lavorazione Test Manuale",
        "unit": "m2",
        "primary_role": "muratore",
        "productivity_per_worker_per_hour": 5.0,
        "min_crew": 1
    }
    r = requests.post(f"{BASE_URL}/api/catalog/works/", json=item_payload)
    if r.status_code == 200:
        print("✅ Upsert OK")
    else:
        print(f"❌ Upsert Failed: {r.text}")

    # 2. Ricerca
    print("\n🔹 Test 2: Ricerca")
    r = requests.get(f"{BASE_URL}/api/catalog/works/search?q=Test")
    if r.status_code == 200:
        items = r.json().get("items", [])
        print(f"   Trovati: {len(items)}")
        if any(x["code"] == "TEST_ITEM_001" for x in items):
            print("✅ Voce test trovata")
        else:
            print("⚠️ Voce test non trovata nella ricerca")
    else:
        print(f"❌ Search Failed: {r.text}")

    # 3. Upsert Listino
    print("\n🔹 Test 3: Upsert Listino")
    price_payload = {
        "region": "TestRegion",
        "city": "TestCity",
        "materials": {"TEST_MAT": 10.50},
        "wages": {"muratore": 28.00}
    }
    r = requests.post(f"{BASE_URL}/api/catalog/works/pricelist/upsert_codes", json=price_payload)
    if r.status_code == 200:
        print("✅ Pricelist Upsert OK")
    else:
        print(f"❌ Pricelist Upsert Failed: {r.text}")

    # 4. Get Listino
    print("\n🔹 Test 4: Get Listino")
    r = requests.get(f"{BASE_URL}/api/catalog/works/pricelist?region=TestRegion&city=TestCity")
    if r.status_code == 200:
        pl = r.json().get("pricelist")
        if pl and pl.get("wages", {}).get("muratore") == 28.0:
            print("✅ Listino recuperato correttamente")
        else:
            print(f"⚠️ Dati listino non corrispondono: {pl}")
    else:
        print(f"❌ Get Pricelist Failed: {r.text}")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()