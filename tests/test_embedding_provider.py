"""Tests for embedding provider abstractions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.stores.vector.embeddings import BaseEmbeddingProvider, OpenAIEmbeddingProvider


class TestBaseEmbeddingProvider:
    """Test suite for BaseEmbeddingProvider ABC."""

    def test_cannot_instantiate_directly(self):
        """BaseEmbeddingProvider cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseEmbeddingProvider()

    def test_concrete_subclass_must_implement_all_methods(self):
        """Concrete subclass must implement all abstract methods."""
        class IncompleteProvider(BaseEmbeddingProvider):
            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return []

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteProvider()

    def test_concrete_subclass_with_all_methods(self):
        """Concrete subclass can be instantiated if all methods implemented."""
        class MockProvider(BaseEmbeddingProvider):
            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

            async def embed_query(self, query: str) -> list[float]:
                return [0.1, 0.2, 0.3]

            @property
            def dimensions(self) -> int:
                return 3

        provider = MockProvider()
        assert isinstance(provider, BaseEmbeddingProvider)
        assert provider.dimensions == 3


class TestMockEmbeddingProvider:
    """Test suite for a mock embedding provider implementation."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock embedding provider for testing."""
        class TestProvider(BaseEmbeddingProvider):
            def __init__(self, dimensions: int = 4):
                self._dimensions = dimensions

            async def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[float(i) / 10 for i in range(self._dimensions)] for _ in texts]

            async def embed_query(self, query: str) -> list[float]:
                return [float(i) / 10 for i in range(self._dimensions)]

            @property
            def dimensions(self) -> int:
                return self._dimensions

        return TestProvider()

    @pytest.mark.asyncio
    async def test_embed_texts_returns_embeddings(self, mock_provider):
        """Embed texts returns embeddings for each input text."""
        texts = ["Hello world", "Test document", "Another text"]

        embeddings = await mock_provider.embed_texts(texts)

        assert len(embeddings) == 3
        assert all(len(emb) == 4 for emb in embeddings)
        assert all(isinstance(emb, list) for emb in embeddings)

    @pytest.mark.asyncio
    async def test_embed_query_returns_single_embedding(self, mock_provider):
        """Embed query returns a single embedding vector."""
        query = "search query"

        embedding = await mock_provider.embed_query(query)

        assert isinstance(embedding, list)
        assert len(embedding) == 4
        assert all(isinstance(val, float) for val in embedding)

    @pytest.mark.asyncio
    async def test_embed_empty_list(self, mock_provider):
        """Embed texts handles empty list."""
        embeddings = await mock_provider.embed_texts([])

        assert embeddings == []

    def test_dimensions_property(self, mock_provider):
        """Dimensions property returns correct value."""
        assert mock_provider.dimensions == 4


class TestOpenAIEmbeddingProvider:
    """Test suite for OpenAI embedding provider."""

    @pytest.fixture
    def mock_openai_embeddings(self):
        """Create a mock OpenAIEmbeddings instance."""
        mock = MagicMock()
        mock.aembed_documents = AsyncMock(return_value=[
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ])
        mock.aembed_query = AsyncMock(return_value=[0.7, 0.8, 0.9])
        return mock

    def test_provider_initialization_without_api_key(self, mock_openai_embeddings):
        """Provider can be initialized without explicit API key."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings):
            provider = OpenAIEmbeddingProvider()

            assert provider._model == "text-embedding-3-small"
            assert provider.dimensions == 1536

    def test_provider_initialization_with_api_key(self, mock_openai_embeddings):
        """Provider can be initialized with explicit API key."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings) as mock_cls:
            _ = OpenAIEmbeddingProvider(api_key="test-key")

            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs['api_key'] == "test-key"
            assert call_kwargs['model'] == "text-embedding-3-small"

    def test_provider_initialization_with_custom_model(self, mock_openai_embeddings):
        """Provider can be initialized with custom model."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings) as mock_cls:
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")

            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs['model'] == "text-embedding-3-large"
            assert provider._model == "text-embedding-3-large"

    def test_dimensions_property(self, mock_openai_embeddings):
        """Dimensions property returns 1536 for OpenAI embeddings."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings):
            provider = OpenAIEmbeddingProvider()

            assert provider.dimensions == 1536

    @pytest.mark.asyncio
    async def test_embed_texts_delegates_to_openai(self, mock_openai_embeddings):
        """Embed texts delegates to underlying OpenAIEmbeddings."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings):
            provider = OpenAIEmbeddingProvider()
            texts = ["Hello world", "Test document"]

            embeddings = await provider.embed_texts(texts)

            mock_openai_embeddings.aembed_documents.assert_called_once_with(texts)
            assert len(embeddings) == 2
            assert embeddings[0] == [0.1, 0.2, 0.3]
            assert embeddings[1] == [0.4, 0.5, 0.6]

    @pytest.mark.asyncio
    async def test_embed_query_delegates_to_openai(self, mock_openai_embeddings):
        """Embed query delegates to underlying OpenAIEmbeddings."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings):
            provider = OpenAIEmbeddingProvider()
            query = "search query"

            embedding = await provider.embed_query(query)

            mock_openai_embeddings.aembed_query.assert_called_once_with(query)
            assert embedding == [0.7, 0.8, 0.9]

    @pytest.mark.asyncio
    async def test_embed_texts_empty_list(self, mock_openai_embeddings):
        """Embed texts handles empty list."""
        mock_openai_embeddings.aembed_documents.return_value = []

        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings):
            provider = OpenAIEmbeddingProvider()

            embeddings = await provider.embed_texts([])

            mock_openai_embeddings.aembed_documents.assert_called_once_with([])
            assert embeddings == []

    @pytest.mark.asyncio
    async def test_multiple_embed_calls(self, mock_openai_embeddings):
        """Provider can handle multiple sequential embed calls."""
        with patch('langchain_openai.OpenAIEmbeddings', return_value=mock_openai_embeddings):
            provider = OpenAIEmbeddingProvider()

            await provider.embed_texts(["Text 1"])
            await provider.embed_query("Query 1")
            await provider.embed_texts(["Text 2", "Text 3"])

            assert mock_openai_embeddings.aembed_documents.call_count == 2
            assert mock_openai_embeddings.aembed_query.call_count == 1
