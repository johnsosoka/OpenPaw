"""API route modules."""

from openpaw.api.routes.builtins import router as builtins_router
from openpaw.api.routes.monitoring import router as monitoring_router
from openpaw.api.routes.settings import router as settings_router
from openpaw.api.routes.workspaces import router as workspaces_router

__all__ = ["builtins_router", "monitoring_router", "settings_router", "workspaces_router"]
