"""Factory functions for creating vector stores and embedding providers."""

import logging
from pathlib import Path
from typing import Any

from openpaw.core.paths import VECTORS_DB
from openpaw.stores.vector.base import BaseVectorStore
from openpaw.stores.vector.embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


def create_vector_store(provider: str, config: dict[str, Any], workspace_path: Path) -> BaseVectorStore:
    """Create a vector store from provider string and configuration.

    Args:
        provider: Vector store provider identifier (e.g., "sqlite_vec").
        config: Provider-specific configuration dict.
        workspace_path: Path to workspace root (for storage location).

    Returns:
        Configured BaseVectorStore instance.

    Raises:
        ValueError: If provider is unsupported.
    """
    if provider == "sqlite_vec":
        from openpaw.stores.vector.sqlite_vec import SqliteVecStore

        db_path = workspace_path / str(VECTORS_DB)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        return SqliteVecStore(
            db_path=db_path,
            dimensions=config.get("dimensions", 1536),
        )

    raise ValueError(f"Unknown vector store provider: {provider}")


def create_embedding_provider(provider: str, config: dict[str, Any]) -> BaseEmbeddingProvider:
    """Create an embedding provider from provider string and configuration.

    Args:
        provider: Embedding provider identifier (e.g., "openai").
        config: Provider-specific configuration dict.

    Returns:
        Configured BaseEmbeddingProvider instance.

    Raises:
        ValueError: If provider is unsupported.
    """
    if provider == "openai":
        from openpaw.stores.vector.embeddings import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=config.get("api_key"),
            model=config.get("model", "text-embedding-3-small"),
        )

    raise ValueError(f"Unknown embedding provider: {provider}")
