"""Tests for LocalEmbeddingProvider — lazy-loading local sentence-transformers embeddings."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.stores.vector.embeddings import LocalEmbeddingProvider


class TestLocalEmbeddingProviderInit:
    """Tests for LocalEmbeddingProvider constructor behavior."""

    def test_constructor_sets_model_name(self):
        """Constructor stores the supplied model name."""
        provider = LocalEmbeddingProvider(model="all-mpnet-base-v2")
        assert provider._model_name == "all-mpnet-base-v2"

    def test_constructor_default_model_name(self):
        """Constructor uses all-MiniLM-L6-v2 when no model is supplied."""
        provider = LocalEmbeddingProvider()
        assert provider._model_name == "all-MiniLM-L6-v2"

    def test_constructor_sets_dimensions_from_known_dimensions(self):
        """Constructor resolves dimensions from KNOWN_DIMENSIONS for a known model."""
        provider = LocalEmbeddingProvider(model="all-mpnet-base-v2")
        assert provider._dimensions_val == 768

    def test_constructor_default_model_dimensions(self):
        """Constructor resolves 384 dimensions for the default all-MiniLM-L6-v2 model."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")
        assert provider._dimensions_val == 384

    def test_unknown_model_defaults_to_384_dimensions(self):
        """Unknown model names fall back to 384 dimensions."""
        provider = LocalEmbeddingProvider(model="some-exotic-model-xyz")
        assert provider._dimensions_val == 384

    def test_embeddings_is_none_initially(self):
        """_embeddings is None after construction — lazy loading has not fired."""
        provider = LocalEmbeddingProvider()
        assert provider._embeddings is None

    def test_dimensions_property_returns_correct_value(self):
        """dimensions property reflects the resolved dimension count."""
        provider = LocalEmbeddingProvider(model="all-mpnet-base-v2")
        assert provider.dimensions == 768

    def test_dimensions_property_for_default_model(self):
        """dimensions property returns 384 for the default model."""
        provider = LocalEmbeddingProvider()
        assert provider.dimensions == 384


class TestLocalEmbeddingProviderLazyLoading:
    """Tests for _ensure_loaded() lazy-import behavior."""

    def test_ensure_loaded_imports_langchain_huggingface(self):
        """_ensure_loaded imports langchain_huggingface when called for the first time."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings.return_value = MagicMock()

        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            provider._ensure_loaded()

        mock_module.HuggingFaceEmbeddings.assert_called_once()

    def test_ensure_loaded_creates_huggingface_embeddings_with_correct_model_name(self):
        """_ensure_loaded passes the sentence-transformers-prefixed model name."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings.return_value = MagicMock()

        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            provider._ensure_loaded()

        call_kwargs = mock_module.HuggingFaceEmbeddings.call_args[1]
        assert call_kwargs["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"

    def test_ensure_loaded_passes_cpu_device(self):
        """_ensure_loaded configures model_kwargs with device=cpu."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings.return_value = MagicMock()

        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            provider._ensure_loaded()

        call_kwargs = mock_module.HuggingFaceEmbeddings.call_args[1]
        assert call_kwargs["model_kwargs"] == {"device": "cpu"}

    def test_ensure_loaded_passes_normalize_embeddings(self):
        """_ensure_loaded configures encode_kwargs with normalize_embeddings=True."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        mock_module = MagicMock()
        mock_module.HuggingFaceEmbeddings.return_value = MagicMock()

        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            provider._ensure_loaded()

        call_kwargs = mock_module.HuggingFaceEmbeddings.call_args[1]
        assert call_kwargs["encode_kwargs"] == {"normalize_embeddings": True}

    def test_ensure_loaded_is_idempotent(self):
        """_ensure_loaded is a no-op on subsequent calls when already loaded."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        mock_module = MagicMock()
        mock_embeddings_instance = MagicMock()
        mock_module.HuggingFaceEmbeddings.return_value = mock_embeddings_instance

        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            provider._ensure_loaded()
            provider._ensure_loaded()

        # HuggingFaceEmbeddings should only be constructed once
        mock_module.HuggingFaceEmbeddings.assert_called_once()

    def test_ensure_loaded_stores_embeddings_instance(self):
        """_ensure_loaded populates _embeddings after the first call."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")
        assert provider._embeddings is None

        mock_module = MagicMock()
        mock_embeddings_instance = MagicMock()
        mock_module.HuggingFaceEmbeddings.return_value = mock_embeddings_instance

        with patch.dict(sys.modules, {"langchain_huggingface": mock_module}):
            provider._ensure_loaded()

        assert provider._embeddings is mock_embeddings_instance

    def test_ensure_loaded_raises_import_error_when_package_missing(self):
        """_ensure_loaded raises ImportError with a helpful message when langchain_huggingface is absent."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        # Remove langchain_huggingface from sys.modules so the import fails
        modules_without_huggingface = {
            k: v for k, v in sys.modules.items() if k != "langchain_huggingface"
        }
        modules_without_huggingface["langchain_huggingface"] = None  # type: ignore[assignment]

        with patch.dict(sys.modules, modules_without_huggingface, clear=False):
            # Patch the import inside the method to raise ImportError
            with patch.dict(sys.modules, {"langchain_huggingface": None}):  # type: ignore[dict-item]
                with pytest.raises(ImportError, match="memory-local"):
                    provider._ensure_loaded()

    def test_ensure_loaded_raises_import_error_mentions_install_command(self):
        """ImportError from missing package mentions pip install openpaw[memory-local]."""
        provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2")

        with patch.dict(sys.modules, {"langchain_huggingface": None}):  # type: ignore[dict-item]
            with pytest.raises(ImportError, match="pip install openpaw"):
                provider._ensure_loaded()


class TestLocalEmbeddingProviderEmbed:
    """Tests for embed_texts() and embed_query() delegation behavior."""

    @pytest.mark.asyncio
    async def test_embed_texts_calls_ensure_loaded(self):
        """embed_texts calls _ensure_loaded before delegating."""
        provider = LocalEmbeddingProvider()

        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1, 0.2]])
        provider._embeddings = mock_embeddings

        with patch.object(provider, "_ensure_loaded") as mock_ensure:
            await provider.embed_texts(["hello"])
            mock_ensure.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_texts_delegates_to_aembed_documents(self):
        """embed_texts passes the text list through to aembed_documents."""
        provider = LocalEmbeddingProvider()

        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        provider._embeddings = mock_embeddings

        with patch.object(provider, "_ensure_loaded"):
            result = await provider.embed_texts(["hello world"])

        mock_embeddings.aembed_documents.assert_called_once_with(["hello world"])
        assert result == [[0.1, 0.2, 0.3]]

    @pytest.mark.asyncio
    async def test_embed_texts_returns_embeddings(self):
        """embed_texts returns the embedding list produced by the underlying model."""
        provider = LocalEmbeddingProvider()

        expected = [[0.1, 0.2], [0.3, 0.4]]
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=expected)
        provider._embeddings = mock_embeddings

        with patch.object(provider, "_ensure_loaded"):
            result = await provider.embed_texts(["hello", "world"])

        assert result == expected

    @pytest.mark.asyncio
    async def test_embed_query_calls_ensure_loaded(self):
        """embed_query calls _ensure_loaded before delegating."""
        provider = LocalEmbeddingProvider()

        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=[0.1, 0.2])
        provider._embeddings = mock_embeddings

        with patch.object(provider, "_ensure_loaded") as mock_ensure:
            await provider.embed_query("hello")
            mock_ensure.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_query_delegates_to_aembed_query(self):
        """embed_query passes the query string through to aembed_query."""
        provider = LocalEmbeddingProvider()

        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=[0.9, 0.1])
        provider._embeddings = mock_embeddings

        with patch.object(provider, "_ensure_loaded"):
            result = await provider.embed_query("search term")

        mock_embeddings.aembed_query.assert_called_once_with("search term")
        assert result == [0.9, 0.1]

    @pytest.mark.asyncio
    async def test_embed_query_returns_embedding_vector(self):
        """embed_query returns the single embedding vector from the underlying model."""
        provider = LocalEmbeddingProvider()

        expected = [0.1, 0.2, 0.3, 0.4]
        mock_embeddings = AsyncMock()
        mock_embeddings.aembed_query = AsyncMock(return_value=expected)
        provider._embeddings = mock_embeddings

        with patch.object(provider, "_ensure_loaded"):
            result = await provider.embed_query("some query")

        assert result == expected
