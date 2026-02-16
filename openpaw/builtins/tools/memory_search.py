"""Memory search builtin for semantic search over past conversations."""

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.stores.vector.base import BaseVectorStore
from openpaw.stores.vector.embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class SearchConversationsInput(BaseModel):
    """Input schema for searching conversations."""

    query: str = Field(description="Natural language search query")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of results (1-20)")


class MemorySearchToolBuiltin(BaseBuiltinTool):
    """Semantic search over past conversations.

    Enables agents to search their conversation history using natural language
    queries. Results include conversation snippets with metadata for context.

    This tool requires:
    - memory.enabled: true in workspace config
    - Valid embedding provider (e.g., OpenAI API key)
    - Vector store backend (sqlite-vec)

    Config options: None (runtime check via set_context)
    """

    metadata = BuiltinMetadata(
        name="memory_search",
        display_name="Memory Search",
        description="Semantic search over past conversations",
        builtin_type=BuiltinType.TOOL,
        group="memory",
        prerequisites=BuiltinPrerequisite(),  # Runtime check via set_context
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the memory search tool builtin.

        Args:
            config: Configuration dict (currently unused).
        """
        super().__init__(config)

        # Context references (set via set_context after initialization)
        self._vector_store: BaseVectorStore | None = None
        self._embedding_provider: BaseEmbeddingProvider | None = None

        logger.info("MemorySearchToolBuiltin initialized")

    def set_context(self, vector_store: BaseVectorStore, embedding_provider: BaseEmbeddingProvider) -> None:
        """Set the vector store and embedding provider references.

        Called after vector store and embedding provider are initialized to
        enable memory search.

        Args:
            vector_store: Vector store instance.
            embedding_provider: Embedding provider instance.
        """
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        logger.info("MemorySearchTool connected to vector store and embedding provider")

    def get_langchain_tool(self) -> Any:
        """Return memory search tool as a LangChain StructuredTool."""
        return self._create_search_conversations_tool()

    def _create_search_conversations_tool(self) -> StructuredTool:
        """Create the search_conversations tool."""

        def search_conversations_sync(query: str, limit: int = 5) -> str:
            """Sync wrapper for search_conversations (for LangChain compatibility).

            Args:
                query: Natural language search query.
                limit: Maximum number of results.

            Returns:
                Formatted search results or error message.
            """
            # Guard: check if context is set
            if self._vector_store is None or self._embedding_provider is None:
                return "[Error: Memory search not available (vector store not initialized)]"

            import asyncio

            # Get or create event loop
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self._search_async(query, limit), loop
                )
                return future.result(timeout=30.0)
            except RuntimeError:
                # No running loop - safe to use asyncio.run
                return asyncio.run(self._search_async(query, limit))

        async def search_conversations_async(query: str, limit: int = 5) -> str:
            """Search past conversations using natural language.

            Args:
                query: Natural language search query.
                limit: Maximum number of results.

            Returns:
                Formatted search results or error message.
            """
            # Guard: check if context is set
            if self._vector_store is None or self._embedding_provider is None:
                return "[Error: Memory search not available (vector store not initialized)]"

            return await self._search_async(query, limit)

        return StructuredTool.from_function(
            func=search_conversations_sync,
            coroutine=search_conversations_async,
            name="search_conversations",
            description=(
                "Search past conversations using natural language queries. "
                "Returns relevant conversation snippets with metadata. "
                "Use this to recall previous discussions, decisions, or information "
                "from your conversation history."
            ),
            args_schema=SearchConversationsInput,
        )

    async def _search_async(self, query: str, limit: int) -> str:
        """Perform the actual search operation.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.

        Returns:
            Formatted search results or error message.
        """
        try:
            if self._embedding_provider is None or self._vector_store is None:
                return "[Error: Memory search not available (vector store not initialized)]"

            # Generate query embedding
            query_embedding = await self._embedding_provider.embed_query(query)

            # Search vector store
            results = await self._vector_store.search(
                query_embedding=query_embedding,
                limit=limit,
            )

            if not results:
                return "No relevant conversations found."

            # Format results
            lines = [f"Found {len(results)} relevant conversation(s):\n"]

            for i, result in enumerate(results, 1):
                doc = result.document
                metadata = doc.metadata

                conversation_id = metadata.get("conversation_id", "unknown")
                chunk_index = metadata.get("chunk_index", 0)
                score = f"{result.score:.2f}"

                lines.append(f"--- Result {i} (score: {score}) ---")
                lines.append(f"Conversation: {conversation_id}")
                lines.append(f"Chunk: {chunk_index}")

                if "timestamp_start" in metadata:
                    lines.append(f"Time: {metadata['timestamp_start']}")

                lines.append(f"\n{doc.content}\n")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return f"[Error: Memory search failed: {e}]"
