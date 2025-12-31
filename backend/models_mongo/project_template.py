import json
from datetime import date, datetime
from typing import List, Optional, Dict, Any, Union

# Minimal address schema required by the product
# - Only the essentials for autocomplete + operations
# - Everything else is intentionally omitted
Address = Dict[str, Any]


def normalize_address(addr: Union[str, Address]) -> Address:
    """
    Normalizza un indirizzo (stringa o dict) nella struttura minimale:
      - formatted: stringa stampabile completa
      - street: nome via
      - street_number: civico
      - city: città
      - state: stato/paese (es. "Italia")
      - postal_code: CAP
    Tutti gli altri campi (lat/lng/place_id/region/province/...) vengono ignorati.
    """
    def _now():
        return datetime.utcnow().isoformat()

    # Ingresso come stringa → solo formatted
    if isinstance(addr, str):
        return {
            "formatted": addr.strip(),
            "street": None,
            "street_number": None,
            "city": None,
            "state": None,
            "postal_code": None,
            "created_at": _now(),
        }

    # Ingresso come dict → mappa i campi noti e ignora il resto
    formatted = (
        addr.get("formatted")
        or addr.get("formatted_address")
        or addr.get("project_address")
        or ""
    )

    return {
        "formatted": formatted,
        "street": addr.get("street") or addr.get("route") or None,
        "street_number": addr.get("street_number") or addr.get("streetNo") or None,
        "city": addr.get("city") or addr.get("locality") or None,
        # "state" è inteso come Stato/Paese (non provincia)
        "state": addr.get("state") or addr.get("country") or None,
        "postal_code": addr.get("postal_code") or addr.get("zip") or None,
        "created_at": addr.get("created_at") or _now(),
    }


def create_new_project(
    project_id: str,
    name: str,
    address: Union[str, Address],
    metric_computation_id: str = "",
    status: str = "quotation"
) -> dict:
    """Create a new project JSON structure (retro-compatibile).

    Manteniamo `project_address` (stringa) per compatibilità con codice legacy,
    ma la struttura principale è `addresses: List[Address]` con il formato minimale.
    """
    addr_obj = normalize_address(address) if address else None
    project = {
        "_id": project_id,
        "name": name,
        "project_date": date.today().isoformat(),
        # compat legacy: stringa di indirizzo principale
        "project_address": (addr_obj.get("formatted") if addr_obj else None),
        # nuova struttura minimale
        "addresses": [addr_obj] if addr_obj else [],
        "status": status,
        "metric_computation_id": metric_computation_id,
        "works": []
    }
    return project


def add_address(project: dict, address: Union[str, Address], make_primary: bool = False) -> None:
    """Aggiunge un indirizzo minimizzato al progetto. Se `make_primary=True`, lo imposta come primario.
    Aggiorna anche `project_address` con `formatted` dell'indirizzo primario.
    """
    addr_obj = normalize_address(address)
    project.setdefault("addresses", [])
    if make_primary:
        project["addresses"] = [addr_obj] + [a for a in project["addresses"] if a != addr_obj]
    else:
        project["addresses"].append(addr_obj)

    primary = project["addresses"][0] if project["addresses"] else None
    project["project_address"] = (primary.get("formatted") if primary else None)


def add_work(
    project: dict,
    work_name: str,
    start_planned: str,
    end_planned: str,
    duration_estimated: float,
    workers: Optional[List[str]] = None
) -> None:
    """Add a work item to a project, with automatic number_of_workers count."""
    worker_list = workers or []
    work = {
        "work_name": work_name,
        "status": "planned",
        "start_date_planned": start_planned,
        "end_date_planned": end_planned,
        "start_date_actual": None,
        "end_date_actual": None,
        "duration_estimated_hours": duration_estimated,
        "duration_actual_hours": None,
        "number_of_workers": len(worker_list),
        "workers": worker_list
    }
    project.setdefault("works", [])
    project["works"].append(work)


def update_work_status(project: dict, work_name: str, new_status: str) -> bool:
    """Update the status of a specific work."""
    for work in project.get("works", []):
        if work.get("work_name") == work_name:
            work["status"] = new_status
            return True
    return False


def save_project(project: dict, filename: str) -> None:
    """Save project structure to a JSON file."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)


# ✅ Example usage (minimal address)
if __name__ == "__main__":
    project = create_new_project(
        project_id="PRJ-2025-004",
        name="New School Building",
        address={
            "formatted": "Via Dante 20, Firenze, Italia",
            "street": "Via Dante",
            "street_number": "20",
            "city": "Firenze",
            "state": "Italia",
            "postal_code": "50122",
        }
    )

    add_work(
        project,
        work_name="Excavation",
        start_planned="2025-11-01",
        end_planned="2025-11-05",
        duration_estimated=50,
        workers=["WRK-201", "WRK-202", "WRK-203"]
    )

    add_address(project, "Piazza Duomo, Firenze", make_primary=False)

    save_project(project, "school_project.json")
    print("✅ Project saved as school_project.json")
