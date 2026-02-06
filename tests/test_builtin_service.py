"""Tests for builtin service business logic."""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from openpaw.api.services.builtin_service import BuiltinService
from openpaw.api.services.encryption import EncryptionService
from openpaw.db.database import init_db_manager


@asynccontextmanager
async def test_db_session():
    """Create test database session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db_manager = init_db_manager(str(db_path))
        await db_manager.init_db()

        async with db_manager.session() as session:
            yield session

        await db_manager.close()


@pytest.fixture
async def builtin_service():
    """Create BuiltinService with test database session."""
    async with test_db_session() as session:
        encryption = EncryptionService()
        service = BuiltinService(session, encryption)
        yield service
        # Commit any pending changes
        await session.commit()


class TestBuiltinListing:
    """Test builtin listing operations."""

    async def test_list_registered_returns_all_builtins(self, builtin_service):
        """Test list_registered returns all builtins with availability."""
        builtins = await builtin_service.list_registered()

        assert isinstance(builtins, list)
        assert len(builtins) > 0

        for builtin in builtins:
            assert "name" in builtin
            assert "type" in builtin
            assert builtin["type"] in ["tool", "processor"]
            assert "group" in builtin
            assert "description" in builtin
            assert "prerequisites" in builtin
            assert "env_vars" in builtin["prerequisites"]
            assert "packages" in builtin["prerequisites"]
            assert "available" in builtin
            assert isinstance(builtin["available"], bool)
            assert "enabled" in builtin
            assert isinstance(builtin["enabled"], bool)

    async def test_list_available_returns_only_available(self, builtin_service):
        """Test list_available returns only builtins with satisfied prerequisites."""
        all_builtins = await builtin_service.list_registered()
        available_builtins = await builtin_service.list_available()

        assert isinstance(available_builtins, list)
        assert len(available_builtins) <= len(all_builtins)

        for builtin in available_builtins:
            assert builtin["available"] is True

    async def test_get_config_returns_config_for_valid_builtin(self, builtin_service):
        """Test get_config returns config for valid builtin."""
        all_builtins = await builtin_service.list_registered()
        if not all_builtins:
            pytest.skip("No builtins registered")

        builtin_name = all_builtins[0]["name"]
        config = await builtin_service.get_config(builtin_name)

        assert config is not None
        assert config["name"] == builtin_name
        assert "type" in config
        assert "group" in config
        assert "enabled" in config
        assert "config" in config
        assert isinstance(config["config"], dict)

    async def test_get_config_returns_none_for_invalid_builtin(self, builtin_service):
        """Test get_config returns None for nonexistent builtin."""
        config = await builtin_service.get_config("nonexistent_builtin")
        assert config is None

    async def test_update_config_enables_builtin(self, builtin_service):
        """Test update_config enables builtin correctly."""
        all_builtins = await builtin_service.list_registered()
        if not all_builtins:
            pytest.skip("No builtins registered")

        builtin_name = all_builtins[0]["name"]

        # Disable builtin
        updated = await builtin_service.update_config(builtin_name, enabled=False, config=None)
        assert updated["enabled"] is False

        # Enable builtin
        updated = await builtin_service.update_config(builtin_name, enabled=True, config=None)
        assert updated["enabled"] is True

    async def test_update_config_updates_configuration(self, builtin_service):
        """Test update_config updates config dictionary correctly."""
        all_builtins = await builtin_service.list_registered()
        if not all_builtins:
            pytest.skip("No builtins registered")

        builtin_name = all_builtins[0]["name"]
        new_config = {"test_key": "test_value", "number": 42}

        updated = await builtin_service.update_config(builtin_name, enabled=None, config=new_config)
        assert updated["config"] == new_config

    async def test_update_config_raises_for_invalid_builtin(self, builtin_service):
        """Test update_config raises ValueError for nonexistent builtin."""
        with pytest.raises(ValueError, match="not found"):
            await builtin_service.update_config("nonexistent", enabled=True, config=None)


class TestApiKeyManagement:
    """Test API key management operations."""

    async def test_list_api_keys_returns_empty_list_initially(self, builtin_service):
        """Test list_api_keys returns empty list when no keys stored."""
        keys = await builtin_service.list_api_keys()
        assert keys == []

    async def test_store_api_key_creates_key(self, builtin_service):
        """Test store_api_key stores encrypted key."""
        created = await builtin_service.store_api_key(
            name="TEST_API_KEY",
            service="test_service",
            value="secret_value_123"
        )

        assert created["name"] == "TEST_API_KEY"
        assert created["service"] == "test_service"
        assert "created_at" in created
        # Value should not be in response
        assert "value" not in created

    async def test_store_api_key_raises_if_duplicate(self, builtin_service):
        """Test store_api_key raises ValueError if duplicate name."""
        await builtin_service.store_api_key(
            name="DUPLICATE_KEY",
            service="service1",
            value="value1"
        )

        with pytest.raises(ValueError, match="already exists"):
            await builtin_service.store_api_key(
                name="DUPLICATE_KEY",
                service="service2",
                value="value2"
            )

    async def test_list_api_keys_returns_names_but_not_values(self, builtin_service):
        """Test list_api_keys returns key metadata but not values."""
        await builtin_service.store_api_key(
            name="KEY1",
            service="service1",
            value="secret1"
        )
        await builtin_service.store_api_key(
            name="KEY2",
            service="service2",
            value="secret2"
        )

        keys = await builtin_service.list_api_keys()
        assert len(keys) == 2

        for key in keys:
            assert "name" in key
            assert "service" in key
            assert "created_at" in key
            # Values should never be returned
            assert "value" not in key
            assert "key_encrypted" not in key

    async def test_delete_api_key_removes_key(self, builtin_service):
        """Test delete_api_key removes key successfully."""
        await builtin_service.store_api_key(
            name="DELETE_ME",
            service="test",
            value="secret"
        )

        # Verify key exists
        keys = await builtin_service.list_api_keys()
        assert any(k["name"] == "DELETE_ME" for k in keys)

        # Delete key
        deleted = await builtin_service.delete_api_key("DELETE_ME")
        assert deleted is True

        # Verify key removed
        keys = await builtin_service.list_api_keys()
        assert not any(k["name"] == "DELETE_ME" for k in keys)

    async def test_delete_api_key_returns_false_if_not_found(self, builtin_service):
        """Test delete_api_key returns False if key not found."""
        deleted = await builtin_service.delete_api_key("NONEXISTENT")
        assert deleted is False

    async def test_get_api_key_value_returns_decrypted_value(self, builtin_service):
        """Test get_api_key_value returns decrypted value."""
        original_value = "my_secret_api_key_123"
        await builtin_service.store_api_key(
            name="SECRET_KEY",
            service="test",
            value=original_value
        )

        decrypted = await builtin_service.get_api_key_value("SECRET_KEY")
        assert decrypted == original_value

    async def test_get_api_key_value_returns_none_if_not_found(self, builtin_service):
        """Test get_api_key_value returns None if key not found."""
        decrypted = await builtin_service.get_api_key_value("NONEXISTENT")
        assert decrypted is None


class TestAllowlistManagement:
    """Test allow/deny list management operations."""

    async def test_get_allowlist_returns_empty_lists_initially(self, builtin_service):
        """Test get_allowlist returns empty allow/deny lists initially."""
        lists = await builtin_service.get_allowlist()
        assert lists["allow"] == []
        assert lists["deny"] == []

    async def test_update_allowlist_replaces_lists(self, builtin_service):
        """Test update_allowlist replaces existing lists."""
        new_allow = ["brave_search", "whisper"]
        new_deny = ["group:voice"]

        updated = await builtin_service.update_allowlist(allow=new_allow, deny=new_deny)

        assert set(updated["allow"]) == set(new_allow)
        assert set(updated["deny"]) == set(new_deny)

    async def test_update_allowlist_overwrites_previous_values(self, builtin_service):
        """Test update_allowlist overwrites previous values."""
        # Set initial values
        await builtin_service.update_allowlist(
            allow=["builtin1", "builtin2"],
            deny=["builtin3"]
        )

        # Update with new values
        updated = await builtin_service.update_allowlist(
            allow=["new_builtin"],
            deny=[]
        )

        assert updated["allow"] == ["new_builtin"]
        assert updated["deny"] == []

    async def test_update_allowlist_accepts_empty_lists(self, builtin_service):
        """Test update_allowlist accepts empty lists to clear restrictions."""
        # Set some values
        await builtin_service.update_allowlist(
            allow=["builtin1"],
            deny=["builtin2"]
        )

        # Clear lists
        updated = await builtin_service.update_allowlist(allow=[], deny=[])

        assert updated["allow"] == []
        assert updated["deny"] == []

    async def test_get_allowlist_persists_across_calls(self, builtin_service):
        """Test get_allowlist returns persisted values."""
        allow_list = ["brave_search", "elevenlabs"]
        deny_list = ["group:experimental"]

        await builtin_service.update_allowlist(allow=allow_list, deny=deny_list)

        # Get lists in new call
        lists = await builtin_service.get_allowlist()

        assert set(lists["allow"]) == set(allow_list)
        assert set(lists["deny"]) == set(deny_list)
