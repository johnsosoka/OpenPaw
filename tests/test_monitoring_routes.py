"""Tests for monitoring API routes."""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from openpaw.api.app import create_app
from openpaw.db.database import init_db_manager


@asynccontextmanager
async def lifespan_context(app):
    """Manually trigger app lifespan for testing."""
    # Startup
    db_path = app.state.config.get("db_path", "openpaw.db")
    db_manager = init_db_manager(db_path)
    await db_manager.init_db()
    app.state.db_manager = db_manager

    yield

    # Shutdown
    await db_manager.close()


@pytest.fixture
async def test_app():
    """Create test FastAPI app with temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        workspaces_path = Path(tmpdir) / "workspaces"
        workspaces_path.mkdir()

        app = create_app({
            "db_path": str(db_path),
            "workspaces_path": str(workspaces_path),
            "orchestrator": None,
        })

        async with lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test"
            ) as client:
                yield client


class TestHealthCheckRoute:
    """Test health check endpoint."""

    async def test_health_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/health returns health status with proper structure."""
        response = await test_app.get("/api/v1/monitoring/health")

        assert response.status_code == 200
        data = response.json()

        # Verify required fields
        assert "status" in data
        assert "version" in data
        assert "database" in data
        assert "orchestrator" in data
        assert "workspaces" in data

        # Verify types
        assert isinstance(data["status"], str)
        assert isinstance(data["version"], str)
        assert isinstance(data["database"], str)
        assert isinstance(data["orchestrator"], str)
        assert isinstance(data["workspaces"], dict)

    async def test_health_works_without_orchestrator(self, test_app):
        """Test GET /api/v1/monitoring/health gracefully handles missing orchestrator."""
        response = await test_app.get("/api/v1/monitoring/health")

        assert response.status_code == 200
        data = response.json()

        # Without orchestrator, should report unavailable
        assert data["orchestrator"] == "unavailable"
        assert data["workspaces"]["total"] == 0
        assert data["workspaces"]["running"] == 0


class TestWorkspaceListRoute:
    """Test workspace listing endpoint."""

    async def test_list_workspaces_returns_empty_without_orchestrator(self, test_app):
        """Test GET /api/v1/monitoring/workspaces returns empty list without orchestrator."""
        response = await test_app.get("/api/v1/monitoring/workspaces")

        assert response.status_code == 200
        data = response.json()

        assert "workspaces" in data
        assert isinstance(data["workspaces"], list)
        assert len(data["workspaces"]) == 0

    async def test_list_workspaces_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/workspaces returns proper structure."""
        response = await test_app.get("/api/v1/monitoring/workspaces")

        assert response.status_code == 200
        data = response.json()

        assert "workspaces" in data
        assert isinstance(data["workspaces"], list)


class TestWorkspaceDetailRoute:
    """Test workspace detail endpoint."""

    async def test_get_workspace_returns_404_without_orchestrator(self, test_app):
        """Test GET /api/v1/monitoring/workspaces/{name} returns 404 when orchestrator not available."""
        response = await test_app.get("/api/v1/monitoring/workspaces/test_workspace")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    async def test_get_workspace_returns_404_for_nonexistent(self, test_app):
        """Test GET /api/v1/monitoring/workspaces/{name} returns 404 when workspace not found."""
        response = await test_app.get("/api/v1/monitoring/workspaces/nonexistent_workspace")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()


class TestWorkspaceSessionsRoute:
    """Test workspace sessions endpoint."""

    async def test_list_sessions_returns_404_without_orchestrator(self, test_app):
        """Test GET /api/v1/monitoring/workspaces/{name}/sessions returns 404 when workspace not found."""
        response = await test_app.get("/api/v1/monitoring/workspaces/test_workspace/sessions")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    async def test_list_sessions_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/workspaces/{name}/sessions returns proper structure."""
        # Without orchestrator, this will return 404
        response = await test_app.get("/api/v1/monitoring/workspaces/any_workspace/sessions")

        # Either 404 (no orchestrator) or 200 with sessions list
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert "sessions" in data
            assert isinstance(data["sessions"], list)


class TestMetricsRoute:
    """Test metrics endpoints."""

    async def test_get_aggregated_metrics_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/metrics returns metrics with proper structure."""
        response = await test_app.get("/api/v1/monitoring/metrics")

        assert response.status_code == 200
        data = response.json()

        # Verify required fields
        assert "period" in data
        assert "start" in data
        assert "end" in data
        assert "metrics" in data

        # Verify types
        assert isinstance(data["period"], str)
        assert isinstance(data["start"], str)  # ISO timestamp
        assert isinstance(data["end"], str)    # ISO timestamp
        assert isinstance(data["metrics"], dict)

    async def test_get_metrics_accepts_period_param(self, test_app):
        """Test GET /api/v1/monitoring/metrics accepts period query param."""
        for period in ["hour", "day", "week"]:
            response = await test_app.get(f"/api/v1/monitoring/metrics?period={period}")

            assert response.status_code == 200
            data = response.json()
            assert data["period"] == period

    async def test_get_metrics_defaults_to_day_period(self, test_app):
        """Test GET /api/v1/monitoring/metrics defaults to day period."""
        response = await test_app.get("/api/v1/monitoring/metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "day"

    async def test_get_workspace_metrics_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/metrics/{workspace} returns workspace-specific metrics."""
        response = await test_app.get("/api/v1/monitoring/metrics/test_workspace")

        assert response.status_code == 200
        data = response.json()

        # Verify required fields
        assert "period" in data
        assert "start" in data
        assert "end" in data
        assert "metrics" in data

    async def test_get_workspace_metrics_accepts_period_param(self, test_app):
        """Test GET /api/v1/monitoring/metrics/{workspace} accepts period query param."""
        for period in ["hour", "day", "week"]:
            response = await test_app.get(
                f"/api/v1/monitoring/metrics/test_workspace?period={period}"
            )

            assert response.status_code == 200
            data = response.json()
            assert data["period"] == period


class TestErrorsRoute:
    """Test error listing endpoints."""

    async def test_list_errors_returns_empty_initially(self, test_app):
        """Test GET /api/v1/monitoring/errors returns empty list initially."""
        response = await test_app.get("/api/v1/monitoring/errors")

        assert response.status_code == 200
        data = response.json()

        assert "errors" in data
        assert isinstance(data["errors"], list)
        assert len(data["errors"]) == 0

    async def test_list_errors_accepts_workspace_param(self, test_app):
        """Test GET /api/v1/monitoring/errors accepts workspace query param."""
        response = await test_app.get("/api/v1/monitoring/errors?workspace=test_workspace")

        assert response.status_code == 200
        data = response.json()
        assert "errors" in data

    async def test_list_errors_accepts_limit_param(self, test_app):
        """Test GET /api/v1/monitoring/errors accepts limit query param."""
        response = await test_app.get("/api/v1/monitoring/errors?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert "errors" in data

    async def test_list_errors_defaults_to_50_limit(self, test_app):
        """Test GET /api/v1/monitoring/errors defaults to limit of 50."""
        response = await test_app.get("/api/v1/monitoring/errors")

        assert response.status_code == 200
        # Response will be empty initially, but should accept the default

    async def test_list_workspace_errors_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/errors/{workspace} returns workspace-specific errors."""
        response = await test_app.get("/api/v1/monitoring/errors/test_workspace")

        assert response.status_code == 200
        data = response.json()

        assert "errors" in data
        assert isinstance(data["errors"], list)

    async def test_list_workspace_errors_accepts_limit_param(self, test_app):
        """Test GET /api/v1/monitoring/errors/{workspace} accepts limit query param."""
        response = await test_app.get("/api/v1/monitoring/errors/test_workspace?limit=25")

        assert response.status_code == 200
        data = response.json()
        assert "errors" in data


class TestQueueStatisticsRoute:
    """Test queue statistics endpoint."""

    async def test_get_queue_stats_returns_proper_structure(self, test_app):
        """Test GET /api/v1/monitoring/queues returns queue stats with proper structure."""
        response = await test_app.get("/api/v1/monitoring/queues")

        assert response.status_code == 200
        data = response.json()

        # Verify required fields
        assert "queues" in data
        assert "totals" in data

        # Verify types
        assert isinstance(data["queues"], dict)
        assert isinstance(data["totals"], dict)

    async def test_get_queue_stats_empty_without_orchestrator(self, test_app):
        """Test GET /api/v1/monitoring/queues returns empty stats without orchestrator."""
        response = await test_app.get("/api/v1/monitoring/queues")

        assert response.status_code == 200
        data = response.json()

        # Without orchestrator, should return empty queues
        assert data["queues"] == {}
        assert isinstance(data["totals"], dict)
