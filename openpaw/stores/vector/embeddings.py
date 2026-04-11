"""Embedding provider abstractions for vector search."""

import logging
from abc import ABC, abstractmethod
from typing import Any

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

    KNOWN_DIMENSIONS: dict[str, int] = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

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
        self._dimensions = self.KNOWN_DIMENSIONS.get(model, 1536)

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


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """Local embeddings via sentence-transformers (HuggingFace).

    Uses all-MiniLM-L6-v2 by default (384 dimensions, ~22MB model).
    The model is loaded lazily on first embed call to avoid startup overhead.

    Requires: pip install openpaw[memory-local]
    """

    KNOWN_DIMENSIONS: dict[str, int] = {
        "all-MiniLM-L6-v2": 384,
        "all-mpnet-base-v2": 768,
        "all-MiniLM-L12-v2": 384,
        "bge-small-en-v1.5": 384,
        "bge-base-en-v1.5": 768,
    }

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        """Initialize the local embedding provider.

        Args:
            model: HuggingFace model name (default: all-MiniLM-L6-v2, 384 dims).
        """
        self._model_name = model
        self._dimensions_val = self.KNOWN_DIMENSIONS.get(model, 384)
        self._embeddings: Any = None  # Lazy init
        logger.info(
            "Local embedding provider initialized (model: %s, dims: %d)",
            model,
            self._dimensions_val,
        )

    def _ensure_loaded(self) -> None:
        """Lazily load the sentence-transformers model on first use."""
        if self._embeddings is not None:
            return
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as e:
            raise ImportError(
                "Local embeddings require the memory-local extras: "
                "pip install openpaw[memory-local]"
            ) from e

        self._embeddings = HuggingFaceEmbeddings(
            model_name=f"sentence-transformers/{self._model_name}",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info("Loaded sentence-transformers model: %s", self._model_name)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        self._ensure_loaded()
        return await self._embeddings.aembed_documents(texts)

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query.

        Args:
            query: Query text to embed.

        Returns:
            Embedding vector.
        """
        self._ensure_loaded()
        return await self._embeddings.aembed_query(query)

    @property
    def dimensions(self) -> int:
        """Get the dimensionality of the embedding vectors."""
        return self._dimensions_val
