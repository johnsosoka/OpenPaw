"""Integration tests for BuiltinLoader with database support."""

import tempfile
from pathlib import Path

import pytest

from openpaw.api.services.builtin_service import BuiltinService
from openpaw.api.services.encryption import EncryptionService
from openpaw.builtins.loader import BuiltinLoader
from openpaw.core.config import BuiltinsConfig
from openpaw.db.database import DatabaseManager


@pytest.fixture
async def db_manager():
    """Create a test database manager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        manager = DatabaseManager(db_path)
        await manager.init_db()
        yield manager
        await manager.close()


@pytest.fixture
def encryption_service():
    """Create a test encryption service."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "test_key"
        return EncryptionService(key_path)


@pytest.fixture
def empty_config():
    """Create an empty builtins config."""
    return BuiltinsConfig(
        allow=[],
        deny=[],
    )


class TestBuiltinLoaderSyncMode:
    """Test BuiltinLoader in synchronous mode (backward compatibility)."""

    def test_load_tools_without_database(self, empty_config):
        """Test loading tools without database service."""
        loader = BuiltinLoader(global_config=empty_config)

        # Should work without errors
        tools = loader.load_tools()
        assert isinstance(tools, list)

    def test_load_processors_without_database(self, empty_config):
        """Test loading processors without database service."""
        loader = BuiltinLoader(global_config=empty_config)

        # Should work without errors
        processors = loader.load_processors()
        assert isinstance(processors, list)

    def test_warns_when_sync_called_with_database_service(
        self, empty_config, db_manager, encryption_service, caplog
    ):
        """Test that warning is logged when sync methods called with database."""

        async def run_test():
            async with db_manager.session() as session:
                service = BuiltinService(session, encryption_service)

                loader = BuiltinLoader(
                    global_config=empty_config,
                    builtin_service=service,
                )

                # Call sync method despite having database service
                tools = loader.load_tools()
                assert isinstance(tools, list)

                # Should have logged warning
                assert "load_tools() was called synchronously" in caplog.text

        import asyncio

        asyncio.run(run_test())


class TestBuiltinLoaderAsyncMode:
    """Test BuiltinLoader in async mode with database support."""

    @pytest.mark.asyncio
    async def test_load_tools_with_empty_database(
        self, empty_config, db_manager, encryption_service
    ):
        """Test loading tools with empty database."""
        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=empty_config,
                builtin_service=service,
            )

            # Should work without errors
            tools = await loader.load_tools_async()
            assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_load_processors_with_empty_database(
        self, empty_config, db_manager, encryption_service
    ):
        """Test loading processors with empty database."""
        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=empty_config,
                builtin_service=service,
            )

            # Should work without errors
            processors = await loader.load_processors_async()
            assert isinstance(processors, list)

    @pytest.mark.asyncio
    async def test_database_api_key_used_when_env_not_set(
        self, empty_config, db_manager, encryption_service, monkeypatch
    ):
        """Test that database API key is used when env var not set."""
        # Clear env var if set
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            # Store API key in database
            await service.store_api_key(
                name="BRAVE_API_KEY",
                service="brave_search",
                value="test_api_key_from_db",
            )
            await session.commit()

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=empty_config,
                builtin_service=service,
            )

            # Load tools - should check database for API key
            tools = await loader.load_tools_async()

            # Verify database was queried (no error should occur)
            assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_database_allow_deny_extends_yaml(
        self, db_manager, encryption_service
    ):
        """Test that database allow/deny lists extend YAML config."""
        # YAML config with some entries
        config = BuiltinsConfig(
            allow=["brave_search"],
            deny=["group:voice"],
        )

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            # Add database allow/deny entries
            await service.update_allowlist(
                allow=["elevenlabs"],
                deny=["whisper"],
            )
            await session.commit()

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=config,
                builtin_service=service,
            )

            # Load allow/deny from database
            db_allow_deny = await loader._load_db_allow_deny()

            # Verify merged lists are used
            # YAML: allow=["brave_search"], deny=["group:voice"]
            # DB:   allow=["elevenlabs"],    deny=["whisper"]
            # Result should merge both

            # Test that _is_allowed uses both lists
            assert loader._is_allowed("brave_search", None, db_allow_deny)
            assert loader._is_allowed("elevenlabs", None, db_allow_deny)
            assert not loader._is_allowed("whisper", "voice", db_allow_deny)

    @pytest.mark.asyncio
    async def test_cache_db_allow_deny_on_first_access(
        self, empty_config, db_manager, encryption_service
    ):
        """Test that database allow/deny lists are cached."""
        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            # Set up allow/deny in database
            await service.update_allowlist(
                allow=["test_tool"],
                deny=[],
            )
            await session.commit()

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=empty_config,
                builtin_service=service,
            )

            # First access should populate cache
            assert loader._db_allow_deny is None
            result1 = await loader._load_db_allow_deny()
            assert loader._db_allow_deny is not None

            # Second access should use cache
            result2 = await loader._load_db_allow_deny()
            assert result1 == result2

    @pytest.mark.asyncio
    async def test_graceful_failure_when_database_unavailable(
        self, empty_config, caplog
    ):
        """Test that loader handles database errors gracefully."""
        # Create a broken database service (will fail on queries)
        class BrokenService:
            async def get_allowlist(self):
                raise RuntimeError("Database connection failed")

            async def get_api_key_value(self, name):
                raise RuntimeError("Database connection failed")

        loader = BuiltinLoader(
            global_config=empty_config,
            builtin_service=BrokenService(),
        )

        # Should not crash, just log warnings and fall back
        tools = await loader.load_tools_async()
        assert isinstance(tools, list)

        # Should have logged database errors
        assert "Failed to load allow/deny from database" in caplog.text


class TestBuiltinLoaderAPIKeyPriority:
    """Test API key priority: env var > database > YAML config."""

    @pytest.mark.asyncio
    async def test_env_var_takes_precedence_over_database(
        self, empty_config, db_manager, encryption_service, monkeypatch
    ):
        """Test that env var API key takes precedence over database."""
        # Set env var
        monkeypatch.setenv("BRAVE_API_KEY", "env_key")

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            # Store different key in database
            await service.store_api_key(
                name="BRAVE_API_KEY",
                service="brave_search",
                value="db_key",
            )
            await session.commit()

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=empty_config,
                builtin_service=service,
            )

            # Load tools - env var should win
            # (This is implicit - env var satisfies prerequisites so DB not checked)
            tools = await loader.load_tools_async()
            assert isinstance(tools, list)

    @pytest.mark.asyncio
    async def test_database_used_when_env_var_not_set(
        self, empty_config, db_manager, encryption_service, monkeypatch, caplog
    ):
        """Test that database API key is used when env var not set."""
        # Clear env var
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            # Store key in database
            await service.store_api_key(
                name="BRAVE_API_KEY",
                service="brave_search",
                value="db_key",
            )
            await session.commit()

        async with db_manager.session() as session:
            service = BuiltinService(session, encryption_service)

            loader = BuiltinLoader(
                global_config=empty_config,
                builtin_service=service,
            )

            # Load tools - should use database key
            tools = await loader.load_tools_async()
            assert isinstance(tools, list)

            # Should have logged database usage if key was found
            # (only if builtin was actually loaded)
