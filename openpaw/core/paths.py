"""Central workspace path constants.

Single source of truth for all workspace-relative directory and file paths.
Every module that constructs workspace paths should import from here.
All paths are relative to the workspace root.
"""

from pathlib import PurePosixPath

# ---------------------------------------------------------------------------
# Top-level directories
# ---------------------------------------------------------------------------

AGENT_DIR = PurePosixPath("agent")
CONFIG_DIR = PurePosixPath("config")
DATA_DIR = PurePosixPath("data")
MEMORY_DIR = PurePosixPath("memory")
WORKSPACE_DIR = PurePosixPath("workspace")

# ---------------------------------------------------------------------------
# Agent identity files
# ---------------------------------------------------------------------------

AGENT_MD = AGENT_DIR / "AGENT.md"
USER_MD = AGENT_DIR / "USER.md"
SOUL_MD = AGENT_DIR / "SOUL.md"
HEARTBEAT_MD = AGENT_DIR / "HEARTBEAT.md"
IDENTITY_FILES = [AGENT_MD, USER_MD, SOUL_MD, HEARTBEAT_MD]

# ---------------------------------------------------------------------------
# Agent extension directories
# ---------------------------------------------------------------------------

TOOLS_DIR = AGENT_DIR / "tools"
SKILLS_DIR = AGENT_DIR / "skills"
TEAM_DIR = AGENT_DIR / "team"

# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------

AGENT_YAML = CONFIG_DIR / "agent.yaml"
DOT_ENV = CONFIG_DIR / ".env"
CRONS_DIR = CONFIG_DIR / "crons"

# ---------------------------------------------------------------------------
# Data files (framework-managed, agent read-only via dedicated tools)
# ---------------------------------------------------------------------------

CONVERSATIONS_DB = DATA_DIR / "conversations.db"
SESSIONS_JSON = DATA_DIR / "sessions.json"
SUBAGENTS_YAML = DATA_DIR / "subagents.yaml"
TOKEN_USAGE_JSONL = DATA_DIR / "token_usage.jsonl"
VECTORS_DB = DATA_DIR / "vectors.db"
BROWSER_COOKIES_JSON = DATA_DIR / "browser_cookies.json"
DYNAMIC_CRONS_JSON = DATA_DIR / "dynamic_crons.json"
HEARTBEAT_LOG_JSONL = DATA_DIR / "heartbeat_log.jsonl"
TASKS_YAML = DATA_DIR / "TASKS.yaml"
UPLOADS_DIR = DATA_DIR / "uploads"

# ---------------------------------------------------------------------------
# Memory directories
# ---------------------------------------------------------------------------

MEMORY_CONVERSATIONS_DIR = MEMORY_DIR / "conversations"
MEMORY_LOGS_DIR = MEMORY_DIR / "logs"

# ---------------------------------------------------------------------------
# Workspace (agent work area — default write root)
# ---------------------------------------------------------------------------

DOWNLOADS_DIR = WORKSPACE_DIR / "downloads"
SCREENSHOTS_DIR = WORKSPACE_DIR / "screenshots"

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

# Known top-level directory names (used to detect explicit paths in write ops).
# Paths whose first component matches one of these are NOT auto-prefixed with workspace/.
TOP_LEVEL_DIRS: frozenset[str] = frozenset({
    str(AGENT_DIR),
    str(CONFIG_DIR),
    str(DATA_DIR),
    str(MEMORY_DIR),
    str(WORKSPACE_DIR),
})

# Write-protected directories: agent filesystem tools may NOT write to these.
# Paths are compared by parts, not string prefix, to avoid false matches.
WRITE_PROTECTED_DIRS: frozenset[str] = frozenset({
    str(DATA_DIR),
    str(MEMORY_DIR / "logs"),
    str(MEMORY_DIR / "conversations"),
    str(CONFIG_DIR),
})

# Specific files within write-protected directories that the agent IS allowed
# to write (via overwrite_file / edit_file).  These are absolute exceptions
# to WRITE_PROTECTED_DIRS.
AGENT_WRITABLE_FILES: frozenset[str] = frozenset({
    str(HEARTBEAT_MD),
})
