"""Tests for Cron API routes."""

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

        # Create app with test configuration
        app = create_app({
            "db_path": str(db_path),
            "workspaces_path": str(workspaces_path),
            "orchestrator": None,
        })

        # Manually trigger lifespan since ASGITransport doesn't
        async with lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test"
            ) as client:
                yield client


async def create_test_workspace(client: AsyncClient, name: str = "test_workspace") -> dict:
    """Helper to create a test workspace."""
    workspace_data = {
        "name": name,
        "description": "Test workspace for cron tests",
    }
    response = await client.post("/api/v1/workspaces", json=workspace_data)
    assert response.status_code == 201
    return response.json()


async def create_test_cron(
    client: AsyncClient,
    workspace: str = "test_workspace",
    name: str = "test_cron",
    schedule: str = "0 9 * * *",
    enabled: bool = True,
) -> dict:
    """Helper to create a test cron job."""
    cron_data = {
        "workspace": workspace,
        "name": name,
        "schedule": schedule,
        "prompt": "Test prompt for cron job",
        "output": {
            "channel": "telegram",
            "chat_id": 123456789,
        },
        "enabled": enabled,
    }
    response = await client.post("/api/v1/crons", json=cron_data)
    assert response.status_code == 201
    return response.json()


class TestCronListRoutes:
    """Test cron job listing endpoints."""

    async def test_list_crons_returns_empty_list_initially(self, test_app):
        """Test GET /api/v1/crons returns empty list."""
        response = await test_app.get("/api/v1/crons")

        assert response.status_code == 200
        data = response.json()
        assert data["cron_jobs"] == []
        assert data["total"] == 0

    async def test_list_crons_returns_created_crons(self, test_app):
        """Test GET /api/v1/crons returns created cron jobs."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        # Create cron jobs
        await create_test_cron(test_app, "workspace1", "cron1", "0 9 * * *")
        await create_test_cron(test_app, "workspace1", "cron2", "*/15 * * * *")

        # List all crons
        response = await test_app.get("/api/v1/crons")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["cron_jobs"]) == 2

        cron_names = {c["name"] for c in data["cron_jobs"]}
        assert cron_names == {"cron1", "cron2"}

    async def test_list_crons_filters_by_workspace(self, test_app):
        """Test GET /api/v1/crons filters by workspace query param."""
        # Create workspaces
        await create_test_workspace(test_app, "workspace1")
        await create_test_workspace(test_app, "workspace2")

        # Create crons in different workspaces
        await create_test_cron(test_app, "workspace1", "cron1")
        await create_test_cron(test_app, "workspace2", "cron2")

        # Filter by workspace1
        response = await test_app.get("/api/v1/crons?workspace=workspace1")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cron_jobs"][0]["name"] == "cron1"
        assert data["cron_jobs"][0]["workspace"] == "workspace1"

    async def test_list_crons_filters_by_enabled(self, test_app):
        """Test GET /api/v1/crons filters by enabled query param."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        # Create enabled and disabled crons
        await create_test_cron(test_app, "workspace1", "enabled_cron", enabled=True)
        await create_test_cron(test_app, "workspace1", "disabled_cron", enabled=False)

        # Filter by enabled=true
        response = await test_app.get("/api/v1/crons?enabled=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cron_jobs"][0]["name"] == "enabled_cron"
        assert data["cron_jobs"][0]["enabled"] is True

        # Filter by enabled=false
        response = await test_app.get("/api/v1/crons?enabled=false")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cron_jobs"][0]["name"] == "disabled_cron"
        assert data["cron_jobs"][0]["enabled"] is False

    async def test_list_crons_combines_filters(self, test_app):
        """Test GET /api/v1/crons with multiple filters."""
        # Create workspaces
        await create_test_workspace(test_app, "workspace1")
        await create_test_workspace(test_app, "workspace2")

        # Create various crons
        await create_test_cron(test_app, "workspace1", "cron1", enabled=True)
        await create_test_cron(test_app, "workspace1", "cron2", enabled=False)
        await create_test_cron(test_app, "workspace2", "cron3", enabled=True)

        # Filter by workspace1 and enabled=true
        response = await test_app.get("/api/v1/crons?workspace=workspace1&enabled=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cron_jobs"][0]["name"] == "cron1"


class TestCronCreateRoutes:
    """Test cron job creation endpoints."""

    async def test_create_cron_returns_201(self, test_app):
        """Test POST /api/v1/crons creates successfully with valid data."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        cron_data = {
            "workspace": "workspace1",
            "name": "daily_task",
            "schedule": "0 9 * * *",
            "prompt": "Generate daily summary",
            "output": {
                "channel": "telegram",
                "chat_id": 123456789,
            },
            "enabled": True,
        }

        response = await test_app.post("/api/v1/crons", json=cron_data)

        assert response.status_code == 201
        data = response.json()
        assert data["workspace"] == "workspace1"
        assert data["name"] == "daily_task"
        assert data["schedule"] == "0 9 * * *"
        assert data["prompt"] == "Generate daily summary"
        assert data["enabled"] is True
        assert data["output"]["channel"] == "telegram"
        assert data["output"]["chat_id"] == 123456789
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "next_run" in data

    async def test_create_cron_returns_409_for_duplicate_name(self, test_app):
        """Test POST /api/v1/crons returns 409 for duplicate name in same workspace."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        # Create first cron
        await create_test_cron(test_app, "workspace1", "duplicate_cron")

        # Try to create duplicate
        cron_data = {
            "workspace": "workspace1",
            "name": "duplicate_cron",
            "schedule": "*/15 * * * *",
            "prompt": "Different prompt",
            "output": {
                "channel": "telegram",
                "chat_id": 987654321,
            },
        }

        response = await test_app.post("/api/v1/crons", json=cron_data)

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    async def test_create_cron_allows_same_name_in_different_workspaces(self, test_app):
        """Test POST /api/v1/crons allows same name in different workspaces."""
        # Create workspaces
        await create_test_workspace(test_app, "workspace1")
        await create_test_workspace(test_app, "workspace2")

        # Create cron in workspace1
        await create_test_cron(test_app, "workspace1", "same_name")

        # Create cron with same name in workspace2
        response = await create_test_cron(test_app, "workspace2", "same_name")

        assert response["name"] == "same_name"
        assert response["workspace"] == "workspace2"

    async def test_create_cron_returns_404_for_invalid_workspace(self, test_app):
        """Test POST /api/v1/crons returns 404 for invalid workspace."""
        cron_data = {
            "workspace": "nonexistent_workspace",
            "name": "test_cron",
            "schedule": "0 9 * * *",
            "prompt": "Test prompt",
            "output": {
                "channel": "telegram",
                "chat_id": 123456789,
            },
        }

        response = await test_app.post("/api/v1/crons", json=cron_data)

        assert response.status_code == 400
        assert "workspace" in response.json()["detail"].lower()

    async def test_create_cron_returns_400_for_invalid_schedule(self, test_app):
        """Test POST /api/v1/crons returns 400 for invalid schedule."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        # Test invalid schedule format
        cron_data = {
            "workspace": "workspace1",
            "name": "invalid_cron",
            "schedule": "invalid schedule",
            "prompt": "Test prompt",
            "output": {
                "channel": "telegram",
                "chat_id": 123456789,
            },
        }

        response = await test_app.post("/api/v1/crons", json=cron_data)

        assert response.status_code == 400
        assert "schedule" in response.json()["detail"].lower()

    async def test_create_cron_returns_400_for_incomplete_schedule(self, test_app):
        """Test POST /api/v1/crons returns 400 for incomplete schedule."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        # Test schedule with only 4 fields instead of 5
        cron_data = {
            "workspace": "workspace1",
            "name": "incomplete_cron",
            "schedule": "* * * *",
            "prompt": "Test prompt",
            "output": {
                "channel": "telegram",
                "chat_id": 123456789,
            },
        }

        response = await test_app.post("/api/v1/crons", json=cron_data)

        assert response.status_code == 400

    async def test_create_cron_defaults_enabled_to_true(self, test_app):
        """Test POST /api/v1/crons defaults enabled to true."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        cron_data = {
            "workspace": "workspace1",
            "name": "default_enabled",
            "schedule": "0 9 * * *",
            "prompt": "Test prompt",
            "output": {
                "channel": "telegram",
                "chat_id": 123456789,
            },
            # enabled not specified
        }

        response = await test_app.post("/api/v1/crons", json=cron_data)

        assert response.status_code == 201
        assert response.json()["enabled"] is True


class TestCronGetRoutes:
    """Test single cron job retrieval endpoints."""

    async def test_get_cron_returns_cron_data(self, test_app):
        """Test GET /api/v1/crons/{workspace}/{name} returns cron data."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        created = await create_test_cron(test_app, "workspace1", "test_cron")

        # Get the cron
        response = await test_app.get("/api/v1/crons/workspace1/test_cron")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created["id"]
        assert data["workspace"] == "workspace1"
        assert data["name"] == "test_cron"
        assert data["schedule"] == "0 9 * * *"
        assert data["prompt"] == "Test prompt for cron job"
        assert data["enabled"] is True
        assert "next_run" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_get_cron_returns_404_for_invalid_workspace(self, test_app):
        """Test GET /api/v1/crons/{workspace}/{name} returns 404 for invalid workspace."""
        response = await test_app.get("/api/v1/crons/nonexistent/test_cron")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_get_cron_returns_404_for_invalid_name(self, test_app):
        """Test GET /api/v1/crons/{workspace}/{name} returns 404 for invalid name."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        response = await test_app.get("/api/v1/crons/workspace1/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestCronUpdateRoutes:
    """Test cron job update endpoints."""

    async def test_update_cron_updates_schedule(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} updates schedule."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron", "0 9 * * *")

        # Update schedule
        update_data = {"schedule": "*/30 * * * *"}
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["schedule"] == "*/30 * * * *"
        assert data["name"] == "test_cron"

    async def test_update_cron_updates_enabled(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} updates enabled."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron", enabled=True)

        # Disable cron
        update_data = {"enabled": False}
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

        # Re-enable cron
        update_data = {"enabled": True}
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True

    async def test_update_cron_updates_prompt(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} updates prompt."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron")

        # Update prompt
        new_prompt = "New prompt text for the cron job"
        update_data = {"prompt": new_prompt}
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["prompt"] == new_prompt

    async def test_update_cron_updates_output(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} updates output."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron")

        # Update output
        new_output = {
            "channel": "telegram",
            "chat_id": 999888777,
        }
        update_data = {"output": new_output}
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["output"]["chat_id"] == 999888777

    async def test_update_cron_updates_multiple_fields(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} updates multiple fields."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron")

        # Update multiple fields
        update_data = {
            "schedule": "0 12 * * *",
            "prompt": "Updated prompt",
            "enabled": False,
        }
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["schedule"] == "0 12 * * *"
        assert data["prompt"] == "Updated prompt"
        assert data["enabled"] is False

    async def test_update_cron_returns_404_for_invalid_workspace(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} returns 404 for invalid workspace."""
        update_data = {"enabled": False}
        response = await test_app.put("/api/v1/crons/nonexistent/test_cron", json=update_data)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_update_cron_returns_404_for_invalid_name(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} returns 404 for invalid name."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        update_data = {"enabled": False}
        response = await test_app.put("/api/v1/crons/workspace1/nonexistent", json=update_data)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_update_cron_returns_400_for_invalid_schedule(self, test_app):
        """Test PUT /api/v1/crons/{workspace}/{name} returns 400 for invalid schedule."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron")

        # Update with invalid schedule
        update_data = {"schedule": "invalid schedule format"}
        response = await test_app.put("/api/v1/crons/workspace1/test_cron", json=update_data)

        assert response.status_code == 400
        assert "schedule" in response.json()["detail"].lower()


class TestCronDeleteRoutes:
    """Test cron job deletion endpoints."""

    async def test_delete_cron_returns_204(self, test_app):
        """Test DELETE /api/v1/crons/{workspace}/{name} returns 204 on success."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron")

        # Delete cron
        response = await test_app.delete("/api/v1/crons/workspace1/test_cron")

        assert response.status_code == 204
        assert response.content == b""

    async def test_delete_cron_removes_from_list(self, test_app):
        """Test DELETE /api/v1/crons/{workspace}/{name} removes cron from list."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "delete_me")

        # Verify cron exists
        list_response = await test_app.get("/api/v1/crons")
        assert list_response.json()["total"] == 1

        # Delete cron
        await test_app.delete("/api/v1/crons/workspace1/delete_me")

        # Verify cron removed
        list_response = await test_app.get("/api/v1/crons")
        assert list_response.json()["total"] == 0

    async def test_delete_cron_returns_404_for_invalid_workspace(self, test_app):
        """Test DELETE /api/v1/crons/{workspace}/{name} returns 404 for invalid workspace."""
        response = await test_app.delete("/api/v1/crons/nonexistent/test_cron")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_delete_cron_returns_404_for_invalid_name(self, test_app):
        """Test DELETE /api/v1/crons/{workspace}/{name} returns 404 for invalid name."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        response = await test_app.delete("/api/v1/crons/workspace1/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestCronTriggerRoutes:
    """Test manual cron trigger endpoints."""

    async def test_trigger_cron_returns_202(self, test_app):
        """Test POST /api/v1/crons/{workspace}/{name}/trigger returns 202 on success."""
        # Create workspace and cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "test_cron")

        # Trigger cron
        response = await test_app.post("/api/v1/crons/workspace1/test_cron/trigger")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["workspace"] == "workspace1"
        assert data["name"] == "test_cron"

    async def test_trigger_cron_works_for_disabled_cron(self, test_app):
        """Test POST /api/v1/crons/{workspace}/{name}/trigger works for disabled cron."""
        # Create workspace and disabled cron
        await create_test_workspace(test_app, "workspace1")
        await create_test_cron(test_app, "workspace1", "disabled_cron", enabled=False)

        # Trigger should still work
        response = await test_app.post("/api/v1/crons/workspace1/disabled_cron/trigger")

        assert response.status_code == 202

    async def test_trigger_cron_returns_404_for_invalid_workspace(self, test_app):
        """Test POST /api/v1/crons/{workspace}/{name}/trigger returns 404 for invalid workspace."""
        response = await test_app.post("/api/v1/crons/nonexistent/test_cron/trigger")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_trigger_cron_returns_404_for_invalid_name(self, test_app):
        """Test POST /api/v1/crons/{workspace}/{name}/trigger returns 404 for invalid name."""
        # Create workspace
        await create_test_workspace(test_app, "workspace1")

        response = await test_app.post("/api/v1/crons/workspace1/nonexistent/trigger")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestCronExecutionRoutes:
    """Test cron execution history endpoints."""

    async def test_list_executions_returns_empty_list_initially(self, test_app):
        """Test GET /api/v1/crons/executions returns empty list."""
        response = await test_app.get("/api/v1/crons/executions")

        assert response.status_code == 200
        data = response.json()
        assert data["executions"] == []
        assert data["total"] == 0

    async def test_list_executions_accepts_workspace_filter(self, test_app):
        """Test GET /api/v1/crons/executions accepts workspace query param."""
        response = await test_app.get("/api/v1/crons/executions?workspace=test_workspace")

        assert response.status_code == 200
        data = response.json()
        assert "executions" in data
        assert "total" in data

    async def test_list_executions_accepts_limit_parameter(self, test_app):
        """Test GET /api/v1/crons/executions accepts limit query param."""
        response = await test_app.get("/api/v1/crons/executions?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert "executions" in data
        assert "total" in data

    async def test_list_executions_validates_limit_range(self, test_app):
        """Test GET /api/v1/crons/executions validates limit range."""
        # Test limit < 1
        response = await test_app.get("/api/v1/crons/executions?limit=0")
        assert response.status_code == 422

        # Test limit > 500
        response = await test_app.get("/api/v1/crons/executions?limit=501")
        assert response.status_code == 422

        # Valid limits should work
        response = await test_app.get("/api/v1/crons/executions?limit=1")
        assert response.status_code == 200

        response = await test_app.get("/api/v1/crons/executions?limit=500")
        assert response.status_code == 200


class TestCronValidSchedules:
    """Test various valid cron schedule formats."""

    async def test_create_cron_with_standard_schedule(self, test_app):
        """Test creating cron with standard daily schedule."""
        await create_test_workspace(test_app, "workspace1")

        cron = await create_test_cron(test_app, "workspace1", "daily", "0 9 * * *")
        assert cron["schedule"] == "0 9 * * *"

    async def test_create_cron_with_interval_schedule(self, test_app):
        """Test creating cron with interval schedule."""
        await create_test_workspace(test_app, "workspace1")

        cron = await create_test_cron(test_app, "workspace1", "every_15_min", "*/15 * * * *")
        assert cron["schedule"] == "*/15 * * * *"

    async def test_create_cron_with_midnight_schedule(self, test_app):
        """Test creating cron with midnight schedule."""
        await create_test_workspace(test_app, "workspace1")

        cron = await create_test_cron(test_app, "workspace1", "midnight", "0 0 * * *")
        assert cron["schedule"] == "0 0 * * *"

    async def test_create_cron_with_weekly_schedule(self, test_app):
        """Test creating cron with weekly schedule."""
        await create_test_workspace(test_app, "workspace1")

        cron = await create_test_cron(test_app, "workspace1", "sunday", "0 0 * * 0")
        assert cron["schedule"] == "0 0 * * 0"
