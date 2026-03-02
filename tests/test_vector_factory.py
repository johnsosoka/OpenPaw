"""Tests for vector store and embedding provider factory functions."""

from unittest.mock import MagicMock, patch

import pytest

from openpaw.stores.vector.factory import create_embedding_provider, create_vector_store


class TestCreateVectorStore:
    """Tests for create_vector_store factory function."""

    @patch("openpaw.stores.vector.sqlite_vec.SqliteVecStore")
    def test_sqlite_vec_returns_sqlite_vec_store(self, mock_sqlite_vec_class, tmp_path):
        """Test create_vector_store with 'sqlite_vec' returns SqliteVecStore."""
        mock_store = MagicMock()
        mock_sqlite_vec_class.return_value = mock_store

        config = {"dimensions": 1536}
        store = create_vector_store("sqlite_vec", config, tmp_path)

        # Verify the class was instantiated
        mock_sqlite_vec_class.assert_called_once()
        call_kwargs = mock_sqlite_vec_class.call_args[1]
        assert "db_path" in call_kwargs
        assert "dimensions" in call_kwargs
        assert call_kwargs["dimensions"] == 1536

        # Verify the returned instance
        assert store is mock_store

    def test_sqlite_vec_creates_data_directory(self, tmp_path):
        """Test create_vector_store creates data directory."""
        with patch("openpaw.stores.vector.sqlite_vec.SqliteVecStore") as mock_sqlite_vec_class:
            mock_store = MagicMock()
            mock_sqlite_vec_class.return_value = mock_store

            config = {"dimensions": 1536}
            create_vector_store("sqlite_vec", config, tmp_path)

            # Verify data directory was created
            data_dir = tmp_path / "data"
            assert data_dir.exists()
            assert data_dir.is_dir()

    @patch("openpaw.stores.vector.sqlite_vec.SqliteVecStore")
    def test_sqlite_vec_db_path_location(self, mock_sqlite_vec_class, tmp_path):
        """Test create_vector_store places DB in correct location."""
        mock_store = MagicMock()
        mock_sqlite_vec_class.return_value = mock_store

        config = {"dimensions": 1536}
        create_vector_store("sqlite_vec", config, tmp_path)

        call_kwargs = mock_sqlite_vec_class.call_args[1]
        db_path = call_kwargs["db_path"]
        expected_path = tmp_path / "data" / "vectors.db"
        assert db_path == expected_path

    def test_unknown_provider_raises_value_error(self, tmp_path):
        """Test create_vector_store with unknown provider raises ValueError."""
        config = {}
        with pytest.raises(ValueError, match="Unknown vector store provider: unknown_provider"):
            create_vector_store("unknown_provider", config, tmp_path)

    @patch("openpaw.stores.vector.sqlite_vec.SqliteVecStore")
    def test_sqlite_vec_passes_dimensions_config(self, mock_sqlite_vec_class, tmp_path):
        """Test create_vector_store passes dimensions config to SqliteVecStore."""
        mock_store = MagicMock()
        mock_sqlite_vec_class.return_value = mock_store

        config = {"dimensions": 768}
        create_vector_store("sqlite_vec", config, tmp_path)

        call_kwargs = mock_sqlite_vec_class.call_args[1]
        assert call_kwargs["dimensions"] == 768

    @patch("openpaw.stores.vector.sqlite_vec.SqliteVecStore")
    def test_sqlite_vec_default_dimensions(self, mock_sqlite_vec_class, tmp_path):
        """Test create_vector_store uses default dimensions if not in config."""
        mock_store = MagicMock()
        mock_sqlite_vec_class.return_value = mock_store

        config = {}
        create_vector_store("sqlite_vec", config, tmp_path)

        call_kwargs = mock_sqlite_vec_class.call_args[1]
        assert call_kwargs["dimensions"] == 1536


class TestCreateEmbeddingProvider:
    """Tests for create_embedding_provider factory function."""

    @patch("openpaw.stores.vector.embeddings.OpenAIEmbeddingProvider")
    def test_openai_returns_openai_embedding_provider(self, mock_openai_class):
        """Test create_embedding_provider with 'openai' returns OpenAIEmbeddingProvider."""
        mock_provider = MagicMock()
        mock_openai_class.return_value = mock_provider

        config = {
            "api_key": "sk-test-key",
            "model": "text-embedding-3-small",
        }
        provider = create_embedding_provider("openai", config)

        # Verify the class was instantiated
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "sk-test-key"
        assert call_kwargs["model"] == "text-embedding-3-small"

        # Verify the returned instance
        assert provider is mock_provider

    def test_unknown_provider_raises_value_error(self):
        """Test create_embedding_provider with unknown provider raises ValueError."""
        config = {}
        with pytest.raises(ValueError, match="Unknown embedding provider: unknown_provider"):
            create_embedding_provider("unknown_provider", config)

    @patch("openpaw.stores.vector.embeddings.OpenAIEmbeddingProvider")
    def test_openai_passes_api_key(self, mock_openai_class):
        """Test create_embedding_provider passes api_key to OpenAIEmbeddingProvider."""
        mock_provider = MagicMock()
        mock_openai_class.return_value = mock_provider

        config = {"api_key": "sk-custom-key"}
        create_embedding_provider("openai", config)

        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "sk-custom-key"

    @patch("openpaw.stores.vector.embeddings.OpenAIEmbeddingProvider")
    def test_openai_passes_model(self, mock_openai_class):
        """Test create_embedding_provider passes model to OpenAIEmbeddingProvider."""
        mock_provider = MagicMock()
        mock_openai_class.return_value = mock_provider

        config = {
            "api_key": "sk-test-key",
            "model": "text-embedding-3-large",
        }
        create_embedding_provider("openai", config)

        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["model"] == "text-embedding-3-large"

    @patch("openpaw.stores.vector.embeddings.OpenAIEmbeddingProvider")
    def test_openai_default_model(self, mock_openai_class):
        """Test create_embedding_provider uses default model if not in config."""
        mock_provider = MagicMock()
        mock_openai_class.return_value = mock_provider

        config = {"api_key": "sk-test-key"}
        create_embedding_provider("openai", config)

        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["model"] == "text-embedding-3-small"

    @patch("openpaw.stores.vector.embeddings.OpenAIEmbeddingProvider")
    def test_openai_api_key_from_config(self, mock_openai_class):
        """Test create_embedding_provider extracts api_key from config dict."""
        mock_provider = MagicMock()
        mock_openai_class.return_value = mock_provider

        config = {
            "api_key": "sk-nested-key",
            "model": "text-embedding-3-small",
        }
        create_embedding_provider("openai", config)

        call_kwargs = mock_openai_class.call_args[1]
        assert call_kwargs["api_key"] == "sk-nested-key"
