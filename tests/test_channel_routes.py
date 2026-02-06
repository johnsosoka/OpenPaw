"""Tests for channel API routes."""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


class TestChannelTypesRoutes:
    """Test channel types endpoints."""

    async def test_list_channel_types_returns_all_supported(self, test_app):
        """Test GET /api/v1/channels/types returns supported channel types."""
        response = await test_app.get("/api/v1/channels/types")

        assert response.status_code == 200
        data = response.json()
        assert "types" in data
        assert isinstance(data["types"], list)
        assert len(data["types"]) > 0

        # Verify structure of each channel type
        for channel_type in data["types"]:
            assert "name" in channel_type
            assert "description" in channel_type
            assert "config_schema" in channel_type
            assert "status" in channel_type
            assert isinstance(channel_type["config_schema"], dict)

    async def test_list_channel_types_includes_telegram_as_active(self, test_app):
        """Test GET /api/v1/channels/types includes telegram as active."""
        response = await test_app.get("/api/v1/channels/types")

        assert response.status_code == 200
        data = response.json()
        types = data["types"]

        telegram = next((t for t in types if t["name"] == "telegram"), None)
        assert telegram is not None
        assert telegram["status"] == "active"
        assert "token" in telegram["config_schema"]["properties"]

    async def test_list_channel_types_includes_planned_channels(self, test_app):
        """Test GET /api/v1/channels/types includes planned channel types."""
        response = await test_app.get("/api/v1/channels/types")

        assert response.status_code == 200
        data = response.json()
        types = data["types"]
        type_names = [t["name"] for t in types]

        # Should include planned channels
        assert "discord" in type_names
        assert "slack" in type_names

        # Verify planned status
        discord = next(t for t in types if t["name"] == "discord")
        slack = next(t for t in types if t["name"] == "slack")
        assert discord["status"] == "planned"
        assert slack["status"] == "planned"


class TestChannelConfigRoutes:
    """Test channel configuration endpoints."""

    async def test_get_channel_config_returns_404_when_no_channel(self, test_app):
        """Test GET /api/v1/channels/{workspace} returns 404 when no channel configured."""
        # Create workspace first
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Try to get channel config
        response = await test_app.get("/api/v1/channels/test-workspace")

        assert response.status_code == 404
        assert "no channel configured" in response.json()["detail"].lower()

    async def test_get_channel_config_returns_config_when_exists(self, test_app):
        """Test GET /api/v1/channels/{workspace} returns config when exists."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel binding
        channel_data = {
            "type": "telegram",
            "token": "test_token_123",
            "allowed_users": [12345, 67890],
            "allowed_groups": [],
            "allow_all": False,
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        # Get channel config
        response = await test_app.get("/api/v1/channels/test-workspace")

        assert response.status_code == 200
        data = response.json()
        assert data["workspace"] == "test-workspace"
        assert data["type"] == "telegram"
        assert data["enabled"] is True
        assert data["allowed_users"] == [12345, 67890]
        assert data["allowed_groups"] == []
        assert data["allow_all"] is False
        # Token should never be returned
        assert "token" not in data

    async def test_update_channel_config_creates_new_binding(self, test_app):
        """Test PUT /api/v1/channels/{workspace} creates new channel binding."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel binding
        channel_data = {
            "type": "telegram",
            "token": "test_token_123",
            "allowed_users": [12345],
            "allowed_groups": [67890],
            "allow_all": False,
            "enabled": True
        }
        response = await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        assert response.status_code == 200
        data = response.json()
        assert data["workspace"] == "test-workspace"
        assert data["type"] == "telegram"
        assert data["enabled"] is True
        assert data["allowed_users"] == [12345]
        assert data["allowed_groups"] == [67890]
        assert data["allow_all"] is False
        # Token should never be returned
        assert "token" not in data

    async def test_update_channel_config_updates_existing_binding(self, test_app):
        """Test PUT /api/v1/channels/{workspace} updates existing channel binding."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create initial channel binding
        initial_data = {
            "type": "telegram",
            "token": "test_token_123",
            "allowed_users": [12345],
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=initial_data)

        # Update channel binding
        update_data = {
            "allowed_users": [12345, 67890],
            "allowed_groups": [11111],
            "enabled": False
        }
        response = await test_app.put("/api/v1/channels/test-workspace", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["workspace"] == "test-workspace"
        assert data["type"] == "telegram"  # Should retain type
        assert data["enabled"] is False  # Updated
        assert data["allowed_users"] == [12345, 67890]  # Updated
        assert data["allowed_groups"] == [11111]  # Updated

    async def test_update_channel_config_token_never_returned(self, test_app):
        """Test PUT /api/v1/channels/{workspace} never returns token in response."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel with token
        channel_data = {
            "type": "telegram",
            "token": "super_secret_token_123456",
            "enabled": True
        }
        response = await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        assert response.status_code == 200
        data = response.json()
        # Token should never be in response
        assert "token" not in data
        assert "config_encrypted" not in data
        # Verify it has other expected fields
        assert data["workspace"] == "test-workspace"
        assert data["type"] == "telegram"

    async def test_update_channel_config_returns_404_for_invalid_workspace(self, test_app):
        """Test PUT /api/v1/channels/{workspace} returns 404 for invalid workspace."""
        channel_data = {
            "type": "telegram",
            "token": "test_token_123",
            "enabled": True
        }
        response = await test_app.put("/api/v1/channels/nonexistent-workspace", json=channel_data)

        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    async def test_update_channel_config_returns_400_for_invalid_type(self, test_app):
        """Test PUT /api/v1/channels/{workspace} returns 400 for invalid channel type."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Try to create channel with invalid type
        channel_data = {
            "type": "invalid_channel_type",
            "token": "test_token_123",
            "enabled": True
        }
        response = await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        assert response.status_code == 400
        assert "invalid channel type" in response.json()["detail"].lower()

    async def test_update_channel_config_requires_token_for_new_binding(self, test_app):
        """Test PUT /api/v1/channels/{workspace} requires token for new binding."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Try to create channel without token
        channel_data = {
            "type": "telegram",
            "enabled": True
        }
        response = await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        assert response.status_code == 400
        assert "token" in response.json()["detail"].lower()

    async def test_update_channel_config_allows_partial_updates(self, test_app):
        """Test PUT /api/v1/channels/{workspace} allows partial updates without token."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create initial binding
        initial_data = {
            "type": "telegram",
            "token": "test_token_123",
            "allowed_users": [12345],
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=initial_data)

        # Update only enabled field
        update_data = {"enabled": False}
        response = await test_app.put("/api/v1/channels/test-workspace", json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        # Other fields should remain unchanged
        assert data["type"] == "telegram"
        assert data["allowed_users"] == [12345]


class TestChannelTestingRoutes:
    """Test channel connection testing endpoints."""

    async def test_test_connection_returns_400_for_invalid_workspace(self, test_app):
        """Test POST /api/v1/channels/{workspace}/test returns 400 for invalid workspace."""
        response = await test_app.post("/api/v1/channels/nonexistent-workspace/test")

        assert response.status_code == 400
        assert "no channel configured" in response.json()["detail"].lower()

    async def test_test_connection_returns_400_when_no_channel(self, test_app):
        """Test POST /api/v1/channels/{workspace}/test returns 400 when no channel configured."""
        # Create workspace without channel
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        response = await test_app.post("/api/v1/channels/test-workspace/test")

        assert response.status_code == 400
        assert "no channel configured" in response.json()["detail"].lower()

    @patch("openpaw.api.services.channel_service.httpx.AsyncClient")
    async def test_test_connection_returns_503_for_invalid_token(self, mock_client_class, test_app):
        """Test POST /api/v1/channels/{workspace}/test returns 503 for invalid token."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel binding with invalid token
        channel_data = {
            "type": "telegram",
            "token": "invalid_token",
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        # Mock failed telegram API call
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = Exception("Unauthorized")

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        response = await test_app.post("/api/v1/channels/test-workspace/test")

        assert response.status_code == 503
        assert "error" in response.json()["detail"].lower() or "failed" in response.json()["detail"].lower()

    @patch("openpaw.api.services.channel_service.httpx.AsyncClient")
    async def test_test_connection_returns_success_for_valid_token(self, mock_client_class, test_app):
        """Test POST /api/v1/channels/{workspace}/test returns success for valid token."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel binding
        channel_data = {
            "type": "telegram",
            "token": "valid_token_123",
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        # Mock successful telegram API call
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = AsyncMock()
        mock_response.json = lambda: {
            "ok": True,
            "result": {
                "id": 123456789,
                "username": "test_bot",
                "first_name": "Test Bot",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
                "supports_inline_queries": False
            }
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        response = await test_app.post("/api/v1/channels/test-workspace/test")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "bot_info" in data
        assert data["bot_info"]["id"] == 123456789
        assert data["bot_info"]["username"] == "test_bot"
        assert data["bot_info"]["first_name"] == "Test Bot"

    @patch("openpaw.api.services.channel_service.httpx.AsyncClient")
    async def test_test_connection_includes_bot_capabilities(self, mock_client_class, test_app):
        """Test POST /api/v1/channels/{workspace}/test includes bot capability info."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel binding
        channel_data = {
            "type": "telegram",
            "token": "valid_token_123",
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        # Mock successful telegram API call with capabilities
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = AsyncMock()
        mock_response.json = lambda: {
            "ok": True,
            "result": {
                "id": 123456789,
                "username": "test_bot",
                "first_name": "Test Bot",
                "can_join_groups": True,
                "can_read_all_group_messages": True,
                "supports_inline_queries": True
            }
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        response = await test_app.post("/api/v1/channels/test-workspace/test")

        assert response.status_code == 200
        data = response.json()
        bot_info = data["bot_info"]
        assert bot_info["can_join_groups"] is True
        assert bot_info["can_read_all_group_messages"] is True
        assert bot_info["supports_inline_queries"] is True

    @patch("openpaw.api.services.channel_service.httpx.AsyncClient")
    async def test_test_connection_handles_telegram_api_error(self, mock_client_class, test_app):
        """Test POST /api/v1/channels/{workspace}/test handles Telegram API errors."""
        # Create workspace
        workspace_data = {
            "name": "test-workspace",
            "description": "Test workspace"
        }
        await test_app.post("/api/v1/workspaces", json=workspace_data)

        # Create channel binding
        channel_data = {
            "type": "telegram",
            "token": "test_token",
            "enabled": True
        }
        await test_app.put("/api/v1/channels/test-workspace", json=channel_data)

        # Mock telegram API error response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = AsyncMock()
        mock_response.json = lambda: {
            "ok": False,
            "description": "Invalid token"
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        response = await test_app.post("/api/v1/channels/test-workspace/test")

        assert response.status_code == 503
        assert "telegram api error" in response.json()["detail"].lower()
