"""Vector store package for conversation memory and semantic search."""

from openpaw.stores.vector.base import (
    BaseVectorStore,
    VectorDocument,
    VectorSearchResult,
)
from openpaw.stores.vector.embeddings import (
    BaseEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from openpaw.stores.vector.factory import (
    create_embedding_provider,
    create_vector_store,
)
from openpaw.stores.vector.indexer import ConversationIndexer

__all__ = [
    "BaseVectorStore",
    "VectorDocument",
    "VectorSearchResult",
    "BaseEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "create_embedding_provider",
    "create_vector_store",
    "ConversationIndexer",
]
