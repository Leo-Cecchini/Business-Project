# test_schedule_refactoring.py
import requests
import json

BASE_URL = "http://localhost:5001"

def run_tests():
    print("=== TEST SCHEDULE SERVICE ===")
    
    # 1. Capacity Check
    print("\n🔹 Test 1: Capacity Check")
    payload = {
        "start": "2025-05-01",
        "end": "2025-05-05",
        "role": "muratore",
        "crew_min": 1,
        "region": "Lazio" 
    }
    r = requests.post(f"{BASE_URL}/api/schedule/capacity_check", json=payload)
    if r.status_code == 200:
        print("✅ Capacity Check: OK")
        print(f"   Response: {json.dumps(r.json(), indent=2)}")
    else:
        print(f"❌ Error: {r.text}")

    # ... dentro run_tests() ...

    # 1.5 PREPARAZIONE DATI (Creiamo un worker disponibile per il test)
    print("\n🔹 Prep: Creazione Worker per Schedule Test")
    worker_payload = {
        "name": "Mario Rossi",
        "role": "muratore", # Ruolo richiesto dal test
        "home_city": "Roma",
        "home_region": "Lazio", # Regione richiesta
        "available": True
    }
    # Assumiamo che la route workers esista
    requests.post(f"{BASE_URL}/api/workers", json=worker_payload)
    
    # ... (poi esegui Auto Plan) ...

    # 2. Auto Plan
    print("\n🔹 Test 2: Auto Plan")
    plan_payload = {
        "start": "2025-06-01",
        "region": "Lazio",
        "items": [
            {"work_code": "FLR-001", "qty": 100, "unit": "m2"}, # Posa pavimento (codice deve esistere in work_catalog o finto)
            # Se non hai codici reali nel DB, il test potrebbe dare warnings ma non deve crashare
        ]
    }
    r = requests.post(f"{BASE_URL}/api/schedule/auto_plan", json=plan_payload)
    if r.status_code == 200:
        print("✅ Auto Plan: OK")
        res = r.json()
        print(f"   Plan items: {len(res.get('plan', []))}")
        print(f"   Warnings: {res.get('warnings')}")
        
        # 3. Commit Plan (se il plan ha successo)
        if res.get("plan"):
            print("\n🔹 Test 3: Commit Plan")
            commit_payload = {
                "project_id": "TEST_PRJ_SCHED", # Assicurati che esista o che il service gestisca upsert su draft
                "plan": res["plan"],
                "assign_now": True
            }
            # Creiamo un progetto fittizio prima per sicurezza
            requests.post(f"{BASE_URL}/api/projects", json={"name": "Test Sched", "id": "TEST_PRJ_SCHED"})
            
            r2 = requests.post(f"{BASE_URL}/api/schedule/commit_plan", json=commit_payload)
            if r2.status_code == 200:
                print("✅ Commit Plan: OK")
                print(f"   Assigned: {r2.json().get('assigned')}")
            else:
                print(f"❌ Commit Error: {r2.text}")
    else:
        print(f"❌ Auto Plan Error: {r.text}")

if __name__ == "__main__":
    run_tests()