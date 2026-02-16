"""Conversation archiving for OpenPaw.

This module handles reading conversations from LangGraph checkpointers and
writing them to human-readable markdown and machine-readable JSON formats.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from openpaw.core.timezone import format_for_display

logger = logging.getLogger(__name__)


@dataclass
class ConversationArchive:
    """Metadata for an archived conversation.

    Attributes:
        conversation_id: Unique conversation identifier (e.g., "conv_2026-02-07T14-30-00").
        session_key: Session key (e.g., "telegram:123456").
        workspace_name: Name of the workspace.
        started_at: When the conversation started.
        ended_at: When the conversation ended (archive time).
        message_count: Number of messages in the conversation.
        summary: Optional summary text (from /compact), None for regular archives.
        markdown_path: Path to the markdown archive file.
        json_path: Path to the JSON archive file.
        tags: Optional metadata tags (e.g., ["shutdown", "manual"]).
    """

    conversation_id: str
    session_key: str
    workspace_name: str
    started_at: datetime
    ended_at: datetime
    message_count: int
    markdown_path: Path
    json_path: Path
    summary: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with ISO 8601 datetime strings.
        """
        return {
            "conversation_id": self.conversation_id,
            "session_key": self.session_key,
            "workspace_name": self.workspace_name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "message_count": self.message_count,
            "summary": self.summary,
            "tags": self.tags,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any], workspace_path: Path) -> "ConversationArchive":
        """Create instance from JSON data.

        Args:
            data: Dictionary from JSON file.
            workspace_path: Path to workspace root (for reconstructing file paths).

        Returns:
            ConversationArchive instance.
        """
        conversation_id = data["conversation_id"]
        archive_dir = workspace_path / "memory" / "conversations"

        return cls(
            conversation_id=conversation_id,
            session_key=data["session_key"],
            workspace_name=data["workspace_name"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"]),
            message_count=data["message_count"],
            summary=data.get("summary"),
            markdown_path=archive_dir / f"{conversation_id}.md",
            json_path=archive_dir / f"{conversation_id}.json",
            tags=data.get("tags", []),
        )


class ConversationArchiver:
    """Archives conversations from the checkpointer to markdown + JSON files.

    Archives are stored in: {workspace}/memory/conversations/
    Each archive consists of two files:
    - {conversation_id}.md  — Human-readable markdown
    - {conversation_id}.json — Machine-readable, includes tool_calls
    """

    def __init__(self, workspace_path: Path, workspace_name: str, timezone: str = "UTC", indexer: Any = None):
        """Initialize archiver.

        Args:
            workspace_path: Path to workspace root.
            workspace_name: Name of the workspace.
            timezone: IANA timezone identifier for display timestamps (default: "UTC").
            indexer: Optional ConversationIndexer for vector search.
        """
        self._workspace_path = Path(workspace_path)
        self._workspace_name = workspace_name
        self._timezone = timezone
        self._indexer = indexer
        self._archive_dir = self._workspace_path / "memory" / "conversations"
        self._archive_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"ConversationArchiver initialized: {self._archive_dir}")

    async def archive(
        self,
        checkpointer: Any,
        thread_id: str,
        session_key: str,
        conversation_id: str,
        summary: str | None = None,
        tags: list[str] | None = None,
    ) -> ConversationArchive | None:
        """Archive a conversation from the checkpointer.

        Reads messages from checkpointer, writes markdown + JSON files.

        Args:
            checkpointer: LangGraph checkpointer (AsyncSqliteSaver).
            thread_id: Thread ID for the conversation.
            session_key: Session key (e.g., "telegram:123456").
            conversation_id: Conversation ID (e.g., "conv_2026-02-07T14-30-00").
            summary: Optional summary text (from /compact).
            tags: Optional metadata tags (e.g., ["shutdown", "manual"]).

        Returns:
            ConversationArchive if successful, None if no messages found.
        """
        # Read messages from checkpointer
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config)

        if not checkpoint_tuple:
            logger.warning(f"No checkpoint found for thread_id: {thread_id}")
            return None

        messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
        if not messages:
            logger.warning(f"Empty conversation for thread_id: {thread_id}")
            return None

        # Extract timestamps from messages
        started_at = self._extract_timestamp(messages[0])
        ended_at = datetime.now(UTC)

        # Build archive metadata
        archive = ConversationArchive(
            conversation_id=conversation_id,
            session_key=session_key,
            workspace_name=self._workspace_name,
            started_at=started_at,
            ended_at=ended_at,
            message_count=len(messages),
            summary=summary,
            markdown_path=self._archive_dir / f"{conversation_id}.md",
            json_path=self._archive_dir / f"{conversation_id}.json",
            tags=tags or [],
        )

        # Write markdown file
        self._write_markdown(archive, messages)

        # Write JSON file
        self._write_json(archive, messages)

        logger.info(
            f"Archived conversation {conversation_id} ({len(messages)} messages) "
            f"to {archive.markdown_path.name}"
        )

        # Index for vector search if indexer is set
        if self._indexer:
            try:
                chunks_indexed = await self._indexer.index_archive(archive.json_path)
                logger.info(f"Indexed {chunks_indexed} chunks for conversation {conversation_id}")
            except Exception as e:
                logger.warning(f"Failed to index conversation {conversation_id}: {e}")

        return archive

    def _extract_timestamp(self, message: BaseMessage) -> datetime:
        """Extract timestamp from message or use current time.

        Args:
            message: LangChain message object.

        Returns:
            Timestamp as datetime (UTC).
        """
        # Try to get timestamp from additional_kwargs
        timestamp = message.additional_kwargs.get("timestamp")
        if timestamp:
            if isinstance(timestamp, datetime):
                return timestamp
            try:
                return datetime.fromisoformat(timestamp)
            except (ValueError, TypeError):
                pass

        # Fallback to current time
        return datetime.now(UTC)

    def _write_markdown(self, archive: ConversationArchive, messages: list[BaseMessage]) -> None:
        """Write human-readable markdown archive.

        Args:
            archive: Archive metadata.
            messages: List of conversation messages.
        """
        lines = [
            "# Conversation Archive",
            "",
            f"**ID:** {archive.conversation_id}",
            f"**Session:** {archive.session_key}",
            f"**Workspace:** {archive.workspace_name}",
            f"**Started:** {format_for_display(archive.started_at, self._timezone, '%Y-%m-%d %H:%M:%S %Z')}",
            f"**Ended:** {format_for_display(archive.ended_at, self._timezone, '%Y-%m-%d %H:%M:%S %Z')}",
            f"**Messages:** {archive.message_count}",
            "",
        ]

        # Add summary section if present
        if archive.summary:
            lines.extend([
                "---",
                "",
                "## Summary",
                "",
                archive.summary,
                "",
            ])

        lines.append("---")
        lines.append("")

        # Format each message
        for i, message in enumerate(messages, 1):
            timestamp = self._extract_timestamp(message)
            timestamp_str = format_for_display(timestamp, self._timezone, '%Y-%m-%d %H:%M:%S %Z')

            if isinstance(message, HumanMessage):
                lines.append(f"**[User]** {timestamp_str}")
                lines.append("")
                lines.append(str(message.content))
                lines.append("")
                lines.append("---")
                lines.append("")

            elif isinstance(message, AIMessage):
                lines.append(f"**[Agent]** {timestamp_str}")
                lines.append("")
                lines.append(str(message.content))
                lines.append("")

                # Include tool calls if present
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tool_call in message.tool_calls:
                        lines.append(f"**[Tool Call: {tool_call.get('name', 'unknown')}]**")
                        lines.append("")
                        args = tool_call.get("args", {})
                        for key, value in args.items():
                            lines.append(f"- {key}: {value}")
                        lines.append("")

                lines.append("---")
                lines.append("")

            elif isinstance(message, ToolMessage):
                lines.append(f"**[Tool Result]** {timestamp_str}")
                lines.append("")
                lines.append(str(message.content))
                lines.append("")
                lines.append("---")
                lines.append("")

        # Write to file
        archive.markdown_path.write_text("\n".join(lines), encoding="utf-8")

    def _write_json(self, archive: ConversationArchive, messages: list[BaseMessage]) -> None:
        """Write machine-readable JSON archive.

        Args:
            archive: Archive metadata.
            messages: List of conversation messages.
        """
        # Build message list
        json_messages: list[dict[str, Any]] = []
        for message in messages:
            timestamp = self._extract_timestamp(message)

            msg_dict: dict[str, Any] = {
                "timestamp": timestamp.isoformat(),
                "tool_calls": None,
                "tool_call_id": None,
            }

            if isinstance(message, HumanMessage):
                msg_dict["role"] = "human"
                msg_dict["content"] = str(message.content)

            elif isinstance(message, AIMessage):
                msg_dict["role"] = "ai"
                msg_dict["content"] = str(message.content)

                # Include tool calls if present
                if hasattr(message, "tool_calls") and message.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "name": tc.get("name"),
                            "args": tc.get("args", {}),
                            "id": tc.get("id"),
                        }
                        for tc in message.tool_calls
                    ]

            elif isinstance(message, ToolMessage):
                msg_dict["role"] = "tool"
                msg_dict["content"] = str(message.content)
                msg_dict["tool_call_id"] = getattr(message, "tool_call_id", None)

            else:
                # Unknown message type - store as generic
                msg_dict["role"] = "unknown"
                msg_dict["content"] = str(message.content)

            json_messages.append(msg_dict)

        # Build full JSON structure
        data = {
            **archive.to_dict(),
            "messages": json_messages,
        }

        # Write to file
        archive.json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def list_archives(self, limit: int = 50) -> list[ConversationArchive]:
        """List archived conversations, most recent first.

        Reads JSON sidecars to build archive metadata.

        Args:
            limit: Maximum number of archives to return.

        Returns:
            List of ConversationArchive objects, sorted by ended_at descending.
        """
        archives = []

        # Scan for JSON files
        for json_file in self._archive_dir.glob("*.json"):
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                archive = ConversationArchive.from_json(data, self._workspace_path)
                archives.append(archive)

            except Exception as e:
                logger.error(f"Failed to load archive {json_file.name}: {e}")
                continue

        # Sort by ended_at descending (most recent first)
        archives.sort(key=lambda a: a.ended_at, reverse=True)

        # Apply limit
        return archives[:limit]
