"""Workspace-local cache of discovered Self-Discover reasoning structures.

Discovery (3 LLM calls) happens once per task *type*; repeats are free. This
is the amortization the paper's 10–40x efficiency claim rests on (ADR-102 §3).

JSON store at ``{workspace}/data/reasoning_structures.json`` following the
stores pattern (``threading.Lock`` + atomic tmp-rename, corruption degrades
to a miss). Keys embed :data:`MODULE_VERSION`, so a version bump invalidates
prior entries; the store holds at most :data:`MAX_ENTRIES` structures,
evicting the oldest by insertion order.
"""

import hashlib
import json
import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

# Bump when prompts/seed modules change in a way that stales cached structures.
MODULE_VERSION = 1

# ponytail: hard cap with oldest-insertion eviction; LRU if hit rates ever matter.
MAX_ENTRIES = 50


class StructureCache:
    """Thread-safe JSON store mapping task-type keys to reasoning structures."""

    def __init__(self, workspace_path: Path) -> None:
        self._path = workspace_path / "data" / "reasoning_structures.json"
        self._lock = Lock()

    def key_for(self, task: str) -> str:
        """Derive a task-type signature: hash of the normalized task prefix.

        Deterministic, no LLM call — near-identical asks share a structure.
        ponytail: prefix hashing only groups near-verbatim repeats; a
        cheap-model task-type label is the upgrade path for better hit rates.
        """
        normalized = " ".join(task.lower().split())[:120]
        digest = hashlib.sha256(f"v{MODULE_VERSION}:{normalized}".encode()).hexdigest()
        return digest[:16]

    def get(self, key: str) -> dict[str, object] | None:
        """Return the cached structure for ``key``, or None on miss/corruption."""
        with self._lock:
            return self._load_unlocked().get(key)

    def put(self, key: str, structure: dict[str, object]) -> None:
        """Persist a structure, evicting the oldest entries past MAX_ENTRIES."""
        with self._lock:
            data = self._load_unlocked()
            data.pop(key, None)  # re-insert at the end so refreshed keys age last
            data[key] = structure
            while len(data) > MAX_ENTRIES:
                data.pop(next(iter(data)))
            self._save_unlocked(data)

    def _load_unlocked(self) -> dict[str, dict[str, object]]:
        """Load the cache file. Caller must hold the lock. Corruption -> empty."""
        if not self._path.exists():
            return {}
        try:
            raw: object = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Reasoning-structure cache unreadable; treating as empty: %s", self._path)
            return {}
        if not isinstance(raw, dict):
            logger.warning("Reasoning-structure cache malformed; treating as empty: %s", self._path)
            return {}
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}

    def _save_unlocked(self, data: dict[str, dict[str, object]]) -> None:
        """Atomic write (tmp + rename). Caller must hold the lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)
