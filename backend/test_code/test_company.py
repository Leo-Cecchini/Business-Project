# test_company_refactoring.py
import json
import io
import requests

BASE_URL = "http://localhost:5001"

def run_tests():
    print("=== TEST REFACTORING COMPANY ===")
    
    # 1. Overview (Dashboard)
    print("\n🔹 Test 1: Company Overview")
    r = requests.get(f"{BASE_URL}/api/company/overview")
    if r.status_code == 200:
        data = r.json()
        stats = data.get("stats", {})
        print("✅ Overview OK")
        print(f"   Workers: {stats.get('workers_total')}")
        print(f"   Projects: {stats.get('projects_total')}")
        print(f"   Roles Breakdown: {data.get('roles_breakdown')}")
    else:
        print(f"❌ Overview Failed: {r.text}")

    # 2. Upload Document
    print("\n🔹 Test 2: Upload Document (Mock)")
    # Creiamo un file finto
    dummy_content = b"Regolamento Aziendale: Si lavora sodo."
    files = {
        'file': ('regolamento_test.txt', io.BytesIO(dummy_content), 'text/plain')
    }
    r = requests.post(f"{BASE_URL}/api/company/documents", files=files)
    
    if r.status_code == 201:
        res = r.json()
        print(f"✅ Upload OK: {res.get('filename')}")
        print(f"   Indexed: {res.get('indexed')}") # Potrebbe essere False se mancano dipendenze AI, ma va bene
    else:
        print(f"❌ Upload Failed: {r.text}")

    # 3. List Documents
    print("\n🔹 Test 3: List Documents")
    r = requests.get(f"{BASE_URL}/api/company/documents")
    if r.status_code == 200:
        docs = r.json().get("documents", [])
        print(f"✅ List Docs OK: Trovati {len(docs)}")
        if any(d['name'] == 'regolamento_test.txt' for d in docs):
            print("   File caricato presente nella lista.")
    else:
        print(f"❌ List Failed: {r.text}")

    print("\n=== FINE TEST ===")

if __name__ == "__main__":
    run_tests()