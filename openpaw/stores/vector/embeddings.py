"""Embedding provider abstractions for vector search."""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    Provides a common interface for generating vector embeddings from text.
    """

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Get the dimensionality of the embedding vectors.

        Returns:
            Number of dimensions in each embedding vector.
        """
        ...


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embeddings via langchain_openai.OpenAIEmbeddings.

    Uses the OpenAI embeddings API with text-embedding-3-small by default.
    """

    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small"):
        """Initialize the OpenAI embedding provider.

        Args:
            api_key: OpenAI API key (uses OPENAI_API_KEY env var if None).
            model: Model name (default: text-embedding-3-small, 1536 dims).
        """
        from langchain_openai import OpenAIEmbeddings

        if api_key:
            self._embeddings = OpenAIEmbeddings(model=model, api_key=api_key)  # type: ignore[arg-type]
        else:
            self._embeddings = OpenAIEmbeddings(model=model)
        self._model = model
        self._dimensions = 1536  # text-embedding-3-small default

        logger.info(f"OpenAI embedding provider initialized (model: {model}, dims: {self._dimensions})")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        return await self._embeddings.aembed_documents(texts)

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        return await self._embeddings.aembed_query(query)

    @property
    def dimensions(self) -> int:
        """Get the dimensionality of the embedding vectors.

        Returns:
            Number of dimensions (1536 for text-embedding-3-small).
        """
        return self._dimensions
