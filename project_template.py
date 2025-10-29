import json
from datetime import date
from typing import List, Optional


def create_new_project(
    project_id: str,
    name: str,
    address: str,
    metric_computation_id: str = "",
    status: str = "quotation"
) -> dict:
    """Create a new project JSON structure."""
    return {
        "_id": project_id,
        "name": name,
        "project_date": date.today().isoformat(),
        "project_address": address,
        "status": status,
        "metric_computation_id": metric_computation_id,
        "works": []
    }


def add_work(
    project: dict,
    work_name: str,
    start_planned: str,
    end_planned: str,
    duration_estimated: float,
    workers: Optional[List[str]] = None
) -> None:
    """Add a work item to a project."""
    work = {
        "work_name": work_name,
        "status": "planned",
        "start_date_planned": start_planned,
        "end_date_planned": end_planned,
        "start_date_actual": None,
        "end_date_actual": None,
        "duration_estimated_hours": duration_estimated,
        "duration_actual_hours": None,
        "workers": workers or []
    }
    project["works"].append(work)


def update_work_status(project: dict, work_name: str, new_status: str) -> bool:
    """Update the status of a specific work."""
    for work in project["works"]:
        if work["work_name"] == work_name:
            work["status"] = new_status
            return True
    return False


def save_project(project: dict, filename: str) -> None:
    """Save project structure to a JSON file."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)


# ✅ Example usage
if __name__ == "__main__":
    project = create_new_project(
        project_id="PRJ-2025-003",
        name="Warehouse Renovation",
        address="Via Verdi 10, Bologna, Italy"
    )

    add_work(
        project,
        work_name="Demolition",
        start_planned="2025-11-05",
        end_planned="2025-11-10",
        duration_estimated=40,
        workers=["WRK-101", "WRK-102"]
    )

    add_work(
        project,
        work_name="Floor reconstruction",
        start_planned="2025-11-11",
        end_planned="2025-11-20",
        duration_estimated=60
    )

    update_work_status(project, "Demolition", "completed")

    save_project(project, "warehouse_project.json")
    print("✅ Project saved as warehouse_project.json")
