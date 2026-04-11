"""Tests for RagInjectionProcessor."""

from unittest.mock import AsyncMock

import pytest

from openpaw.builtins.base import BuiltinType, ProcessorResult
from openpaw.builtins.processors.rag_injection import RagInjectionProcessor
from openpaw.model.message import Message, MessageDirection
from openpaw.stores.vector.base import VectorDocument, VectorSearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_vector_store():
    """AsyncMock vector store that returns no results by default."""
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_embedding_provider():
    """AsyncMock embedding provider that returns a fixed vector."""
    provider = AsyncMock()
    provider.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return provider


@pytest.fixture
def processor():
    """Bare RagInjectionProcessor (not yet wired with runtime deps)."""
    return RagInjectionProcessor()


@pytest.fixture
def wired_processor(processor, mock_vector_store, mock_embedding_provider):
    """Processor with all runtime dependencies wired."""
    processor.set_context(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        max_results=3,
        min_score=0.3,
        max_tokens=500,
        sources=["conversations", "files"],
    )
    return processor


def _make_message(content: str, user_id: str = "user123") -> Message:
    """Helper to build a minimal inbound Message."""
    return Message(
        id="msg001",
        channel="telegram",
        session_key="telegram:user123",
        user_id=user_id,
        content=content,
        direction=MessageDirection.INBOUND,
    )


def _make_result(
    doc_id: str,
    content: str,
    score: float,
    metadata: dict | None = None,
) -> VectorSearchResult:
    """Helper to build a VectorSearchResult."""
    return VectorSearchResult(
        document=VectorDocument(
            id=doc_id,
            content=content,
            metadata=metadata or {},
        ),
        score=score,
    )


# ---------------------------------------------------------------------------
# TestMetadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_name(self, processor):
        assert processor.metadata.name == "rag_injection"

    def test_builtin_type(self, processor):
        assert processor.metadata.builtin_type == BuiltinType.PROCESSOR

    def test_priority(self, processor):
        assert processor.metadata.priority == 200

    def test_group(self, processor):
        assert processor.metadata.group == "memory"


# ---------------------------------------------------------------------------
# TestSetContext
# ---------------------------------------------------------------------------


class TestSetContext:
    def test_not_ready_before_set_context(self, processor):
        assert processor._is_ready() is False

    def test_ready_after_set_context(self, wired_processor):
        assert wired_processor._is_ready() is True

    def test_set_context_stores_vector_store(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
        )
        assert processor._vector_store is mock_vector_store

    def test_set_context_stores_embedding_provider(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
        )
        assert processor._embedding_provider is mock_embedding_provider

    def test_set_context_stores_max_results(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            max_results=7,
        )
        assert processor._max_results == 7

    def test_set_context_stores_min_score(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            min_score=0.6,
        )
        assert processor._min_score == 0.6

    def test_set_context_stores_max_tokens(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            max_tokens=1000,
        )
        assert processor._max_tokens == 1000

    def test_set_context_stores_sources(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            sources=["conversations"],
        )
        assert processor._sources == ["conversations"]

    def test_set_context_sources_defaults_to_both(
        self, processor, mock_vector_store, mock_embedding_provider
    ):
        processor.set_context(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            sources=None,
        )
        assert processor._sources == ["conversations", "files"]


# ---------------------------------------------------------------------------
# TestProcessInbound
# ---------------------------------------------------------------------------


class TestProcessInbound:
    @pytest.mark.asyncio
    async def test_returns_original_when_not_ready(self, processor):
        """Processor without set_context should pass through unchanged."""
        message = _make_message("What is the meaning of life?")
        result = await processor.process_inbound(message)
        assert isinstance(result, ProcessorResult)
        assert result.message.content == message.content

    @pytest.mark.asyncio
    async def test_returns_original_for_system_event(self, wired_processor):
        """Messages from user_id='system' should be skipped."""
        message = _make_message("system notification text here", user_id="system")
        result = await wired_processor.process_inbound(message)
        assert result.message.content == message.content

    @pytest.mark.asyncio
    async def test_returns_original_for_command(self, wired_processor):
        """Messages that are commands (starting with /) should be skipped."""
        message = _make_message("/status")
        result = await wired_processor.process_inbound(message)
        assert result.message.content == message.content

    @pytest.mark.asyncio
    async def test_returns_original_for_short_message(self, wired_processor):
        """Messages shorter than 10 chars should be skipped."""
        message = _make_message("hi")
        result = await wired_processor.process_inbound(message)
        assert result.message.content == message.content

    @pytest.mark.asyncio
    async def test_returns_original_when_no_results(
        self, wired_processor, mock_vector_store
    ):
        """When the vector store returns nothing, content is unchanged."""
        mock_vector_store.search = AsyncMock(return_value=[])
        message = _make_message("Tell me about my previous projects")
        result = await wired_processor.process_inbound(message)
        assert result.message.content == message.content

    @pytest.mark.asyncio
    async def test_injects_context_when_results_found(
        self, wired_processor, mock_vector_store
    ):
        """When results are returned, a <rag_context> block is prepended."""
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "doc1",
                    "This is a relevant snippet from memory.",
                    0.85,
                    {"source_type": "conversation", "conversation_id": "conv_abc"},
                )
            ]
        )
        message = _make_message("Tell me about my previous projects")
        result = await wired_processor.process_inbound(message)

        assert "<rag_context" in result.message.content
        assert message.content in result.message.content

    @pytest.mark.asyncio
    async def test_injected_content_preserves_original_message(
        self, wired_processor, mock_vector_store
    ):
        """Original message content must appear after the injected block."""
        original_content = "Tell me about my previous Python projects"
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "doc1",
                    "Python project notes.",
                    0.9,
                    {"source_type": "file", "file_path": "notes/python.md"},
                )
            ]
        )
        message = _make_message(original_content)
        result = await wired_processor.process_inbound(message)

        # Context block must come before the original content
        rag_pos = result.message.content.index("<rag_context")
        original_pos = result.message.content.index(original_content)
        assert rag_pos < original_pos

    @pytest.mark.asyncio
    async def test_returns_original_on_exception(
        self, wired_processor, mock_vector_store
    ):
        """Any exception during retrieval must degrade gracefully."""
        mock_vector_store.search = AsyncMock(side_effect=RuntimeError("store offline"))
        message = _make_message("Tell me about my previous projects")
        result = await wired_processor.process_inbound(message)
        assert result.message.content == message.content

    @pytest.mark.asyncio
    async def test_enriched_message_preserves_metadata(
        self, wired_processor, mock_vector_store
    ):
        """Metadata on the original message must be forwarded to the enriched copy."""
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "doc1",
                    "Relevant content.",
                    0.8,
                    {"source_type": "conversation", "conversation_id": "conv_xyz"},
                )
            ]
        )
        original_meta = {"some_key": "some_value"}
        message = _make_message("Tell me about my previous projects")
        message.metadata = original_meta
        result = await wired_processor.process_inbound(message)
        assert result.message.metadata == original_meta

    @pytest.mark.asyncio
    async def test_enriched_message_preserves_session_key(
        self, wired_processor, mock_vector_store
    ):
        """session_key must survive the enrichment copy."""
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "doc1",
                    "Relevant content.",
                    0.8,
                    {"source_type": "conversation", "conversation_id": "conv_xyz"},
                )
            ]
        )
        message = _make_message("Tell me about my previous projects")
        result = await wired_processor.process_inbound(message)
        assert result.message.session_key == message.session_key


# ---------------------------------------------------------------------------
# TestBuildContextBlock
# ---------------------------------------------------------------------------


class TestBuildContextBlock:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_results(self, wired_processor, mock_vector_store):
        mock_vector_store.search = AsyncMock(return_value=[])
        result = await wired_processor._build_context_block("some query")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_xml_block_with_conversation_result(
        self, wired_processor, mock_vector_store
    ):
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "doc1",
                    "Conversation snippet.",
                    0.75,
                    {"source_type": "conversation", "conversation_id": "conv_abc"},
                )
            ]
        )
        block = await wired_processor._build_context_block("find conversations")
        assert block is not None
        assert "<rag_context" in block
        assert "Conversation snippet." in block
        assert "</rag_context>" in block

    @pytest.mark.asyncio
    async def test_returns_xml_block_with_file_result(
        self, wired_processor, mock_vector_store
    ):
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "doc1",
                    "File content snippet.",
                    0.8,
                    {"source_type": "file", "file_path": "notes/readme.md"},
                )
            ]
        )
        block = await wired_processor._build_context_block("find files")
        assert block is not None
        assert "File content snippet." in block
        assert 'source="file"' in block

    @pytest.mark.asyncio
    async def test_respects_min_score_filtering(
        self, wired_processor, mock_vector_store
    ):
        """Results below min_score must not appear in the output."""
        wired_processor._min_score = 0.5
        mock_vector_store.search = AsyncMock(
            return_value=[
                _make_result(
                    "low",
                    "Low relevance snippet.",
                    0.2,
                    {"source_type": "file", "file_path": "low.md"},
                ),
                _make_result(
                    "high",
                    "High relevance snippet.",
                    0.9,
                    {"source_type": "file", "file_path": "high.md"},
                ),
            ]
        )
        block = await wired_processor._build_context_block("query")
        assert block is not None
        assert "Low relevance snippet." not in block
        assert "High relevance snippet." in block

    @pytest.mark.asyncio
    async def test_limits_to_max_results(self, wired_processor, mock_vector_store):
        """At most max_results entries should appear in the block."""
        wired_processor._max_results = 2
        # Return one result per search call; two source types = 2 results total,
        # but we configure the store to return 3 per call to verify slicing.
        docs = [
            _make_result(
                f"doc{i}",
                f"Snippet {i}.",
                0.9 - i * 0.05,
                {"source_type": "file", "file_path": f"file{i}.md"},
            )
            for i in range(3)
        ]
        mock_vector_store.search = AsyncMock(return_value=docs)
        block = await wired_processor._build_context_block("query")
        assert block is not None
        # XML element count must not exceed max_results
        assert block.count("<result ") <= 2


# ---------------------------------------------------------------------------
# TestFormatXmlBlock
# ---------------------------------------------------------------------------


class TestFormatXmlBlock:
    def test_xml_structure_has_rag_context_wrapper(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "Sample content.",
                0.8,
                {"source_type": "file", "file_path": "notes.md"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert xml.startswith("<rag_context")
        assert xml.endswith("</rag_context>")

    def test_results_count_attribute(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "First snippet.",
                0.9,
                {"source_type": "file", "file_path": "a.md"},
            ),
            _make_result(
                "doc2",
                "Second snippet.",
                0.8,
                {"source_type": "file", "file_path": "b.md"},
            ),
        ]
        xml = wired_processor._format_xml_block(results)
        assert 'results="2"' in xml

    def test_result_element_includes_source_attribute(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "Content.",
                0.75,
                {"source_type": "conversation", "conversation_id": "conv_abc"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert 'source="conversation"' in xml

    def test_result_element_includes_score_attribute(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "Content.",
                0.75,
                {"source_type": "file", "file_path": "x.md"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert 'score="0.75"' in xml

    def test_result_element_includes_file_attribute_for_file_source(
        self, wired_processor
    ):
        results = [
            _make_result(
                "doc1",
                "Content.",
                0.8,
                {"source_type": "file", "file_path": "notes/readme.md"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert 'file="notes/readme.md"' in xml

    def test_conversation_result_includes_memory_file_pointer(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "Content.",
                0.85,
                {"source_type": "conversation", "conversation_id": "conv_xyz"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert 'file="memory/conversations/conv_xyz.md"' in xml

    def test_content_is_present_in_result(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "The quick brown fox.",
                0.8,
                {"source_type": "file", "file_path": "fox.md"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert "The quick brown fox." in xml

    def test_long_content_is_truncated(self, wired_processor):
        """Content exceeding the per-result budget should be truncated."""
        wired_processor._max_tokens = 10  # Very small budget (~40 chars total)
        long_content = "word " * 200  # 1000+ chars
        results = [
            _make_result(
                "doc1",
                long_content,
                0.8,
                {"source_type": "file", "file_path": "long.md"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        # The full content must not appear verbatim
        assert long_content not in xml
        # Ellipsis marker should be present
        assert "..." in xml

    def test_chunk_index_attribute_when_present(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "Content.",
                0.8,
                {"source_type": "file", "file_path": "notes.md", "chunk_index": 3},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert 'chunk="3"' in xml

    def test_no_chunk_attribute_when_absent(self, wired_processor):
        results = [
            _make_result(
                "doc1",
                "Content.",
                0.8,
                {"source_type": "file", "file_path": "notes.md"},
            )
        ]
        xml = wired_processor._format_xml_block(results)
        assert "chunk=" not in xml


# ---------------------------------------------------------------------------
# TestResolveSourceTypes
# ---------------------------------------------------------------------------


class TestResolveSourceTypes:
    def test_maps_conversations_to_conversation(self, processor):
        processor._sources = ["conversations"]
        assert processor._resolve_source_types() == ["conversation"]

    def test_maps_files_to_file(self, processor):
        processor._sources = ["files"]
        assert processor._resolve_source_types() == ["file"]

    def test_handles_both_sources(self, processor):
        processor._sources = ["conversations", "files"]
        result = processor._resolve_source_types()
        assert "conversation" in result
        assert "file" in result
        assert len(result) == 2

    def test_ignores_unknown_sources(self, processor):
        processor._sources = ["conversations", "unknown_source"]
        result = processor._resolve_source_types()
        assert result == ["conversation"]


# ---------------------------------------------------------------------------
# TestResolveFilePointer
# ---------------------------------------------------------------------------


class TestResolveFilePointer:
    def test_file_source_returns_file_path(self):
        meta = {"source_type": "file", "file_path": "uploads/2026-01-01/doc.pdf"}
        result = RagInjectionProcessor._resolve_file_pointer(meta)
        assert result == "uploads/2026-01-01/doc.pdf"

    def test_conversation_source_returns_memory_path(self):
        meta = {"source_type": "conversation", "conversation_id": "conv_abc123"}
        result = RagInjectionProcessor._resolve_file_pointer(meta)
        assert result == "memory/conversations/conv_abc123.md"

    def test_unknown_source_returns_none(self):
        meta = {"source_type": "unknown"}
        result = RagInjectionProcessor._resolve_file_pointer(meta)
        assert result is None

    def test_file_source_without_file_path_returns_none(self):
        meta = {"source_type": "file"}
        result = RagInjectionProcessor._resolve_file_pointer(meta)
        assert result is None

    def test_conversation_source_without_conversation_id_returns_none(self):
        meta = {"source_type": "conversation"}
        result = RagInjectionProcessor._resolve_file_pointer(meta)
        assert result is None

    def test_empty_metadata_returns_none(self):
        result = RagInjectionProcessor._resolve_file_pointer({})
        assert result is None
