#!/usr/bin/env python3
"""
Test script per verificare i services creati.
Esegui: python test_services.py
"""
import os
import sys

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_id_generator():
    """Test generatori ID."""
    print("🧪 Test ID Generator...")
    
    from services.id_generator import (
        generate_worker_id, 
        generate_project_id,
        validate_worker_id,
        validate_project_id
    )
    
    # Test generazione
    worker_id = generate_worker_id()
    project_id = generate_project_id()
    
    print(f"  ✓ Worker ID generato: {worker_id}")
    print(f"  ✓ Project ID generato: {project_id}")
    
    # Test validazione
    assert validate_worker_id(worker_id), "Worker ID non valido!"
    assert validate_project_id(project_id), "Project ID non valido!"
    
    print(f"  ✓ Validazione ID OK")
    print()


def test_worker_service():
    """Test WorkerService (senza DB)."""
    print("🧪 Test WorkerService...")
    
    from services.worker_service import WorkerService
    
    # Test import
    print("  ✓ Import WorkerService OK")
    
    # Test metodi esistono
    assert hasattr(WorkerService, 'create_worker'), "create_worker missing"
    assert hasattr(WorkerService, 'get_worker'), "get_worker missing"
    assert hasattr(WorkerService, 'list_workers'), "list_workers missing"
    assert hasattr(WorkerService, 'update_worker'), "update_worker missing"
    assert hasattr(WorkerService, 'delete_worker'), "delete_worker missing"
    assert hasattr(WorkerService, 'toggle_availability'), "toggle_availability missing"
    
    print("  ✓ Tutti i metodi presenti")
    print()


def test_project_service():
    """Test ProjectService (senza DB)."""
    print("🧪 Test ProjectService...")
    
    from services.project_service import ProjectService
    
    # Test import
    print("  ✓ Import ProjectService OK")
    
    # Test metodi esistono
    assert hasattr(ProjectService, 'create_project'), "create_project missing"
    assert hasattr(ProjectService, 'get_project'), "get_project missing"
    assert hasattr(ProjectService, 'list_projects'), "list_projects missing"
    assert hasattr(ProjectService, 'update_project'), "update_project missing"
    assert hasattr(ProjectService, 'delete_project'), "delete_project missing"
    assert hasattr(ProjectService, 'toggle_status'), "toggle_status missing"
    assert hasattr(ProjectService, 'confirm_project'), "confirm_project missing"
    
    print("  ✓ Tutti i metodi presenti")
    
    # Test normalizzazione status
    assert ProjectService._normalize_status("confermato") == "Confermato"
    assert ProjectService._normalize_status("confirmed") == "Confermato"
    assert ProjectService._normalize_status("preventivo") == "Preventivo"
    assert ProjectService._normalize_status(None) == "Preventivo"
    
    print("  ✓ Normalizzazione status OK")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("TEST SERVICES - STEP 1")
    print("=" * 60)
    print()
    
    try:
        test_id_generator()
        test_worker_service()
        test_project_service()
        
        print("=" * 60)
        print("✅ TUTTI I TEST PASSATI!")
        print("=" * 60)
        print()
        print("I services sono pronti. Puoi procedere con STEP 2.")
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ TEST FALLITO!")
        print("=" * 60)
        print(f"Errore: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
