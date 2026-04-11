"""RAG injection processor for auto-injecting relevant context into inbound messages."""

import logging
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
    ProcessorResult,
)
from openpaw.model.message import Message
from openpaw.stores.vector.base import BaseVectorStore, VectorSearchResult
from openpaw.stores.vector.embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)

# Approximate chars-per-token ratio for budget enforcement
_CHARS_PER_TOKEN = 4


class RagInjectionProcessor(BaseBuiltinProcessor):
    """Automatically injects relevant RAG context into inbound messages.

    Runs as the last inbound processor (priority 200), after file persistence,
    whisper, timestamp, and docling have enriched the message content.

    When active, queries the vector store with the user's message text and
    prepends a <rag_context> XML block containing relevant snippets with
    file pointers for deeper exploration via read_file().
    """

    metadata = BuiltinMetadata(
        name="rag_injection",
        display_name="RAG Context Injection",
        description="Auto-inject relevant context from past conversations and workspace files",
        builtin_type=BuiltinType.PROCESSOR,
        group="memory",
        prerequisites=BuiltinPrerequisite(),  # Runtime check via set_context
        priority=200,
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._vector_store: BaseVectorStore | None = None
        self._embedding_provider: BaseEmbeddingProvider | None = None
        self._max_results: int = 3
        self._min_score: float = 0.3
        self._max_tokens: int = 500
        self._sources: list[str] = ["conversations", "files"]
        logger.info("RagInjectionProcessor initialized")

    def set_context(
        self,
        vector_store: BaseVectorStore,
        embedding_provider: BaseEmbeddingProvider,
        max_results: int = 3,
        min_score: float = 0.3,
        max_tokens: int = 500,
        sources: list[str] | None = None,
    ) -> None:
        """Wire runtime dependencies from WorkspaceRunner.

        Args:
            vector_store: Initialized vector store instance.
            embedding_provider: Embedding provider instance.
            max_results: Maximum results to inject per message.
            min_score: Minimum similarity score threshold.
            max_tokens: Approximate token budget for injected context.
            sources: Which sources to query (conversations, files, or both).
        """
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._max_results = max_results
        self._min_score = min_score
        self._max_tokens = max_tokens
        self._sources = sources or ["conversations", "files"]
        logger.info(
            "RagInjectionProcessor connected (sources=%s, max_results=%d, min_score=%.2f)",
            self._sources,
            max_results,
            min_score,
        )

    def _is_ready(self) -> bool:
        """Check if the processor has been wired with runtime dependencies."""
        return self._vector_store is not None and self._embedding_provider is not None

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Prepend RAG context to inbound message content.

        Skips system events, very short messages, and command messages.
        On any error, returns the original message unchanged.
        """
        if not self._is_ready():
            return ProcessorResult(message=message)

        # Skip system events and commands
        if message.user_id == "system" or message.is_command:
            return ProcessorResult(message=message)

        # Skip very short messages (not enough signal for meaningful retrieval)
        content = message.content.strip()
        if len(content) < 10:
            return ProcessorResult(message=message)

        try:
            context_block = await self._build_context_block(content)
            if context_block:
                enriched = Message(
                    id=message.id,
                    content=f"{context_block}\n\n{message.content}",
                    user_id=message.user_id,
                    channel=message.channel,
                    session_key=message.session_key,
                    direction=message.direction,
                    timestamp=message.timestamp,
                    reply_to_id=message.reply_to_id,
                    attachments=message.attachments,
                    metadata=message.metadata,
                )
                return ProcessorResult(message=enriched)
        except Exception as e:
            logger.warning(f"RAG injection failed (non-fatal): {e}")

        return ProcessorResult(message=message)

    async def _build_context_block(self, query: str) -> str | None:
        """Query the vector store and format results as an XML block.

        Returns None if no relevant results found.
        """
        assert self._vector_store is not None
        assert self._embedding_provider is not None

        query_embedding = await self._embedding_provider.embed_query(query)

        # Determine source_type filter
        source_types = self._resolve_source_types()

        # Query with over-fetch for score filtering
        results: list[VectorSearchResult] = []
        for source_type in source_types:
            source_results = await self._vector_store.search(
                query_embedding=query_embedding,
                limit=self._max_results,
                source_type=source_type,
            )
            results.extend(source_results)

        # Filter by score and sort by relevance
        results = [r for r in results if r.score >= self._min_score]
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[: self._max_results]

        if not results:
            return None

        return self._format_xml_block(results)

    def _resolve_source_types(self) -> list[str]:
        """Map config source names to vector store source_type values."""
        mapping = {"conversations": "conversation", "files": "file"}
        return [mapping[s] for s in self._sources if s in mapping]

    def _format_xml_block(self, results: list[VectorSearchResult]) -> str:
        """Format search results as a <rag_context> XML block.

        Truncates individual snippets to stay within the token budget.
        """
        max_chars = self._max_tokens * _CHARS_PER_TOKEN
        char_budget_per_result = max_chars // max(len(results), 1)

        lines = [f'<rag_context results="{len(results)}">']

        for result in results:
            doc = result.document
            meta = doc.metadata
            source_type = meta.get("source_type", "unknown")
            score = f"{result.score:.2f}"

            # Build the file attribute for read_file() pointer
            file_attr = self._resolve_file_pointer(meta)

            # Truncate content to budget
            snippet = doc.content[:char_budget_per_result]
            if len(doc.content) > char_budget_per_result:
                snippet = snippet.rsplit(" ", 1)[0] + "..."

            attrs = f'source="{source_type}" score="{score}"'
            if file_attr:
                attrs += f' file="{file_attr}"'
            if "chunk_index" in meta:
                attrs += f' chunk="{meta["chunk_index"]}"'

            lines.append(f"<result {attrs}>")
            lines.append(snippet)
            lines.append("</result>")

        lines.append("</rag_context>")
        return "\n".join(lines)

    @staticmethod
    def _resolve_file_pointer(metadata: dict[str, Any]) -> str | None:
        """Extract a file path for read_file() from chunk metadata."""
        source_type = metadata.get("source_type")
        if source_type == "file":
            return metadata.get("file_path")
        if source_type == "conversation":
            conv_id = metadata.get("conversation_id")
            if conv_id:
                return f"memory/conversations/{conv_id}.md"
        return None
