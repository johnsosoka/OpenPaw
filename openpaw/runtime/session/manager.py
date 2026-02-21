"""Session manager for tracking conversation threads per session.

This module handles conversation lifecycle: tracking active conversation IDs,
rotating conversations via /new command, and persisting session state across
restarts.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from openpaw.model.session import SessionState

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages conversation threads per session with persistent state.

    Tracks active conversation IDs for each session_key, enabling conversation
    rotation via /new command while maintaining the same session_key.

    Thread-safe for concurrent access. State persists to JSON file.

    Example:
        >>> manager = SessionManager(Path("agent_workspaces/gilfoyle"))
        >>> thread_id = manager.get_thread_id("telegram:123456")
        # Returns: "telegram:123456:conv_2026-02-07T14-30-00"
        >>> old_conv = manager.new_conversation("telegram:123456")
        # Rotates to new conversation, returns old conversation ID for archiving
    """

    OPENPAW_DIR = ".openpaw"
    STATE_FILE = "sessions.json"

    def __init__(self, workspace_path: Path):
        """Initialize the session manager.

        Args:
            workspace_path: Path to the agent workspace root.
        """
        self.workspace_path = Path(workspace_path)
        self._openpaw_dir = self.workspace_path / self.OPENPAW_DIR
        self._state_file = self._openpaw_dir / self.STATE_FILE
        self._lock = Lock()
        self._sessions: dict[str, SessionState] = {}

        # Ensure .openpaw directory exists
        self._openpaw_dir.mkdir(parents=True, exist_ok=True)

        # Load existing state
        self._load()

        logger.info(f"SessionManager initialized: {self._state_file}")

    def _load(self) -> None:
        """Load session state from JSON file. Thread-safe."""
        with self._lock:
            if not self._state_file.exists():
                logger.debug(f"State file does not exist: {self._state_file}")
                self._sessions = {}
                return

            try:
                with self._state_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    logger.error(f"Invalid state format (expected dict): {self._state_file}")
                    self._sessions = {}
                    return

                # Parse each session state
                self._sessions = {}
                for session_key, session_data in data.items():
                    try:
                        self._sessions[session_key] = SessionState.from_dict(session_data)
                    except Exception as e:
                        logger.error(f"Failed to parse session {session_key}: {e}")
                        continue

                logger.debug(f"Loaded {len(self._sessions)} session(s) from state")

            except json.JSONDecodeError as e:
                logger.error(f"Corrupted state file {self._state_file}: {e}")
                self._sessions = {}
            except Exception as e:
                logger.error(f"Unexpected error loading {self._state_file}: {e}", exc_info=True)
                self._sessions = {}

    def _save(self) -> None:
        """Persist session state to JSON file. Thread-safe, atomic write.

        Uses tmp file + rename pattern for atomicity.
        Caller must hold self._lock.
        """
        try:
            # Convert sessions to dict
            data = {
                session_key: state.to_dict()
                for session_key, state in self._sessions.items()
            }

            # Atomic write: write to temp file, then rename
            tmp_path = self._state_file.with_suffix(".tmp")

            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

            # Atomic rename (POSIX guarantees atomicity)
            tmp_path.rename(self._state_file)

            logger.debug(f"Saved {len(self._sessions)} session(s) to state")

        except Exception as e:
            logger.error(f"Failed to save sessions to {self._state_file}: {e}", exc_info=True)
            raise

    def _create_conversation_id(self) -> str:
        """Generate a new conversation ID with timestamp.

        Returns:
            Conversation ID in format "conv_2026-02-07T14-30-00-123456".
        """
        now = datetime.now(UTC)
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        microseconds = now.strftime("%f")
        return f"conv_{timestamp}-{microseconds}"

    def get_thread_id(self, session_key: str) -> str:
        """Get the thread ID for a session, creating new session if needed.

        Thread ID format: "{session_key}:{conversation_id}"

        Args:
            session_key: Session identifier (e.g., "telegram:123456").

        Returns:
            Full thread ID for use with checkpointer.
        """
        with self._lock:
            # Create new session if doesn't exist
            if session_key not in self._sessions:
                conversation_id = self._create_conversation_id()
                self._sessions[session_key] = SessionState(
                    conversation_id=conversation_id,
                    started_at=datetime.now(UTC),
                )
                self._save()
                logger.info(f"Created new session: {session_key} with conversation {conversation_id}")

            return f"{session_key}:{self._sessions[session_key].conversation_id}"

    def new_conversation(self, session_key: str) -> str:
        """Start a new conversation for a session, rotating the conversation ID.

        Args:
            session_key: Session identifier.

        Returns:
            The OLD conversation ID (for archiving).
        """
        with self._lock:
            # Get or create session
            if session_key not in self._sessions:
                old_conversation_id = self._create_conversation_id()
                self._sessions[session_key] = SessionState(
                    conversation_id=old_conversation_id,
                    started_at=datetime.now(UTC),
                )
            else:
                old_conversation_id = self._sessions[session_key].conversation_id

            # Create new conversation
            new_conversation_id = self._create_conversation_id()
            self._sessions[session_key] = SessionState(
                conversation_id=new_conversation_id,
                started_at=datetime.now(UTC),
            )

            self._save()

            logger.info(
                f"Rotated conversation for {session_key}: "
                f"{old_conversation_id} -> {new_conversation_id}"
            )

            return old_conversation_id

    def get_state(self, session_key: str) -> SessionState | None:
        """Retrieve session state for a session key.

        Args:
            session_key: Session identifier.

        Returns:
            SessionState instance if exists, None otherwise.
        """
        with self._lock:
            return self._sessions.get(session_key)

    def increment_message_count(self, session_key: str) -> None:
        """Increment message count and update last active timestamp.

        Args:
            session_key: Session identifier.
        """
        with self._lock:
            if session_key in self._sessions:
                self._sessions[session_key].message_count += 1
                self._sessions[session_key].last_active_at = datetime.now(UTC)
                self._save()
                logger.debug(f"Incremented message count for {session_key}")
            else:
                logger.warning(f"Attempted to increment message count for unknown session: {session_key}")

    def list_sessions(self) -> dict[str, SessionState]:
        """List all active sessions.

        Returns:
            Dictionary mapping session_key to SessionState.
        """
        with self._lock:
            return dict(self._sessions)
