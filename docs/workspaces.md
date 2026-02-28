# Workspaces

Workspaces are isolated agent instances with their own personality, configuration, and capabilities. Each workspace represents a distinct AI agent with specific behavior patterns and access permissions.

## Directory Structure

```
agent_workspaces/<name>/
├── AGENT.md          # Capabilities, behavior guidelines
├── USER.md           # User context/preferences
├── SOUL.md           # Core personality, values
├── HEARTBEAT.md      # Current state, session notes (agent-writable)
├── agent.yaml        # Optional per-workspace configuration
├── .env              # Workspace-specific environment variables
├── .openpaw/         # Framework internals (protected from agent access)
│   ├── conversations.db    # AsyncSqliteSaver checkpoint database
│   ├── sessions.json       # Session/conversation thread state
│   ├── token_usage.jsonl   # Token usage metrics
│   └── subagents.yaml      # Sub-agent state
├── uploads/          # User-uploaded files (from FilePersistenceProcessor)
│   └── {YYYY-MM-DD}/      # Date-partitioned storage
│       ├── report.pdf        # Original uploaded file
│       ├── report.md         # Docling-converted markdown (sibling)
│       ├── voice_123.ogg     # Original audio file
│       └── voice_123.txt     # Whisper transcript (sibling)
├── downloads/        # Browser-downloaded files
├── screenshots/      # Browser screenshots
├── TASKS.yaml        # Persistent task tracking
├── heartbeat_log.jsonl  # Heartbeat event log
├── memory/
│   └── conversations/  # Archived conversation exports
│       ├── conv_*.md     # Markdown archives (human-readable)
│       └── conv_*.json   # JSON sidecars (machine-readable)
├── crons/            # Static scheduled task definitions
│   └── *.yaml
└── tools/            # Custom LangChain @tool functions
    ├── *.py
    └── requirements.txt
```

## Required Files

Every workspace must contain four markdown files that define the agent's identity and behavior.

### AGENT.md - Capabilities and Behavior

Defines what the agent can do and how it should behave.

**Example:**

```markdown
# Agent Profile

You are Gilfoyle, a senior systems architect and DevOps engineer.

## Capabilities

- AWS infrastructure management (Lambda, S3, DynamoDB)
- Python development (FastAPI, SQLAlchemy, Pydantic)
- Terraform infrastructure-as-code
- CI/CD pipeline design
- System architecture and design patterns

## Communication Style

- Be direct and technically precise
- Avoid unnecessary pleasantries
- Use sarcasm sparingly but effectively
- Cite specific technologies and patterns when relevant

## Constraints

- Do not make AWS changes without confirmation
- Always explain architectural decisions
- Prioritize security and scalability
```

### USER.md - User Context

Information about the user(s) this agent serves.

**Example:**

```markdown
# User Profile

## Name
John Sosoka

## Role
Engineering Lead

## Preferences
- Prefers concise technical explanations
- Works in Pacific Time (PT)
- Uses AWS us-west-2 region by default

## Context
- Manages multiple client projects
- Values clean, maintainable code
- Follows Clean Code and Clean Architecture principles
```

### SOUL.md - Core Personality

The agent's fundamental values and personality traits.

**Example:**

```markdown
# Core Values

## Technical Excellence
Always prioritize correctness, clarity, and maintainability over cleverness.

## Honesty
If you don't know something, say so. Don't speculate or guess about critical systems.

## Efficiency
Value the user's time. Be concise but complete.

## Professionalism
Maintain professional communication standards. You represent the engineering team.
```

### HEARTBEAT.md - Current State

Session state and notes. The agent can read and modify this file to persist information across conversations.

**Example:**

```markdown
# Current State

## Session Started
2026-02-05

## Active Projects
- OpenPaw: Multi-channel agent framework
- ClientX: AWS Lambda migration

## Pending Tasks
- Review OpenPaw documentation
- Update Terraform modules for ClientX

## Recent Learnings
- Conversation persistence via AsyncSqliteSaver
- APScheduler for cron implementation
```

The agent can update HEARTBEAT.md during conversations to track ongoing work, decisions, and context. This file serves as a scratchpad for agent-maintained notes and is especially useful for heartbeat check-ins.

## Optional Configuration

### agent.yaml - Workspace Configuration

Override global configuration for this specific workspace.

**Example:**

```yaml
name: Gilfoyle
description: Sarcastic systems architect
timezone: America/Denver  # IANA timezone identifier (default: UTC)

model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.5
  max_turns: 50

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: [123456789]
  allowed_groups: []

queue:
  mode: steer
  debounce_ms: 500

builtins:
  allow: []    # Empty = allow all available
  deny:
    - elevenlabs

heartbeat:
  enabled: true
  interval_minutes: 30
  active_hours: "09:00-17:00"  # Interpreted in workspace timezone
  suppress_ok: true
  output:
    channel: telegram
    chat_id: 123456789
```

See the main CLAUDE.md documentation for detailed configuration options.

### .env - Environment Variables

Workspace-specific environment variables are automatically loaded from `.env` files in the workspace root.

**Example:**

```bash
# API keys specific to this workspace
CALENDAR_API_KEY=abc123
JIRA_API_TOKEN=xyz789

# Workspace-specific configuration
DEFAULT_PROJECT=ClientX
TEAM_EMAIL=team@example.com
```

These variables are available to custom tools and can be referenced in `agent.yaml` using `${VAR_NAME}` syntax.

## Workspace Isolation

Each workspace is fully isolated:

- **Separate channels** - Own Telegram bot or dedicated channel
- **Independent queue** - Own queue manager and concurrency limits
- **Isolated filesystem** - Can only read/write within workspace directory
- **Dedicated agent instance** - Own LangGraph agent with separate memory
- **Per-workspace crons** - Scheduled tasks scoped to workspace
- **Isolated sub-agents** - Background workers managed per workspace
- **Protected framework internals** - `.openpaw/` directory is read-only to agents

This enables running multiple agents simultaneously without interference:

```bash
poetry run openpaw -c config.yaml -w gilfoyle,assistant,scheduler
```

Each agent operates independently with its own configuration and personality.

## Filesystem Access

Agents have sandboxed filesystem access to their workspace directory via `FilesystemTools` in `openpaw/agent/tools/filesystem.py`.

### Available Operations

- `ls` - List directory contents
- `read_file` - Read file contents (100K character safety valve)
- `write_file` - Create new files or append to existing files
- `overwrite_file` - Replace file contents entirely
- `edit_file` - Make precise edits to existing files
- `glob_files` - Find files by pattern (e.g., `*.md`, `**/*.py`)
- `grep_files` - Search file contents with regex (supports `context_lines` for surrounding context)
- `file_info` - Get metadata (size, line count, binary detection) without reading content

### Path Security

All filesystem operations use `resolve_sandboxed_path()` from `openpaw/agent/tools/sandbox.py` for path traversal protection:

- **Workspace-scoped** - Cannot access files outside workspace directory
- **No absolute paths** - Rejects paths starting with `/` or `~`
- **No parent traversal** - Rejects `..` in paths
- **Framework protection** - Cannot read or write `.openpaw/` directory

### Example Use Cases

**Persistent notes:**
```
Agent reads HEARTBEAT.md → Updates pending tasks → Writes back to file
```

**Data organization:**
```
Agent creates notes/ directory → Saves meeting summaries → Retrieves on demand
```

**File analysis:**
```
Agent uses file_info to check size → Uses grep_files to search content → Reads specific files
```

**Uploaded file processing:**
```
User uploads document → FilePersistenceProcessor saves to uploads/ → Agent reads processed markdown
```

## Custom Tools

Workspaces can define custom LangChain tools in the `tools/` directory. These are Python files containing `@tool` decorated functions that are automatically loaded and made available to the agent.

### Creating Custom Tools

**Example: Calendar tool** (`tools/calendar.py`)

```python
from langchain_core.tools import tool
from datetime import datetime, timedelta
import os

@tool
def get_upcoming_events(days_ahead: int = 7) -> str:
    """Get upcoming calendar events.

    Args:
        days_ahead: Number of days to look ahead

    Returns:
        Formatted list of events.
    """
    api_key = os.getenv("CALENDAR_API_KEY")
    if not api_key:
        return "Error: CALENDAR_API_KEY not configured"

    # Implementation here
    events = fetch_calendar_events(api_key, days_ahead)
    return format_events(events)

@tool
def check_availability(date: str) -> str:
    """Check if a specific date is free.

    Args:
        date: Date in YYYY-MM-DD format

    Returns:
        Availability status with free time blocks.
    """
    # Implementation here
    return check_calendar_availability(date)
```

### Tool Dependencies

Add a `tools/requirements.txt` for tool-specific packages:

```
# tools/requirements.txt
icalendar>=5.0.0
caldav>=1.0.0
requests>=2.31.0
```

Missing dependencies are automatically installed at workspace startup.

### Tool Loading

- Files must be in `{workspace}/tools/*.py`
- Use LangChain's `@tool` decorator from `langchain_core.tools`
- Tools are merged with framework builtins (brave_search, cron, browser, etc.)
- Environment variables from workspace `.env` are available
- Multiple tools per file are supported
- Files starting with `_` are ignored
- Tools are dynamically imported at workspace startup

### Tool Best Practices

1. **Clear documentation** - Use comprehensive docstrings with Args/Returns sections
2. **Error handling** - Return error messages rather than raising exceptions
3. **Environment variables** - Use `.env` for API keys and configuration
4. **Type hints** - LangChain uses type hints for parameter validation
5. **Focused functionality** - Each tool should have a single, clear purpose
6. **Examples in docstring** - Help the agent understand when to use the tool

## Scheduled Tasks (Crons)

Define scheduled tasks in the `crons/` directory using YAML files.

**Example: crons/daily-summary.yaml**

```yaml
name: daily-summary
schedule: "0 9 * * *"  # 9 AM daily (workspace timezone)
enabled: true

prompt: |
  Generate a daily summary by reviewing:
  - Active projects in HEARTBEAT.md
  - TASKS.yaml for pending work
  - Recent conversation archives in memory/conversations/

  Provide a concise status update focusing on what requires attention today.

output:
  channel: telegram
  chat_id: 123456789
```

**Schedule Format:**
- Standard cron expression: `"minute hour day-of-month month day-of-week"`
- Fires in the workspace timezone
- Examples:
  - `"0 9 * * *"` - Every day at 9:00 AM
  - `"*/15 * * * *"` - Every 15 minutes
  - `"0 0 * * 0"` - Every Sunday at midnight
  - `"0 9 * * 1-5"` - Weekdays at 9:00 AM

**Enable/Disable:** Set `enabled: false` to disable without deleting the file.

See the main CLAUDE.md documentation for dynamic scheduling via the `cron` builtin.

## Heartbeat System

The heartbeat scheduler enables proactive agent check-ins on a configurable schedule.

**Configuration in agent.yaml:**

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30           # How often to check in
  active_hours: "09:00-17:00"    # Only run during these hours (workspace timezone)
  suppress_ok: true              # Don't send message if agent responds "HEARTBEAT_OK"
  output:
    channel: telegram
    chat_id: 123456789
```

**HEARTBEAT_OK Protocol:** If the agent determines there's nothing to report, it can respond with exactly "HEARTBEAT_OK" and no message will be sent (when `suppress_ok: true`).

**Pre-flight Skip:** Before invoking the LLM, the scheduler checks HEARTBEAT.md and TASKS.yaml. If HEARTBEAT.md is empty/trivial and no active tasks exist, the heartbeat is skipped entirely — saving API costs for idle workspaces.

**Task Summary Injection:** When active tasks exist, a compact summary is automatically injected into the heartbeat prompt as `<active_tasks>` XML tags.

**Event Logging:** Every heartbeat event is logged to `{workspace}/heartbeat_log.jsonl` with outcome, duration, token metrics, and active task count.

## Conversation Persistence

Conversations persist across restarts via `AsyncSqliteSaver` (from `langgraph-checkpoint-sqlite`).

### Storage Locations

- **Active conversations** - `.openpaw/conversations.db` (SQLite checkpoint database)
- **Session state** - `.openpaw/sessions.json` (thread tracking)
- **Archives** - `memory/conversations/` (dual-format exports: markdown + JSON)

### Conversation Lifecycle

1. Messages are stored in the checkpoint database with thread ID `"{session_key}:{conversation_id}"`
2. Conversation IDs use format `conv_{ISO_timestamp_with_microseconds}`
3. `/new` command archives the current conversation and starts fresh
4. `/compact` command summarizes the conversation, archives it, and starts new with summary injected
5. On workspace shutdown, all active conversations are automatically archived

### Archived Conversations

Archived conversations are exported to `memory/conversations/` in dual format:

- **Markdown** (`conv_*.md`) - Human-readable format, agents can reference for long-term context
- **JSON** (`conv_*.json`) - Machine-readable with full metadata, internal timestamps in UTC

Agents can read archived conversations to maintain long-term memory across conversation resets.

## Creating a New Workspace

The fastest way to create a workspace is with the `init` command:

```bash
# Basic scaffold with TODO markers
poetry run openpaw init my_agent

# Pre-configure model and channel
poetry run openpaw init my_agent --model anthropic:claude-sonnet-4-20250514 --channel telegram

# Scaffold in a custom directory
poetry run openpaw init my_agent --path /path/to/workspaces
```

This creates the workspace directory with all required files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md, agent.yaml, .env) pre-populated with templates and TODO markers.

**After scaffolding:**

1. Edit `agent.yaml` with your model and channel settings
2. Add API keys to `.env`
3. Customize AGENT.md, USER.md, and SOUL.md to define personality
4. Optionally add custom tools in `tools/` and cron jobs in `crons/`
5. Run the workspace:

```bash
poetry run openpaw -c config.yaml -w my_agent
```

**List available workspaces:**

```bash
poetry run openpaw list
```

**Name requirements:** Workspace names must be 2-64 characters, start with a lowercase letter, and contain only lowercase letters, digits, hyphens, and underscores (e.g., `my_agent`, `test-bot`, `gilfoyle`).

## Example Workspaces

### Technical Support Agent

**AGENT.md:**
```markdown
# Technical Support Specialist

You are a technical support specialist for SaaS products.

## Capabilities
- Troubleshooting common issues
- API debugging assistance
- Documentation lookup via brave_search
- Issue escalation when needed

## Communication Style
- Patient and helpful
- Ask clarifying questions
- Provide step-by-step solutions
- Link to relevant documentation
```

**agent.yaml:**
```yaml
queue:
  mode: followup  # Process support requests sequentially

builtins:
  allow:
    - brave_search  # Enable documentation search
    - send_message  # Progress updates during troubleshooting
```

### Scheduled Reporter

**AGENT.md:**
```markdown
# Daily Reporter

You generate daily reports by analyzing system state and recent activity.

## Capabilities
- Reading workspace files (HEARTBEAT.md, TASKS.yaml)
- Summarizing project status
- Identifying pending tasks and blockers
- Analyzing conversation archives for trends
```

**crons/daily-report.yaml:**
```yaml
name: daily-report
schedule: "0 9 * * 1-5"  # Weekdays at 9 AM
enabled: true

prompt: |
  Review all workspace files and generate a status report.

  Include:
  - Active projects from HEARTBEAT.md
  - Task status from TASKS.yaml
  - Recent conversation topics from memory/conversations/
  - Any blockers requiring human attention
```

### Multi-User Team Assistant

**AGENT.md:**
```markdown
# Team Assistant

You are a team assistant supporting multiple engineers in a group chat.

## Capabilities
- Task tracking via TASKS.yaml
- Calendar management (custom tools)
- Documentation lookup
- Meeting note summarization

## Communication Style
- Tag users when addressing them directly
- Be concise in group contexts
- Use threads for detailed discussions
```

**agent.yaml:**
```yaml
channel:
  type: telegram
  allowed_groups: [-1001234567890]  # Team group chat

builtins:
  task_tracker:
    enabled: true
  brave_search:
    enabled: true
```

**tools/calendar.py:**
```python
from langchain_core.tools import tool

@tool
def check_team_availability(date: str) -> str:
    """Check team calendar for available meeting slots.

    Args:
        date: Date in YYYY-MM-DD format

    Returns:
        Available time slots for team meetings.
    """
    # Implementation using workspace calendar API
    return get_team_availability(date)
```

## Best Practices

1. **Clear identity** - Give each workspace a distinct personality and purpose
2. **Focused capabilities** - Don't try to make one agent do everything
3. **Consistent voice** - Maintain personality across all markdown files
4. **Appropriate permissions** - Use `allowed_users`/`allowed_groups` to restrict access
5. **Regular updates** - Keep HEARTBEAT.md current with ongoing work
6. **Tool organization** - Use descriptive names and comprehensive docstrings
7. **Cron hygiene** - Disable unused cron jobs (`enabled: false`) rather than deleting
8. **Timezone awareness** - Set workspace timezone for accurate scheduling and display
9. **Task management** - Use TASKS.yaml for long-running work across conversations
10. **Archive review** - Encourage agents to review conversation archives for long-term context
11. **Security** - Never commit API keys or tokens; use `.env` and environment variables
