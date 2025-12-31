from services.schedule_service import ScheduleService

# 1. Genera piano
plan_result = ScheduleService.generate_plan(
    items=[
        {"work_code": "MUR01", "qty": 100, "unit": "m²"},
        {"work_code": "IMP01", "qty": 50, "unit": "m"}
    ],
    start_date="2025-02-01",
    region="Lazio",
    city="Roma",
    daily_hours=8,
    require_foreman=True
)

print(f"Piano generato: {len(plan_result['plan'])} works")
print(f"Warnings: {plan_result['warnings']}")

# 2. Salva piano (con assegnazione)
project_id = "507f1f77bcf86cd799439011"  # ID reale del tuo progetto

commit_result = ScheduleService.commit_plan(
    project_id=project_id,
    plan_data=plan_result["plan"],
    assign=True  # Popola workers array
)

print(f"✅ Salvato: {commit_result['works_added']} works")
print(f"✅ Assegnati: {commit_result['workers_assigned']} workers")