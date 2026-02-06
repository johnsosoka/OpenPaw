"""Tests for builtin API routes."""

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


class TestBuiltinManagementRoutes:
    """Test builtin management endpoints."""

    async def test_list_builtins_returns_all_registered(self, test_app):
        """Test GET /api/v1/builtins returns list of builtins."""
        response = await test_app.get("/api/v1/builtins")

        assert response.status_code == 200
        data = response.json()
        assert "builtins" in data
        assert "total" in data
        assert isinstance(data["builtins"], list)
        assert data["total"] == len(data["builtins"])

        if data["builtins"]:
            builtin = data["builtins"][0]
            assert "name" in builtin
            assert "type" in builtin
            assert "group" in builtin
            assert "description" in builtin
            assert "prerequisites" in builtin
            assert "available" in builtin
            assert "enabled" in builtin

    async def test_list_available_builtins_filters_by_availability(self, test_app):
        """Test GET /api/v1/builtins/available returns filtered list."""
        response = await test_app.get("/api/v1/builtins/available")

        assert response.status_code == 200
        data = response.json()
        assert "builtins" in data
        assert "total" in data

        for builtin in data["builtins"]:
            assert builtin["available"] is True

    async def test_get_builtin_config_returns_config(self, test_app):
        """Test GET /api/v1/builtins/{name} returns config."""
        # First get list of builtins
        list_response = await test_app.get("/api/v1/builtins")
        builtins = list_response.json()["builtins"]

        if not builtins:
            pytest.skip("No builtins registered")

        builtin_name = builtins[0]["name"]

        response = await test_app.get(f"/api/v1/builtins/{builtin_name}")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == builtin_name
        assert "type" in data
        assert "group" in data
        assert "enabled" in data
        assert "config" in data

    async def test_get_builtin_config_returns_404_for_invalid_name(self, test_app):
        """Test GET /api/v1/builtins/{name} returns 404 for invalid builtin."""
        response = await test_app.get("/api/v1/builtins/nonexistent_builtin")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_update_builtin_config_updates_enabled(self, test_app):
        """Test PUT /api/v1/builtins/{name} updates enabled state."""
        # Get a builtin name
        list_response = await test_app.get("/api/v1/builtins")
        builtins = list_response.json()["builtins"]

        if not builtins:
            pytest.skip("No builtins registered")

        builtin_name = builtins[0]["name"]

        # Disable the builtin
        update_data = {"enabled": False}
        response = await test_app.put(
            f"/api/v1/builtins/{builtin_name}",
            json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

        # Enable the builtin
        update_data = {"enabled": True}
        response = await test_app.put(
            f"/api/v1/builtins/{builtin_name}",
            json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True

    async def test_update_builtin_config_updates_config_dict(self, test_app):
        """Test PUT /api/v1/builtins/{name} updates config dictionary."""
        list_response = await test_app.get("/api/v1/builtins")
        builtins = list_response.json()["builtins"]

        if not builtins:
            pytest.skip("No builtins registered")

        builtin_name = builtins[0]["name"]

        new_config = {"test_key": "test_value", "count": 5}
        update_data = {"config": new_config}

        response = await test_app.put(
            f"/api/v1/builtins/{builtin_name}",
            json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["config"] == new_config

    async def test_update_builtin_config_returns_404_for_invalid_name(self, test_app):
        """Test PUT /api/v1/builtins/{name} returns 404 for invalid builtin."""
        update_data = {"enabled": True}
        response = await test_app.put(
            "/api/v1/builtins/nonexistent_builtin",
            json=update_data
        )

        assert response.status_code == 404


class TestApiKeyManagementRoutes:
    """Test API key management endpoints."""

    async def test_list_api_keys_returns_empty_list_initially(self, test_app):
        """Test GET /api/v1/builtins/api-keys returns empty list."""
        response = await test_app.get("/api/v1/builtins/api-keys")

        assert response.status_code == 200
        data = response.json()
        assert data["api_keys"] == []
        assert data["total"] == 0

    async def test_create_api_key_returns_201(self, test_app):
        """Test POST /api/v1/builtins/api-keys creates key."""
        key_data = {
            "name": "TEST_KEY",
            "service": "test_service",
            "value": "secret_api_key_123"
        }

        response = await test_app.post("/api/v1/builtins/api-keys", json=key_data)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "TEST_KEY"
        assert data["service"] == "test_service"
        assert "created_at" in data
        # Value should not be in response
        assert "value" not in data

    async def test_create_api_key_returns_409_if_exists(self, test_app):
        """Test POST /api/v1/builtins/api-keys returns 409 if exists."""
        key_data = {
            "name": "DUPLICATE_KEY",
            "service": "service1",
            "value": "secret1"
        }

        # Create first key
        response = await test_app.post("/api/v1/builtins/api-keys", json=key_data)
        assert response.status_code == 201

        # Try to create duplicate
        response = await test_app.post("/api/v1/builtins/api-keys", json=key_data)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    async def test_list_api_keys_returns_list_without_values(self, test_app):
        """Test GET /api/v1/builtins/api-keys returns list without values."""
        # Create some keys
        keys = [
            {"name": "KEY1", "service": "service1", "value": "secret1"},
            {"name": "KEY2", "service": "service2", "value": "secret2"},
        ]

        for key_data in keys:
            await test_app.post("/api/v1/builtins/api-keys", json=key_data)

        # List keys
        response = await test_app.get("/api/v1/builtins/api-keys")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["api_keys"]) == 2

        for key in data["api_keys"]:
            assert "name" in key
            assert "service" in key
            assert "created_at" in key
            # Values should never be returned
            assert "value" not in key
            assert "key_encrypted" not in key

    async def test_delete_api_key_returns_204(self, test_app):
        """Test DELETE /api/v1/builtins/api-keys/{name} returns 204."""
        # Create key
        key_data = {
            "name": "DELETE_ME",
            "service": "test",
            "value": "secret"
        }
        await test_app.post("/api/v1/builtins/api-keys", json=key_data)

        # Delete key
        response = await test_app.delete("/api/v1/builtins/api-keys/DELETE_ME")
        assert response.status_code == 204

        # Verify key deleted
        list_response = await test_app.get("/api/v1/builtins/api-keys")
        keys = list_response.json()["api_keys"]
        assert not any(k["name"] == "DELETE_ME" for k in keys)

    async def test_delete_api_key_returns_404_if_not_found(self, test_app):
        """Test DELETE /api/v1/builtins/api-keys/{name} returns 404 if not found."""
        response = await test_app.delete("/api/v1/builtins/api-keys/NONEXISTENT")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestAllowlistRoutes:
    """Test allowlist management endpoints."""

    async def test_get_allowlist_returns_empty_lists_initially(self, test_app):
        """Test GET /api/v1/builtins/allowlist returns empty lists."""
        response = await test_app.get("/api/v1/builtins/allowlist")

        assert response.status_code == 200
        data = response.json()
        assert data["allow"] == []
        assert data["deny"] == []

    async def test_update_allowlist_updates_lists(self, test_app):
        """Test PUT /api/v1/builtins/allowlist updates lists."""
        update_data = {
            "allow": ["brave_search", "whisper"],
            "deny": ["group:experimental"]
        }

        response = await test_app.put("/api/v1/builtins/allowlist", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert set(data["allow"]) == set(update_data["allow"])
        assert set(data["deny"]) == set(update_data["deny"])

    async def test_update_allowlist_overwrites_previous_values(self, test_app):
        """Test PUT /api/v1/builtins/allowlist overwrites previous values."""
        # Set initial values
        initial_data = {
            "allow": ["builtin1", "builtin2"],
            "deny": ["builtin3"]
        }
        await test_app.put("/api/v1/builtins/allowlist", json=initial_data)

        # Update with new values
        new_data = {
            "allow": ["new_builtin"],
            "deny": []
        }
        response = await test_app.put("/api/v1/builtins/allowlist", json=new_data)

        assert response.status_code == 200
        data = response.json()
        assert data["allow"] == ["new_builtin"]
        assert data["deny"] == []

    async def test_update_allowlist_accepts_empty_lists(self, test_app):
        """Test PUT /api/v1/builtins/allowlist accepts empty lists."""
        # Set some values
        initial_data = {
            "allow": ["builtin1"],
            "deny": ["builtin2"]
        }
        await test_app.put("/api/v1/builtins/allowlist", json=initial_data)

        # Clear lists
        clear_data = {"allow": [], "deny": []}
        response = await test_app.put("/api/v1/builtins/allowlist", json=clear_data)

        assert response.status_code == 200
        data = response.json()
        assert data["allow"] == []
        assert data["deny"] == []

    async def test_get_allowlist_returns_persisted_values(self, test_app):
        """Test GET /api/v1/builtins/allowlist returns persisted values."""
        update_data = {
            "allow": ["brave_search", "elevenlabs"],
            "deny": ["group:voice"]
        }
        await test_app.put("/api/v1/builtins/allowlist", json=update_data)

        # Get lists
        response = await test_app.get("/api/v1/builtins/allowlist")

        assert response.status_code == 200
        data = response.json()
        assert set(data["allow"]) == set(update_data["allow"])
        assert set(data["deny"]) == set(update_data["deny"])
