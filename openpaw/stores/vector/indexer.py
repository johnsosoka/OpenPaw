"""Conversation indexer for semantic search over archived conversations."""

import json
import logging
from pathlib import Path
from typing import Any

from openpaw.stores.vector.base import BaseVectorStore, VectorDocument
from openpaw.stores.vector.embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class ConversationIndexer:
    """Indexes conversation archives into the vector store.

    Chunks conversations using a sliding window of 2-3 turn pairs (human + AI).
    Each chunk becomes a VectorDocument with metadata for filtering.
    """

    WINDOW_SIZE = 3  # Number of turn pairs per chunk
    OVERLAP = 1      # Overlap between chunks

    def __init__(self, vector_store: BaseVectorStore, embedding_provider: BaseEmbeddingProvider):
        """Initialize the conversation indexer.

        Args:
            vector_store: Vector store for persisting embeddings.
            embedding_provider: Provider for generating embeddings.
        """
        self._store = vector_store
        self._embeddings = embedding_provider
        logger.info("ConversationIndexer initialized")

    async def index_archive(self, archive_json_path: Path) -> int:
        """Index a conversation archive JSON file.

        Reads the JSON archive, extracts turn pairs, creates chunks with a
        sliding window, generates embeddings, and stores in the vector database.

        Args:
            archive_json_path: Path to the conversation JSON sidecar file.

        Returns:
            Number of chunks indexed.
        """
        # Read JSON archive
        try:
            data = json.loads(archive_json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to read archive {archive_json_path}: {e}")
            return 0

        conversation_id = data.get("conversation_id", "")
        session_key = data.get("session_key", "")
        messages = data.get("messages", [])

        if not messages:
            logger.debug(f"Empty archive, skipping: {conversation_id}")
            return 0

        # Build turn pairs (human + ai response)
        turns = self._extract_turns(messages)
        if not turns:
            logger.debug(f"No complete turns found in archive: {conversation_id}")
            return 0

        # Create chunks with sliding window
        chunks = self._create_chunks(turns, conversation_id, session_key)
        if not chunks:
            logger.debug(f"No chunks created for archive: {conversation_id}")
            return 0

        # Generate embeddings
        texts = [chunk.content for chunk in chunks]
        try:
            embeddings = await self._embeddings.embed_texts(texts)
        except Exception as e:
            logger.error(f"Failed to generate embeddings for {conversation_id}: {e}")
            return 0

        # Attach embeddings to chunks
        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        # Store in vector database
        count = await self._store.add_documents(chunks)
        logger.info(f"Indexed {count} chunks for conversation {conversation_id}")
        return count

    async def remove_conversation(self, conversation_id: str) -> int:
        """Remove all chunks for a conversation from the vector store.

        Args:
            conversation_id: Conversation ID to remove.

        Returns:
            Number of chunks deleted.
        """
        count = await self._store.delete_by_metadata("conversation_id", conversation_id)
        logger.info(f"Removed {count} chunks for conversation {conversation_id}")
        return count

    def _extract_turns(self, messages: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Extract turn pairs (human message + AI response) from messages.

        Args:
            messages: List of message dictionaries from JSON archive.

        Returns:
            List of (human_msg, ai_msg) tuples.
        """
        turns = []
        current_human = None

        for msg in messages:
            role = msg.get("role")
            if role == "human":
                current_human = msg
            elif role == "ai" and current_human:
                turns.append((current_human, msg))
                current_human = None

        return turns

    def _create_chunks(
        self,
        turns: list[tuple[dict[str, Any], dict[str, Any]]],
        conversation_id: str,
        session_key: str,
    ) -> list[VectorDocument]:
        """Create overlapping chunks from turn pairs.

        Uses a sliding window to create chunks of WINDOW_SIZE turns with
        OVERLAP between consecutive chunks.

        Args:
            turns: List of (human_msg, ai_msg) tuples.
            conversation_id: Conversation ID for metadata.
            session_key: Session key for metadata.

        Returns:
            List of VectorDocument instances (without embeddings).
        """
        chunks = []

        for i in range(0, len(turns), self.WINDOW_SIZE - self.OVERLAP):
            window = turns[i:i + self.WINDOW_SIZE]
            if not window:
                break

            # Build chunk content
            lines = []
            timestamps = []

            for human_msg, ai_msg in window:
                lines.append(f"User: {human_msg.get('content', '')}")
                lines.append(f"Agent: {ai_msg.get('content', '')}")

                # Collect timestamps
                if human_msg.get("timestamp"):
                    timestamps.append(human_msg["timestamp"])

            content = "\n".join(lines)
            chunk_id = f"{conversation_id}:chunk:{i}"

            metadata = {
                "conversation_id": conversation_id,
                "session_key": session_key,
                "chunk_index": i,
            }

            if timestamps:
                metadata["timestamp_start"] = timestamps[0]
                metadata["timestamp_end"] = timestamps[-1]

            chunks.append(VectorDocument(id=chunk_id, content=content, metadata=metadata))

        return chunks
