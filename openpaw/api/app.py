"""FastAPI application factory for OpenPaw management API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openpaw.api.routes.monitoring import router as monitoring_router
from openpaw.db.database import init_db_manager
from openpaw.orchestrator import OpenPawOrchestrator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle."""
    # Startup: Initialize database
    db_path = app.state.config.get("db_path", "openpaw.db")
    db_manager = init_db_manager(db_path)
    await db_manager.init_db()

    # Store database manager in app state
    # Note: orchestrator and workspaces_path are already set in create_app
    app.state.db_manager = db_manager

    yield

    # Shutdown: Cleanup resources
    await db_manager.close()


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config: Application configuration dictionary. Expected keys:
            - db_path: Path to SQLite database (default: "openpaw.db")
            - workspaces_path: Path to agent_workspaces directory
            - orchestrator: Optional OpenPawOrchestrator instance
            - cors_origins: List of allowed CORS origins (default: ["*"])

    Returns:
        Configured FastAPI application instance
    """
    # Default configuration
    default_config = {
        "db_path": "openpaw.db",
        "workspaces_path": Path("agent_workspaces"),
        "orchestrator": None,
        "cors_origins": ["*"],  # Allow all origins for dev
    }

    # Merge provided config with defaults
    app_config = {**default_config, **(config or {})}

    # Create FastAPI app with lifespan
    app = FastAPI(
        title="OpenPaw Management API",
        description="REST API for managing OpenPaw agent workspaces",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store config in app state
    app.state.config = app_config
    app.state.workspaces_path = Path(app_config["workspaces_path"])
    app.state.orchestrator = app_config["orchestrator"]

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config["cors_origins"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routes at /api/v1
    api_v1 = FastAPI()
    api_v1.include_router(monitoring_router)

    # Share state with sub-app so dependencies can access orchestrator, etc.
    api_v1.state = app.state

    app.mount("/api/v1", api_v1)

    return app


def attach_orchestrator(app: FastAPI, orchestrator: OpenPawOrchestrator) -> None:
    """
    Attach an orchestrator to a running FastAPI application.

    This allows the CLI to create the app, start it, then attach the
    orchestrator after initialization.

    Args:
        app: FastAPI application instance
        orchestrator: Running OpenPawOrchestrator instance
    """
    app.state.orchestrator = orchestrator
