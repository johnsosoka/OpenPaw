"""Workspace file indexer for semantic search over workspace files."""

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpaw.stores.vector.base import BaseVectorStore, VectorDocument
from openpaw.stores.vector.embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class IndexingResult:
    """Summary of an indexing operation."""

    files_indexed: int = 0
    files_skipped: int = 0  # Unchanged (hash match)
    files_errored: int = 0
    chunks_created: int = 0
    duration_ms: float = 0.0


class FileIndexer:
    """Indexes workspace files into the vector store for semantic search.

    Uses SHA-256 content hashing for change detection. Only re-indexes
    files whose content has changed since last indexing.
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embedding_provider: BaseEmbeddingProvider,
        workspace_path: Path,
        config: Any,  # FileIndexingConfig
    ):
        """Initialize the file indexer.

        Args:
            vector_store: Vector store for persisting embeddings.
            embedding_provider: Provider for generating embeddings.
            workspace_path: Absolute path to the workspace root.
            config: FileIndexingConfig with include/exclude patterns and chunk settings.
        """
        self._store = vector_store
        self._embeddings = embedding_provider
        self._workspace_path = workspace_path
        self._config = config
        logger.info("FileIndexer initialized")

    async def index_workspace(self, force: bool = False) -> IndexingResult:
        """Index all matching workspace files.

        Discovers files via include/exclude glob patterns, computes SHA-256
        hashes for change detection, and only re-indexes files that have
        changed since the last run (unless force=True). Stale hash entries
        for deleted files are cleaned up automatically.

        Args:
            force: If True, re-index all files regardless of hash.

        Returns:
            IndexingResult with per-file and chunk counts.
        """
        start = time.monotonic()
        result = IndexingResult()

        discovered = self._discover_files()
        discovered_paths = {str(p.relative_to(self._workspace_path)) for p in discovered}

        stored_hashes = await self._store.get_file_hashes()

        for path in discovered:
            relative_path = str(path.relative_to(self._workspace_path))
            try:
                content_hash = _compute_file_hash(path)

                if not force and stored_hashes.get(relative_path) == content_hash:
                    result.files_skipped += 1
                    continue

                # Delete stale chunks before re-indexing
                await self._store.delete_by_metadata("file_path", relative_path)

                content = path.read_text(encoding="utf-8", errors="replace")
                chunks = self._chunk_file(content, relative_path)

                if chunks:
                    texts = [chunk.content for chunk in chunks]
                    embeddings = await self._embeddings.embed_texts(texts)
                    for chunk, embedding in zip(chunks, embeddings):
                        chunk.embedding = embedding
                    await self._store.add_documents(chunks)

                chunk_count = len(chunks)
                await self._store.set_file_hash(relative_path, content_hash, chunk_count)

                result.files_indexed += 1
                result.chunks_created += chunk_count
                logger.debug(f"Indexed {relative_path} ({chunk_count} chunks)")

            except Exception as e:
                logger.warning(f"Error indexing {relative_path}: {e}")
                result.files_errored += 1

        # Remove hash entries for files that no longer exist
        for stored_path in stored_hashes:
            if stored_path not in discovered_paths:
                await self._store.remove_file_hash(stored_path)
                await self._store.delete_by_metadata("file_path", stored_path)
                logger.debug(f"Removed stale index entry for deleted file: {stored_path}")

        result.duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            f"Workspace indexing complete: {result.files_indexed} indexed, "
            f"{result.files_skipped} skipped, {result.files_errored} errored, "
            f"{result.chunks_created} chunks ({result.duration_ms:.0f}ms)"
        )
        return result

    async def index_file(self, relative_path: str, force: bool = False) -> int:
        """Index a single workspace file.

        Validates the path is within the workspace, checks for changes via
        hash comparison, and re-indexes only if necessary (or if force=True).

        Args:
            relative_path: Path relative to workspace root.
            force: If True, re-index even if the file hash is unchanged.

        Returns:
            Number of chunks created (0 if skipped or file is empty).

        Raises:
            ValueError: If the resolved path escapes the workspace root.
            FileNotFoundError: If the file does not exist.
        """
        absolute_path = (self._workspace_path / relative_path).resolve()
        if not absolute_path.is_relative_to(self._workspace_path.resolve()):
            raise ValueError(f"Path escapes workspace root: {relative_path}")

        if not absolute_path.is_file():
            raise FileNotFoundError(f"File not found: {relative_path}")

        content_hash = _compute_file_hash(absolute_path)
        stored_hashes = await self._store.get_file_hashes()

        if not force and stored_hashes.get(relative_path) == content_hash:
            logger.debug(f"Skipping unchanged file: {relative_path}")
            return 0

        await self._store.delete_by_metadata("file_path", relative_path)

        content = absolute_path.read_text(encoding="utf-8", errors="replace")
        chunks = self._chunk_file(content, relative_path)

        if chunks:
            texts = [chunk.content for chunk in chunks]
            embeddings = await self._embeddings.embed_texts(texts)
            for chunk, embedding in zip(chunks, embeddings):
                chunk.embedding = embedding
            await self._store.add_documents(chunks)

        chunk_count = len(chunks)
        await self._store.set_file_hash(relative_path, content_hash, chunk_count)
        logger.info(f"Indexed {relative_path} ({chunk_count} chunks)")
        return chunk_count

    async def remove_file(self, relative_path: str) -> int:
        """Remove all chunks for a file from the vector store.

        Args:
            relative_path: Path relative to workspace root.

        Returns:
            Number of chunks deleted.
        """
        count = await self._store.delete_by_metadata("file_path", relative_path)
        await self._store.remove_file_hash(relative_path)
        logger.info(f"Removed {count} chunks for file: {relative_path}")
        return count

    def _discover_files(self) -> list[Path]:
        """Discover workspace files matching include/exclude patterns.

        Globs include patterns against the workspace root, subtracts exclude
        matches, and filters out files exceeding the configured size limit.

        Returns:
            Sorted list of matching Path objects.
        """
        included: set[Path] = set()
        for pattern in self._config.include:
            included.update(self._workspace_path.glob(pattern))

        excluded: set[Path] = set()
        for pattern in self._config.exclude:
            excluded.update(self._workspace_path.glob(pattern))

        max_bytes = self._config.max_file_size_kb * 1024
        result = []
        for path in included - excluded:
            if not path.is_file():
                continue
            try:
                if path.stat().st_size <= max_bytes:
                    result.append(path)
                else:
                    logger.debug(f"Skipping oversized file: {path.relative_to(self._workspace_path)}")
            except OSError as e:
                logger.warning(f"Could not stat {path}: {e}")

        return sorted(result)

    def _chunk_file(self, content: str, relative_path: str) -> list[VectorDocument]:
        """Split file content into overlapping chunks.

        Uses markdown-aware separators for .md files and default separators
        for all other file types. Each chunk becomes a VectorDocument with
        metadata identifying its source file and position.

        Args:
            content: Full text content of the file.
            relative_path: Path relative to workspace root (used in metadata and IDs).

        Returns:
            List of VectorDocument instances without embeddings.
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        if relative_path.endswith(".md"):
            separators = ["\n## ", "\n### ", "\n#### ", "\n\n", "\n", " ", ""]
        else:
            separators = None  # Use RecursiveCharacterTextSplitter defaults

        splitter_kwargs: dict[str, Any] = {
            "chunk_size": self._config.chunk_size,
            "chunk_overlap": self._config.chunk_overlap,
        }
        if separators is not None:
            splitter_kwargs["separators"] = separators

        splitter = RecursiveCharacterTextSplitter(**splitter_kwargs)
        raw_chunks = splitter.split_text(content)

        documents = []
        for i, chunk_text in enumerate(raw_chunks):
            doc = VectorDocument(
                id=f"file:{relative_path}:chunk:{i}",
                content=chunk_text,
                metadata={
                    "source_type": "file",
                    "file_path": relative_path,
                    "chunk_index": i,
                },
            )
            documents.append(doc)

        return documents


def _compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hex digest for a file.

    Args:
        path: Absolute path to the file.

    Returns:
        Hex string of the SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()
