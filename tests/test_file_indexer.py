"""Tests for workspace file indexer."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import FileIndexingConfig
from openpaw.stores.vector.file_indexer import FileIndexer, IndexingResult, _compute_file_hash


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store with all file-indexer-relevant methods."""
    store = AsyncMock()
    store.add_documents = AsyncMock(return_value=1)
    store.delete_by_metadata = AsyncMock(return_value=0)
    store.get_file_hashes = AsyncMock(return_value={})
    store.set_file_hash = AsyncMock(return_value=None)
    store.remove_file_hash = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_embedding_provider():
    """Create a mock embedding provider that returns deterministic vectors."""
    provider = AsyncMock()
    provider.embed_texts = AsyncMock(side_effect=lambda texts: [[0.1, 0.2, 0.3]] * len(texts))
    return provider


@pytest.fixture
def file_indexer_config():
    """A FileIndexingConfig with simple patterns for testing."""
    return FileIndexingConfig(
        enabled=True,
        include=["**/*.md", "**/*.txt"],
        exclude=["excluded/**/*.md", "excluded/**/*.txt"],
        max_file_size_kb=512,
        chunk_size=1000,
        chunk_overlap=200,
    )


@pytest.fixture
def workspace_dir(tmp_path):
    """A temporary workspace directory with a handful of test files."""
    (tmp_path / "notes.md").write_text("# Notes\n\nSome markdown content.", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("Plain text file.", encoding="utf-8")
    (tmp_path / "script.py").write_text("print('hello')", encoding="utf-8")

    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "deep.md").write_text("# Deep\n\nNested file.", encoding="utf-8")

    excluded_dir = tmp_path / "excluded"
    excluded_dir.mkdir()
    (excluded_dir / "ignored.md").write_text("Should be excluded.", encoding="utf-8")

    return tmp_path


@pytest.fixture
def file_indexer(mock_vector_store, mock_embedding_provider, file_indexer_config, workspace_dir):
    """A FileIndexer wired with mocked dependencies."""
    return FileIndexer(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        workspace_path=workspace_dir,
        config=file_indexer_config,
    )


# ---------------------------------------------------------------------------
# TestDiscoverFiles
# ---------------------------------------------------------------------------


class TestDiscoverFiles:
    """Tests for _discover_files method."""

    def test_include_patterns_match_expected_files(self, file_indexer, workspace_dir):
        """Include patterns (**/*.md, **/*.txt) should match .md and .txt files."""
        discovered = file_indexer._discover_files()
        names = {p.name for p in discovered}
        assert "notes.md" in names
        assert "readme.txt" in names
        assert "deep.md" in names

    def test_non_matching_files_are_excluded(self, file_indexer):
        """Files not matching include patterns (e.g. .py) should not appear."""
        discovered = file_indexer._discover_files()
        names = {p.name for p in discovered}
        assert "script.py" not in names

    def test_exclude_patterns_remove_files(self, file_indexer, workspace_dir):
        """Files under the excluded/ directory should be filtered out."""
        discovered = file_indexer._discover_files()
        names = {p.name for p in discovered}
        assert "ignored.md" not in names

    def test_max_file_size_kb_filters_oversized_files(
        self, mock_vector_store, mock_embedding_provider, workspace_dir
    ):
        """Files exceeding max_file_size_kb should be omitted."""
        # Write a file whose content just exceeds 1 KB
        big_file = workspace_dir / "big.md"
        big_file.write_bytes(b"x" * 1025)

        tiny_config = FileIndexingConfig(
            include=["**/*.md"],
            exclude=[],
            max_file_size_kb=1,  # 1 KB limit
        )
        indexer = FileIndexer(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            workspace_path=workspace_dir,
            config=tiny_config,
        )
        discovered = indexer._discover_files()
        names = {p.name for p in discovered}
        assert "big.md" not in names

    def test_directories_are_ignored(self, file_indexer, workspace_dir):
        """Directories matching the pattern should not appear in results."""
        # subdir itself matches **/*.md patterns during glob but is a directory
        discovered = file_indexer._discover_files()
        assert all(p.is_file() for p in discovered)

    def test_empty_workspace_returns_empty_list(
        self, mock_vector_store, mock_embedding_provider, tmp_path
    ):
        """A workspace with no matching files should return an empty list."""
        config = FileIndexingConfig(include=["**/*.md"], exclude=[])
        indexer = FileIndexer(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            workspace_path=tmp_path,
            config=config,
        )
        assert indexer._discover_files() == []


# ---------------------------------------------------------------------------
# TestChunkFile
# ---------------------------------------------------------------------------


class TestChunkFile:
    """Tests for _chunk_file method."""

    def test_markdown_file_uses_heading_aware_separators(self, file_indexer):
        """Markdown files should be chunked with heading-aware separators."""
        content = "# Heading\n\nParagraph one.\n\n## Section\n\nParagraph two."
        # This is a behavioural assertion — we just verify chunking runs without error
        chunks = file_indexer._chunk_file(content, "notes.md")
        assert isinstance(chunks, list)

    def test_non_markdown_file_uses_default_separators(self, file_indexer):
        """Non-markdown files should use RecursiveCharacterTextSplitter defaults."""
        content = "Line one.\nLine two.\nLine three."
        chunks = file_indexer._chunk_file(content, "readme.txt")
        assert isinstance(chunks, list)

    def test_chunk_metadata_includes_required_fields(self, file_indexer):
        """Every chunk must carry source_type, file_path, and chunk_index metadata."""
        content = "Some content for metadata testing."
        chunks = file_indexer._chunk_file(content, "notes.md")
        assert len(chunks) >= 1
        for i, chunk in enumerate(chunks):
            assert chunk.metadata["source_type"] == "file"
            assert chunk.metadata["file_path"] == "notes.md"
            assert chunk.metadata["chunk_index"] == i

    def test_chunk_id_format(self, file_indexer):
        """Chunk IDs must follow the 'file:{path}:chunk:{index}' convention."""
        content = "ID format test."
        chunks = file_indexer._chunk_file(content, "subdir/deep.md")
        assert len(chunks) >= 1
        for i, chunk in enumerate(chunks):
            assert chunk.id == f"file:subdir/deep.md:chunk:{i}"

    def test_empty_content_produces_no_chunks(self, file_indexer):
        """An empty file should produce zero chunks."""
        chunks = file_indexer._chunk_file("", "empty.md")
        assert chunks == []

    def test_short_content_produces_single_chunk(self, file_indexer):
        """Content well below chunk_size should produce exactly one chunk."""
        content = "Short."
        chunks = file_indexer._chunk_file(content, "short.md")
        assert len(chunks) == 1
        assert chunks[0].content == "Short."


# ---------------------------------------------------------------------------
# TestIndexWorkspace
# ---------------------------------------------------------------------------


class TestIndexWorkspace:
    """Tests for index_workspace method."""

    @pytest.mark.asyncio
    async def test_indexes_new_files_when_no_stored_hashes(
        self, file_indexer, mock_vector_store, mock_embedding_provider
    ):
        """All discovered files should be indexed when the hash store is empty."""
        mock_vector_store.get_file_hashes.return_value = {}

        result = await file_indexer.index_workspace()

        # At least one file should have been indexed
        assert result.files_indexed > 0
        assert result.files_skipped == 0
        mock_vector_store.set_file_hash.assert_called()

    @pytest.mark.asyncio
    async def test_skips_unchanged_files(self, file_indexer, mock_vector_store, workspace_dir):
        """Files whose hash matches the stored hash should be skipped."""
        notes_path = workspace_dir / "notes.md"
        stored_hash = hashlib.sha256(notes_path.read_bytes()).hexdigest()

        # Pretend notes.md is already indexed with the current hash
        mock_vector_store.get_file_hashes.return_value = {"notes.md": stored_hash}

        result = await file_indexer.index_workspace()

        assert result.files_skipped >= 1

    @pytest.mark.asyncio
    async def test_reindexes_changed_files(self, file_indexer, mock_vector_store, workspace_dir):
        """Files whose stored hash differs from the current hash should be re-indexed."""
        # Give notes.md a deliberately wrong stored hash
        mock_vector_store.get_file_hashes.return_value = {"notes.md": "outdated_hash"}

        result = await file_indexer.index_workspace()

        # notes.md (and any other files) must have been indexed
        assert result.files_indexed >= 1
        mock_vector_store.delete_by_metadata.assert_called()

    @pytest.mark.asyncio
    async def test_force_reindexes_all_files(self, file_indexer, mock_vector_store, workspace_dir):
        """force=True should bypass hash comparison and index every discovered file."""
        notes_path = workspace_dir / "notes.md"
        current_hash = hashlib.sha256(notes_path.read_bytes()).hexdigest()

        # Even though the hash matches, force=True must re-index
        mock_vector_store.get_file_hashes.return_value = {"notes.md": current_hash}

        result = await file_indexer.index_workspace(force=True)

        assert result.files_skipped == 0
        assert result.files_indexed > 0

    @pytest.mark.asyncio
    async def test_removes_stale_hashes_for_deleted_files(
        self, file_indexer, mock_vector_store
    ):
        """Hash entries for files that no longer exist should be cleaned up."""
        mock_vector_store.get_file_hashes.return_value = {
            "ghost.md": "somehash",
        }

        await file_indexer.index_workspace()

        mock_vector_store.remove_file_hash.assert_called_with("ghost.md")
        mock_vector_store.delete_by_metadata.assert_any_call("file_path", "ghost.md")

    @pytest.mark.asyncio
    async def test_error_on_one_file_does_not_abort_others(
        self, mock_vector_store, mock_embedding_provider, workspace_dir, file_indexer_config
    ):
        """An exception for a single file should increment files_errored and continue."""
        call_count = 0

        async def embed_with_one_failure(texts):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated embedding failure")
            return [[0.1, 0.2, 0.3]] * len(texts)

        mock_embedding_provider.embed_texts.side_effect = embed_with_one_failure
        mock_vector_store.get_file_hashes.return_value = {}

        indexer = FileIndexer(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
            workspace_path=workspace_dir,
            config=file_indexer_config,
        )
        result = await indexer.index_workspace()

        assert result.files_errored >= 1
        # Other files should still have been processed
        assert result.files_indexed >= 1

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self, file_indexer, mock_vector_store):
        """The returned IndexingResult should reflect the actual operation breakdown."""
        mock_vector_store.get_file_hashes.return_value = {}

        result = await file_indexer.index_workspace()

        assert isinstance(result, IndexingResult)
        assert result.files_indexed + result.files_skipped + result.files_errored > 0

    @pytest.mark.asyncio
    async def test_duration_ms_is_populated(self, file_indexer, mock_vector_store):
        """duration_ms should be a positive float after a completed run."""
        mock_vector_store.get_file_hashes.return_value = {}

        result = await file_indexer.index_workspace()

        assert result.duration_ms > 0.0


# ---------------------------------------------------------------------------
# TestIndexFile
# ---------------------------------------------------------------------------


class TestIndexFile:
    """Tests for index_file method."""

    @pytest.mark.asyncio
    async def test_indexes_a_single_file_successfully(
        self, file_indexer, mock_vector_store, mock_embedding_provider
    ):
        """index_file should return a positive chunk count for a normal file."""
        mock_vector_store.get_file_hashes.return_value = {}

        count = await file_indexer.index_file("notes.md")

        assert count >= 1
        mock_vector_store.set_file_hash.assert_called_once()
        mock_embedding_provider.embed_texts.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_unchanged_file(self, file_indexer, mock_vector_store, workspace_dir):
        """index_file should return 0 when the stored hash matches the file content."""
        notes_path = workspace_dir / "notes.md"
        current_hash = hashlib.sha256(notes_path.read_bytes()).hexdigest()
        mock_vector_store.get_file_hashes.return_value = {"notes.md": current_hash}

        count = await file_indexer.index_file("notes.md")

        assert count == 0
        mock_vector_store.set_file_hash.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_bypasses_hash_check(
        self, file_indexer, mock_vector_store, workspace_dir
    ):
        """force=True should re-index even when the stored hash matches."""
        notes_path = workspace_dir / "notes.md"
        current_hash = hashlib.sha256(notes_path.read_bytes()).hexdigest()
        mock_vector_store.get_file_hashes.return_value = {"notes.md": current_hash}

        count = await file_indexer.index_file("notes.md", force=True)

        assert count >= 1
        mock_vector_store.set_file_hash.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_value_error_for_path_escape(self, file_indexer):
        """Paths that traverse outside the workspace root must raise ValueError."""
        with pytest.raises(ValueError, match="escapes workspace root"):
            await file_indexer.index_file("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_raises_file_not_found_for_missing_file(self, file_indexer):
        """index_file should raise FileNotFoundError when the target does not exist."""
        with pytest.raises(FileNotFoundError):
            await file_indexer.index_file("nonexistent.md")


# ---------------------------------------------------------------------------
# TestRemoveFile
# ---------------------------------------------------------------------------


class TestRemoveFile:
    """Tests for remove_file method."""

    @pytest.mark.asyncio
    async def test_delegates_to_delete_by_metadata_and_remove_file_hash(
        self, file_indexer, mock_vector_store
    ):
        """remove_file should call delete_by_metadata and remove_file_hash."""
        mock_vector_store.delete_by_metadata.return_value = 3

        count = await file_indexer.remove_file("notes.md")

        mock_vector_store.delete_by_metadata.assert_called_once_with("file_path", "notes.md")
        mock_vector_store.remove_file_hash.assert_called_once_with("notes.md")
        assert count == 3


# ---------------------------------------------------------------------------
# TestComputeFileHash
# ---------------------------------------------------------------------------


class TestComputeFileHash:
    """Tests for _compute_file_hash module-level function."""

    def test_returns_consistent_sha256_hex_digest(self, tmp_path):
        """The same file should always produce the same hash."""
        f = tmp_path / "file.txt"
        f.write_text("deterministic content", encoding="utf-8")

        expected = hashlib.sha256(f.read_bytes()).hexdigest()
        assert _compute_file_hash(f) == expected

    def test_different_content_produces_different_hash(self, tmp_path):
        """Two files with different content must not share a hash."""
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("content A", encoding="utf-8")
        b.write_text("content B", encoding="utf-8")

        assert _compute_file_hash(a) != _compute_file_hash(b)
