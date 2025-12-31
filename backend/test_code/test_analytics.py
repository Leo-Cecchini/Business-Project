# test_analytics_refactoring.py
import requests
import json

BASE_URL = "http://localhost:5001"

def run_tests():
    print("=== TEST ANALYTICS SERVICE ===")

    # 1. KPI Veloci
    print("\n🔹 Test 1: Quick Summary (KPI)")
    r = requests.get(f"{BASE_URL}/analytics/summary?days=7")
    if r.status_code == 200:
        d = r.json()
        print(f"✅ Summary OK: Total Chats={d.get('total_chats')}, 7d={d.get('last_days_chats')}, Err={d.get('error_rate')}")
    else:
        print(f"❌ Summary Failed: {r.text}")

    # 2. Generazione Report (Simulata o Reale)
    # Nota: richiede che ci siano chat nel DB. Se vuoto, potrebbe dare errore 404 (gestito).
    print("\n🔹 Test 2: Generate Report")
    gen_payload = {"days": 30, "limit": 50}
    r = requests.post(f"{BASE_URL}/analytics/reports/generate", json=gen_payload)
    
    if r.status_code == 201:
        print("✅ Report Generated OK")
        print(f"   ID: {r.json().get('id')}")
    elif r.status_code == 404:
        print("⚠️ Report Generation: Nessuna chat trovata (corretto se DB vuoto)")
    else:
        print(f"❌ Report Gen Failed: {r.text}")

    # 3. Lista Report
    print("\n🔹 Test 3: List Reports")
    r = requests.get(f"{BASE_URL}/analytics/reports?limit=3")
    if r.status_code == 200:
        reports = r.json()
        print(f"✅ List Reports OK: Found {len(reports)}")
        if reports:
            print(f"   Latest: {reports[0]['created_at']}")
    else:
        print(f"❌ List Reports Failed: {r.text}")

    # 4. Pagina HTML
    print("\n🔹 Test 4: Analytics Page (HTML)")
    r = requests.get(f"{BASE_URL}/analytics/")
    if r.status_code == 200:
        print(f"✅ HTML Page Load OK ({len(r.text)} bytes)")
    else:
        print(f"❌ HTML Page Failed: {r.status_code}")

if __name__ == "__main__":
    run_tests()