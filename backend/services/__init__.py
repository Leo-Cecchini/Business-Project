# services/__init__.py
"""
Service layer exports.
Centralizza l'accesso alla logica di business.
"""

# 1. Services Esistenti
from .workers_service import (
    WorkerService, 
    create_worker_service, 
    remove_worker_service, 
    PermissionError
)
from .project_service import ProjectService
from .chat_service import ChatService
from .chat_skills import ChatSkills
from .material_service import MaterialService
from .work_service import WorkService
from .computo_service import ComputoService
from .schedule_service import ScheduleService
from .catalog_service import CatalogService
from .analytics_service import AnalyticsService
from .company_service import CompanyService

# Nota: EstimateService è spesso usato internamente o come modulo di funzioni,
# ma è utile esporlo se serve accedere a 'price' o 'wage' direttamente.
from .estimate_service import (
    estimate_from_entities,
    price,
    wage
)

__all__ = [
    # Classes
    'WorkerService',
    'ProjectService',
    'ChatService',
    'ChatSkills',
    'MaterialService',
    'WorkService',
    'ComputoService',
    'ScheduleService',
    'CatalogService',
    'AnalyticsService',
    'CompanyService',
    
    # Functions / Helpers
    'create_worker_service',
    'remove_worker_service',
    'estimate_from_entities',
    'price',
    'wage',
    
    # Exceptions
    'PermissionError',
]