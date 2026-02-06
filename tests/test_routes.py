"""Tests for API routes (settings and workspaces)."""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from openpaw.api.app import create_app
from openpaw.db.database import get_db_manager, init_db_manager
from openpaw.db.models import Setting, Workspace


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
    """Create test FastAPI app with temporary database and workspaces."""
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
                yield client, workspaces_path


@pytest.fixture
async def test_client(test_app):
    """Provide just the client from test_app fixture."""
    client, _ = test_app
    return client


@pytest.fixture
async def workspaces_path(test_app):
    """Provide just the workspaces path from test_app fixture."""
    _, path = test_app
    return path


class TestSettingsRoutes:
    """Test settings API endpoints."""

    async def test_get_all_settings_empty(self, test_client):
        """Test GET /api/v1/settings returns empty structure."""
        response = await test_client.get("/api/v1/settings")

        assert response.status_code == 200
        data = response.json()
        assert "agent" in data
        assert "queue" in data
        assert "lanes" in data

    async def test_get_all_settings_with_data(self, test_client):
        """Test GET /api/v1/settings returns populated settings."""
        # Insert test settings directly to database
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            settings = [
                Setting(key="agent.model", value={"value": "claude-sonnet-4"}, category="agent"),
                Setting(key="queue.mode", value={"value": "collect"}, category="queue"),
                Setting(key="lanes.main_concurrency", value={"value": 4}, category="lanes"),
            ]
            session.add_all(settings)
            await session.commit()

        response = await test_client.get("/api/v1/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["agent"]["model"] == "claude-sonnet-4"
        assert data["queue"]["mode"] == "collect"
        assert data["lanes"]["main_concurrency"] == 4

    async def test_get_category_settings_valid(self, test_client):
        """Test GET /api/v1/settings/{category} returns category settings."""
        # Insert test settings
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            settings = [
                Setting(key="agent.model", value={"value": "claude"}, category="agent"),
                Setting(key="agent.temperature", value={"value": 0.7}, category="agent"),
            ]
            session.add_all(settings)
            await session.commit()

        response = await test_client.get("/api/v1/settings/agent")

        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "claude"
        assert data["temperature"] == 0.7

    async def test_get_category_settings_invalid(self, test_client):
        """Test GET /api/v1/settings/{category} returns 404 for invalid category."""
        response = await test_client.get("/api/v1/settings/invalid")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_update_category_settings(self, test_client):
        """Test PUT /api/v1/settings/{category} updates settings."""
        update_data = {
            "model": "claude-sonnet-4",
            "temperature": 0.8,
            "max_turns": 60,
        }

        response = await test_client.put("/api/v1/settings/agent", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "claude-sonnet-4"
        assert data["temperature"] == 0.8
        assert data["max_turns"] == 60

        # Verify persistence
        get_response = await test_client.get("/api/v1/settings/agent")
        assert get_response.status_code == 200
        assert get_response.json()["model"] == "claude-sonnet-4"

    async def test_update_category_settings_invalid_category(self, test_client):
        """Test PUT /api/v1/settings/{category} returns 404 for invalid category."""
        response = await test_client.put("/api/v1/settings/invalid", json={"key": "value"})

        assert response.status_code == 404
        assert "Invalid category" in response.json()["detail"]

    async def test_import_settings_from_yaml(self, test_client):
        """Test POST /api/v1/settings/import imports from YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "agent": {
                    "model": "anthropic:claude-sonnet-4",
                    "temperature": 0.7,
                    "max_turns": 50,
                },
                "queue": {
                    "mode": "collect",
                    "debounce_ms": 1000,
                },
                "lanes": {
                    "main_concurrency": 4,
                },
            }
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            import_request = {
                "config_path": str(config_path),
                "overwrite": False,
            }

            response = await test_client.post("/api/v1/settings/import", json=import_request)

            assert response.status_code == 200
            data = response.json()
            assert data["imported"]["settings"] > 0
            assert data["errors"] == []

    async def test_import_settings_file_not_found(self, test_client):
        """Test POST /api/v1/settings/import returns 400 for missing file."""
        import_request = {
            "config_path": "/nonexistent/path.yaml",
            "overwrite": False,
        }

        response = await test_client.post("/api/v1/settings/import", json=import_request)

        assert response.status_code == 400
        assert "not found" in response.json()["detail"]


class TestWorkspaceRoutes:
    """Test workspace API endpoints."""

    async def test_list_workspaces_empty(self, test_client):
        """Test GET /api/v1/workspaces returns empty list."""
        response = await test_client.get("/api/v1/workspaces")

        assert response.status_code == 200
        data = response.json()
        assert data["workspaces"] == []
        assert data["total"] == 0

    async def test_list_workspaces_with_data(self, test_client, workspaces_path):
        """Test GET /api/v1/workspaces returns workspace list."""
        # Create test workspace
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test-workspace",
                description="Test description",
                path=str(workspaces_path / "test-workspace"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.get("/api/v1/workspaces")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["workspaces"]) == 1
        assert data["workspaces"][0]["name"] == "test-workspace"

    async def test_create_workspace_success(self, test_client, workspaces_path):
        """Test POST /api/v1/workspaces creates workspace."""
        create_data = {
            "name": "new-workspace",
            "description": "New test workspace",
        }

        response = await test_client.post("/api/v1/workspaces", json=create_data)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "new-workspace"
        assert data["description"] == "New test workspace"
        assert data["enabled"] is True
        assert data["status"] == "stopped"

        # Verify filesystem created
        workspace_path = workspaces_path / "new-workspace"
        assert workspace_path.exists()
        assert (workspace_path / "AGENT.md").exists()

    async def test_create_workspace_conflict(self, test_client, workspaces_path):
        """Test POST /api/v1/workspaces returns 409 if workspace exists."""
        # Create existing workspace
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="existing",
                path=str(workspaces_path / "existing"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        create_data = {"name": "existing"}
        response = await test_client.post("/api/v1/workspaces", json=create_data)

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    async def test_get_workspace_success(self, test_client, workspaces_path):
        """Test GET /api/v1/workspaces/{name} returns workspace details."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                description="Test workspace",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.get("/api/v1/workspaces/test")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test"
        assert data["description"] == "Test workspace"

    async def test_get_workspace_not_found(self, test_client):
        """Test GET /api/v1/workspaces/{name} returns 404 if not found."""
        response = await test_client.get("/api/v1/workspaces/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_update_workspace_success(self, test_client, workspaces_path):
        """Test PUT /api/v1/workspaces/{name} updates workspace."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                description="Old description",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        update_data = {
            "description": "New description",
            "enabled": False,
        }

        response = await test_client.put("/api/v1/workspaces/test", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "New description"
        assert data["enabled"] is False

    async def test_update_workspace_model_config(self, test_client, workspaces_path):
        """Test PUT /api/v1/workspaces/{name} updates model config."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        update_data = {
            "model_config": {
                "model_provider": "anthropic",
                "model_name": "claude-sonnet-4",
                "temperature": 0.7,
            }
        }

        response = await test_client.put("/api/v1/workspaces/test", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["config"]["model_provider"] == "anthropic"
        assert data["config"]["model_name"] == "claude-sonnet-4"

    async def test_update_workspace_not_found(self, test_client):
        """Test PUT /api/v1/workspaces/{name} returns 404 if not found."""
        response = await test_client.put("/api/v1/workspaces/nonexistent", json={"description": "test"})

        assert response.status_code == 404

    async def test_delete_workspace_success(self, test_client, workspaces_path):
        """Test DELETE /api/v1/workspaces/{name} returns 204."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.delete("/api/v1/workspaces/test")

        assert response.status_code == 204

        # Verify workspace removed from database
        get_response = await test_client.get("/api/v1/workspaces/test")
        assert get_response.status_code == 404

    async def test_delete_workspace_with_files(self, test_client, workspaces_path):
        """Test DELETE /api/v1/workspaces/{name} with delete_files=true removes filesystem."""
        # Create workspace with files
        workspace_path = workspaces_path / "test"
        workspace_path.mkdir()
        (workspace_path / "AGENT.md").write_text("test")

        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspace_path),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.delete("/api/v1/workspaces/test?delete_files=true")

        assert response.status_code == 204
        assert not workspace_path.exists()

    async def test_delete_workspace_not_found(self, test_client):
        """Test DELETE /api/v1/workspaces/{name} returns 404 if not found."""
        response = await test_client.delete("/api/v1/workspaces/nonexistent")

        assert response.status_code == 404


class TestWorkspaceFileRoutes:
    """Test workspace file operations."""

    async def test_list_workspace_files(self, test_client, workspaces_path):
        """Test GET /api/v1/workspaces/{name}/files lists files."""
        workspace_path = workspaces_path / "test"
        workspace_path.mkdir()
        (workspace_path / "AGENT.md").write_text("test")
        (workspace_path / "SOUL.md").write_text("test")

        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspace_path),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.get("/api/v1/workspaces/test/files")

        assert response.status_code == 200
        data = response.json()
        assert set(data["files"]) == {"AGENT.md", "SOUL.md"}

    async def test_read_workspace_file_success(self, test_client, workspaces_path):
        """Test GET /api/v1/workspaces/{name}/files/{filename} returns content."""
        workspace_path = workspaces_path / "test"
        workspace_path.mkdir()
        (workspace_path / "AGENT.md").write_text("Test content")

        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspace_path),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.get("/api/v1/workspaces/test/files/AGENT.md")

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "AGENT.md"
        assert data["content"] == "Test content"
        assert "updated_at" in data

    async def test_read_workspace_file_invalid_filename(self, test_client, workspaces_path):
        """Test GET /api/v1/workspaces/{name}/files/{filename} returns 400 for invalid file."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.get("/api/v1/workspaces/test/files/invalid.txt")

        assert response.status_code == 400
        assert "Cannot read" in response.json()["detail"]

    async def test_read_workspace_file_not_found(self, test_client, workspaces_path):
        """Test GET /api/v1/workspaces/{name}/files/{filename} returns 404 if file missing."""
        workspace_path = workspaces_path / "test"
        workspace_path.mkdir()

        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspace_path),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.get("/api/v1/workspaces/test/files/AGENT.md")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_write_workspace_file_success(self, test_client, workspaces_path):
        """Test PUT /api/v1/workspaces/{name}/files/{filename} updates content."""
        workspace_path = workspaces_path / "test"
        workspace_path.mkdir()

        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspace_path),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        write_data = {"content": "New content"}
        response = await test_client.put("/api/v1/workspaces/test/files/AGENT.md", json=write_data)

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "AGENT.md"
        assert data["content"] == "New content"

        # Verify file was written
        file_content = (workspace_path / "AGENT.md").read_text()
        assert file_content == "New content"

    async def test_write_workspace_file_invalid_filename(self, test_client, workspaces_path):
        """Test PUT /api/v1/workspaces/{name}/files/{filename} returns 400 for invalid file."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        write_data = {"content": "content"}
        response = await test_client.put("/api/v1/workspaces/test/files/invalid.txt", json=write_data)

        assert response.status_code == 400
        assert "Cannot write" in response.json()["detail"]

    async def test_write_workspace_file_workspace_not_found(self, test_client):
        """Test PUT /api/v1/workspaces/{name}/files/{filename} returns 404 if workspace missing."""
        write_data = {"content": "content"}
        response = await test_client.put("/api/v1/workspaces/nonexistent/files/AGENT.md", json=write_data)

        assert response.status_code == 404


class TestWorkspaceControlRoutes:
    """Test workspace runtime control endpoints."""

    async def test_start_workspace_without_orchestrator(self, test_client, workspaces_path):
        """Test POST /api/v1/workspaces/{name}/start returns 503 without orchestrator."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.post("/api/v1/workspaces/test/start")

        assert response.status_code == 503
        assert "Orchestrator not available" in response.json()["detail"]

    async def test_stop_workspace_without_orchestrator(self, test_client, workspaces_path):
        """Test POST /api/v1/workspaces/{name}/stop returns 503 without orchestrator."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.post("/api/v1/workspaces/test/stop")

        assert response.status_code == 503

    async def test_restart_workspace_without_orchestrator(self, test_client, workspaces_path):
        """Test POST /api/v1/workspaces/{name}/restart returns 503 without orchestrator."""
        db_manager = get_db_manager()
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test",
                path=str(workspaces_path / "test"),
                enabled=True,
            )
            session.add(workspace)
            await session.commit()

        response = await test_client.post("/api/v1/workspaces/test/restart")

        assert response.status_code == 503
