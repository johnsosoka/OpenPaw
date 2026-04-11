"""Memory search builtin for semantic search over past conversations and workspace files."""

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
from openpaw.stores.vector.base import BaseVectorStore, VectorSearchResult
from openpaw.stores.vector.embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class SearchConversationsInput(BaseModel):
    """Input schema for searching conversations."""

    query: str = Field(description="Natural language search query")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of results (1-20)")


class SearchWorkspaceInput(BaseModel):
    """Input schema for searching workspace files."""

    query: str = Field(description="Natural language search query")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of results (1-20)")


class MemorySearchToolBuiltin(BaseBuiltinTool):
    """Semantic search over past conversations and workspace files.

    Provides up to two tools depending on configuration:
    - search_conversations: when memory.conversations.enabled
    - search_workspace: when memory.files.enabled

    This tool requires:
    - memory.enabled: true in workspace config
    - Valid embedding provider (e.g., OpenAI API key)
    - Vector store backend (sqlite-vec)
    """

    metadata = BuiltinMetadata(
        name="memory_search",
        display_name="Memory Search",
        description="Semantic search over past conversations and workspace files",
        builtin_type=BuiltinType.TOOL,
        group="memory",
        prerequisites=BuiltinPrerequisite(),  # Runtime check via set_context
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._vector_store: BaseVectorStore | None = None
        self._embedding_provider: BaseEmbeddingProvider | None = None
        self._conversations_enabled: bool = True
        self._files_enabled: bool = False
        logger.info("MemorySearchToolBuiltin initialized")

    def set_context(
        self,
        vector_store: BaseVectorStore,
        embedding_provider: BaseEmbeddingProvider,
        conversations_enabled: bool = True,
        files_enabled: bool = False,
    ) -> None:
        """Set the vector store and embedding provider references.

        Args:
            vector_store: Vector store instance.
            embedding_provider: Embedding provider instance.
            conversations_enabled: Whether conversation search is enabled.
            files_enabled: Whether workspace file search is enabled.
        """
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._conversations_enabled = conversations_enabled
        self._files_enabled = files_enabled
        logger.info(
            "MemorySearchTool connected (conversations=%s, files=%s)",
            conversations_enabled,
            files_enabled,
        )

    def get_langchain_tool(self) -> list[Any]:
        """Return search tools as a list of LangChain StructuredTools.

        Returns one or two tools depending on what sources are enabled.
        """
        tools: list[Any] = []
        if self._conversations_enabled:
            tools.append(self._create_search_conversations_tool())
        if self._files_enabled:
            tools.append(self._create_search_workspace_tool())
        return tools

    async def _query(
        self,
        query: str,
        limit: int = 5,
        source_type: str | None = None,
        min_score: float = 0.0,
    ) -> list[VectorSearchResult]:
        """Shared query pipeline for both tools and injection.

        Args:
            query: Natural language query text.
            limit: Maximum results to return.
            source_type: Filter by source type. None = search all.
            min_score: Minimum similarity score threshold.

        Returns:
            Filtered and sorted search results.
        """
        if self._vector_store is None or self._embedding_provider is None:
            return []

        query_embedding = await self._embedding_provider.embed_query(query)

        results = await self._vector_store.search(
            query_embedding=query_embedding,
            limit=limit * 2,  # Over-fetch for score filtering
            source_type=source_type,
        )

        return [r for r in results if r.score >= min_score][:limit]

    def _create_search_conversations_tool(self) -> StructuredTool:
        """Create the search_conversations tool."""

        def search_conversations_sync(query: str, limit: int = 5) -> str:
            if self._vector_store is None or self._embedding_provider is None:
                return "[Error: Memory search not available (vector store not initialized)]"
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self._search_conversations_async(query, limit), loop
                )
                return future.result(timeout=30.0)
            except RuntimeError:
                return asyncio.run(self._search_conversations_async(query, limit))

        async def search_conversations_async(query: str, limit: int = 5) -> str:
            if self._vector_store is None or self._embedding_provider is None:
                return "[Error: Memory search not available (vector store not initialized)]"
            return await self._search_conversations_async(query, limit)

        return StructuredTool.from_function(
            func=search_conversations_sync,
            coroutine=search_conversations_async,
            name="search_conversations",
            description=(
                "Search past conversations using natural language queries. "
                "Returns relevant conversation snippets with metadata. "
                "Results include file paths you can use with read_file() for full context."
            ),
            args_schema=SearchConversationsInput,
        )

    def _create_search_workspace_tool(self) -> StructuredTool:
        """Create the search_workspace tool."""

        def search_workspace_sync(query: str, limit: int = 5) -> str:
            if self._vector_store is None or self._embedding_provider is None:
                return "[Error: Memory search not available (vector store not initialized)]"
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self._search_workspace_async(query, limit), loop
                )
                return future.result(timeout=30.0)
            except RuntimeError:
                return asyncio.run(self._search_workspace_async(query, limit))

        async def search_workspace_async(query: str, limit: int = 5) -> str:
            if self._vector_store is None or self._embedding_provider is None:
                return "[Error: Memory search not available (vector store not initialized)]"
            return await self._search_workspace_async(query, limit)

        return StructuredTool.from_function(
            func=search_workspace_sync,
            coroutine=search_workspace_async,
            name="search_workspace",
            description=(
                "Search workspace files (documents, notes, uploads) using natural language. "
                "Returns relevant file snippets with paths you can use with read_file() "
                "for full context."
            ),
            args_schema=SearchWorkspaceInput,
        )

    async def _search_conversations_async(self, query: str, limit: int) -> str:
        """Search conversation history."""
        try:
            results = await self._query(query, limit=limit, source_type="conversation")

            if not results:
                return "No relevant conversations found."

            lines = [f"Found {len(results)} relevant conversation(s):\n"]
            for i, result in enumerate(results, 1):
                doc = result.document
                metadata = doc.metadata
                conversation_id = metadata.get("conversation_id", "unknown")
                score = f"{result.score:.2f}"

                lines.append(f"--- Result {i} (score: {score}) ---")
                lines.append(f"Conversation: {conversation_id}")
                if "timestamp_start" in metadata:
                    lines.append(f"Time: {metadata['timestamp_start']}")
                lines.append(f"\n{doc.content}\n")
                lines.append(
                    f"[Full archive: read_file('memory/conversations/{conversation_id}.md')]"
                )

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Conversation search failed: {e}")
            return f"[Error: Memory search failed: {e}]"

    async def _search_workspace_async(self, query: str, limit: int) -> str:
        """Search workspace files."""
        try:
            results = await self._query(query, limit=limit, source_type="file")

            if not results:
                return "No relevant workspace files found."

            lines = [f"Found {len(results)} relevant file section(s):\n"]
            for i, result in enumerate(results, 1):
                doc = result.document
                metadata = doc.metadata
                file_path = metadata.get("file_path", "unknown")
                chunk_index = metadata.get("chunk_index", 0)
                score = f"{result.score:.2f}"

                lines.append(f"--- Result {i} (score: {score}) ---")
                lines.append(f"File: {file_path} (chunk {chunk_index})")
                if "indexed_at" in metadata:
                    lines.append(f"Indexed: {metadata['indexed_at']}")
                lines.append(f"\n{doc.content}\n")
                lines.append(f"[Full file: read_file('{file_path}')]")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Workspace search failed: {e}")
            return f"[Error: Workspace search failed: {e}]"
