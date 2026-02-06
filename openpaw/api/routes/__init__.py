"""API route modules."""

from openpaw.api.routes.monitoring import router as monitoring_router
from openpaw.api.routes.settings import router as settings_router
from openpaw.api.routes.workspaces import router as workspaces_router

__all__ = ["monitoring_router", "settings_router", "workspaces_router"]
