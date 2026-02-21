# Builtins

Builtins are optional capabilities conditionally loaded based on API key availability and installed packages. They come in two types: **tools** (agent-invokable functions) and **processors** (message transformers).

## Overview

OpenPaw ships with 12 built-in tools and 4 message processors. Builtins are discovered at runtime — if prerequisites (API keys, packages) are missing, the builtin is unavailable. The allow/deny system provides fine-grained control over which capabilities are active in each workspace.

**Architecture:**

```
BuiltinRegistry
├─ Tools (12)
│  ├─ browser          Web automation via Playwright
│  ├─ brave_search     Web search
│  ├─ spawn            Sub-agent spawning
│  ├─ cron             Agent self-scheduling
│  ├─ task_tracker     Persistent task management
│  ├─ send_message     Mid-execution messaging
│  ├─ send_file        Send workspace files to users
│  ├─ followup         Self-continuation
│  ├─ memory_search    Semantic conversation search
│  ├─ shell            Local command execution
│  ├─ ssh              Remote SSH execution
│  └─ elevenlabs       Text-to-speech
│
└─ Processors (4)
   ├─ file_persistence Universal file upload handling
   ├─ whisper          Audio transcription
   ├─ timestamp        Message timestamp injection
   └─ docling          Document-to-markdown conversion
```

**Processor Pipeline Order:** `file_persistence` → `whisper` → `timestamp` → `docling`

The order matters — `file_persistence` runs first to save uploaded files, then downstream processors (whisper, docling) can read from disk.

## Tools

### browser

**Group:** `browser`
**Type:** Tool (11 functions)
**Prerequisites:** `playwright` (core dependency), chromium browser installed

Web automation via Playwright with accessibility tree navigation. Agents interact with pages via numeric element references instead of writing CSS selectors.

**Available Functions:**
- `browser_navigate` — Navigate to a URL (respects domain allowlist/blocklist)
- `browser_snapshot` — Get current page state as numbered accessibility tree
- `browser_click` — Click an element by numeric reference
- `browser_type` — Type text into an input field by numeric reference
- `browser_select` — Select dropdown option by numeric reference
- `browser_scroll` — Scroll the page (up/down/top/bottom)
- `browser_back` — Navigate back in browser history
- `browser_screenshot` — Capture page screenshot (saved to `screenshots/`)
- `browser_close` — Close current page/tab
- `browser_tabs` — List all open tabs
- `browser_switch_tab` — Switch to a different tab by index

**Security Model:**

Domain allowlisting and blocklisting prevent unauthorized navigation. If `allowed_domains` is non-empty, only those domains (and subdomains with `*.` prefix) are permitted. The `blocked_domains` list takes precedence and denies specific domains even if allowed.

**Configuration:**

```yaml
builtins:
  browser:
    enabled: true
    config:
      headless: true                # Run browser without GUI
      allowed_domains:              # Allowlist (empty = allow all)
        - "calendly.com"
        - "*.google.com"            # Subdomain wildcard
      blocked_domains: []           # Blocklist (takes precedence)
      timeout_seconds: 30           # Default timeout for operations
      persist_cookies: false        # Persist cookies across agent runs
      downloads_dir: "downloads"    # Where to save downloaded files
      screenshots_dir: "screenshots"  # Where to save screenshots
```

**Installation:**

```bash
poetry install  # playwright is a core dependency
poetry run playwright install chromium
```

**Usage Example:**

```
User: "Book a meeting on my Calendly for tomorrow at 2pm"
Agent: [Calls browser_navigate("https://calendly.com/myaccount")]
Agent: [Calls browser_snapshot() to see page elements]
Agent: [Calls browser_click(42) to click the "Schedule" button (element #42)]
Agent: [Fills in meeting details and confirms booking]
```

**Lifecycle:**

Browser instances are lazily initialized (no browser created until first use). Each session gets its own browser context. Browsers are automatically cleaned up on `/new`, `/compact`, and workspace shutdown.

**Cookie Persistence:**

When `persist_cookies: true`, authentication state and cookies survive across agent runs within the same session. Cookies are cleared on conversation reset.

**Downloads and Screenshots:**

Files downloaded by the browser are saved to `{workspace}/downloads/` with sanitized filenames. Page screenshots are saved to `{workspace}/screenshots/` and returned as relative paths for agent reference.

---

### brave_search

**Group:** `web`
**Type:** Tool
**Prerequisites:** `BRAVE_API_KEY`, `poetry install -E web`

Web search capability using the Brave Search API.

**Configuration:**

```yaml
builtins:
  brave_search:
    enabled: true
    config:
      count: 5  # Number of search results
```

**Usage Example:**

```
User: "What's the latest news about Python 3.13?"
Agent: [Uses brave_search tool to find recent articles]
Agent: "According to recent sources, Python 3.13 introduces..."
```

---

### spawn

**Group:** `agent`
**Type:** Tool (4 functions)
**Prerequisites:** None (always available)

Sub-agent spawning for concurrent background tasks. Sub-agents run in isolated contexts with filtered tools to prevent recursion and unsolicited messaging.

**Available Functions:**
- `spawn_agent` — Spawn a background sub-agent with a task prompt and label
- `list_subagents` — List all sub-agents (active and recently completed)
- `get_subagent_result` — Retrieve result of a completed sub-agent by ID
- `cancel_subagent` — Cancel a running sub-agent

**Configuration:**

```yaml
builtins:
  spawn:
    enabled: true
    config:
      max_concurrent: 8  # Maximum simultaneous sub-agents (default: 8)
```

**Tool Exclusions:**

Sub-agents cannot spawn sub-agents (no `spawn_agent`), send unsolicited messages (no `send_message`/`send_file`), self-continue (no `request_followup`), or schedule tasks (no cron tools). This prevents recursion and ensures sub-agents are single-purpose workers.

**Lifecycle:**

`pending` → `running` → `completed`/`failed`/`cancelled`/`timed_out`. Running sub-agents exceeding their timeout are marked as `timed_out` during cleanup.

**Notifications:**

When `notify: true` (default), sub-agent completion results are injected into the message queue, triggering a new agent turn to process the `[SYSTEM]` notification.

**Usage Example:**

```
User: "Research topic X in the background while I work on Y"
Agent: [Calls spawn_agent(task="Research topic X...", label="research-x")]
Sub-agent: [Runs concurrently, main agent continues working on Y]
System: [When complete, user receives notification with result summary]
```

**Limits:**

Maximum 8 concurrent sub-agents (configurable), timeout defaults to 30 minutes (1-120 range). Results are truncated at 50K characters to match `read_file` safety valve pattern.

**Storage:**

Sub-agent state persists to `{workspace}/.openpaw/subagents.yaml` and survives restarts. Completed/failed/cancelled requests older than 24 hours are automatically cleaned up on initialization.

---

### cron

**Group:** `agent`
**Type:** Tool (4 functions)
**Prerequisites:** None (always available)

Agent self-scheduling for one-time and recurring tasks. Enables autonomous workflows like "remind me in 20 minutes" or "check on this PR every hour".

**Available Functions:**
- `schedule_at` — Schedule a one-time action at a specific timestamp
- `schedule_every` — Schedule a recurring action at fixed intervals
- `list_scheduled` — List all pending scheduled tasks
- `cancel_scheduled` — Cancel a scheduled task by ID

**Configuration:**

```yaml
builtins:
  cron:
    enabled: true
    config:
      min_interval_seconds: 300  # Minimum interval for recurring tasks (default: 5 min)
      max_tasks: 50              # Maximum pending tasks per workspace
```

**Storage:**

Tasks persist to `{workspace}/dynamic_crons.json` and survive restarts. One-time tasks are automatically cleaned up after execution or if expired on startup.

**Routing:**

Responses are sent back to the first allowed user in the workspace's channel config.

**Usage Example:**

```
User: "Ping me in 10 minutes to check on the deploy"
Agent: [Calls schedule_at with timestamp 10 minutes from now]
System: [Task fires, agent sends reminder to user's chat]
```

---

### task_tracker

**Group:** `agent`
**Type:** Tool (4 functions)
**Prerequisites:** None (always available)

Task management via TASKS.yaml for tracking long-running operations across heartbeats and sessions.

**Available Functions:**
- `create_task` — Create a new tracked task
- `update_task` — Update task status or notes
- `list_tasks` — List all tasks (optionally filtered by status)
- `get_task` — Retrieve a specific task by ID

**Configuration:**

```yaml
builtins:
  task_tracker:
    enabled: true
```

**Storage:**

Tasks persist to `{workspace}/TASKS.yaml`. Thread-safe with atomic writes.

**Integration with Heartbeat:**

When active tasks exist, a compact summary is injected into the heartbeat prompt as `<active_tasks>` XML tags. This avoids an extra LLM tool call to `list_tasks()`.

**Usage Example:**

```
Agent: [Calls create_task(title="Monitor deploy", status="in_progress")]
Agent: [Works on the task]
Agent: [Calls update_task(task_id="task-001", status="completed")]
```

---

### send_message

**Group:** `agent`
**Type:** Tool
**Prerequisites:** None (always available)

Mid-execution messaging to keep users informed during long operations. Agents can send progress updates while continuing to work.

**Configuration:**

```yaml
builtins:
  send_message:
    enabled: true
```

**Implementation:**

Uses shared `_channel_context` for session-safe state access to the active channel.

**Usage Example:**

```
User: "Process this large dataset"
Agent: [Calls send_message("Starting analysis of 10,000 rows...")]
Agent: [Continues processing]
Agent: [Calls send_message("Halfway done, found 3 anomalies...")]
Agent: [Finishes and responds with full results]
```

---

### send_file

**Group:** `agent`
**Type:** Tool
**Prerequisites:** None (always available)

Send workspace files to users via channel. Validates files within sandbox, infers MIME type, enforces 50MB limit.

**Configuration:**

```yaml
builtins:
  send_file:
    enabled: true
    config:
      max_file_size: 52428800  # 50 MB default
```

**Implementation:**

Uses shared `_channel_context` for session-safe state. Validates paths with `resolve_sandboxed_path()` for security.

**Usage Example:**

```
Agent: [Generates a report.pdf in workspace]
Agent: [Calls send_file("report.pdf", caption="Monthly report")]
User: [Receives file via Telegram]
```

---

### followup

**Group:** `agent`
**Type:** Tool
**Prerequisites:** None (always available)

Self-continuation for multi-step autonomous workflows with depth limiting. Agents request re-invocation after responding.

**Configuration:**

```yaml
builtins:
  followup:
    enabled: true
```

**Usage Example:**

```
Agent: "I've completed step 1 of 3. [Calls request_followup()]"
System: [Re-invokes agent]
Agent: "Now completing step 2..."
```

**Depth Limiting:**

Prevents infinite loops via configurable depth limits in the message processing loop.

---

### memory_search

**Group:** `memory`
**Type:** Tool
**Prerequisites:** `sqlite-vec`, `poetry install -E memory`

Semantic search over past conversations using vector embeddings.

**Configuration:**

```yaml
builtins:
  memory_search:
    enabled: true
```

**Usage Example:**

```
User: "What did we discuss about the deployment last week?"
Agent: [Calls memory_search("deployment last week")]
Agent: "Last Tuesday we discussed rolling back the deployment due to..."
```

---

### shell

**Group:** `system`
**Type:** Tool
**Prerequisites:** `poetry install -E system`

Execute shell commands on the host system with configurable security controls. **Disabled by default** — must explicitly enable.

**Security:**

- Disabled by default
- Default blocked commands list prevents dangerous operations (rm -rf, sudo, etc.)
- Optional command allowlist for strict control
- Optional working directory constraint

**Configuration:**

```yaml
builtins:
  shell:
    enabled: true  # Must explicitly enable
    config:
      allowed_commands:  # Optional allowlist
        - ls
        - cat
        - grep
      blocked_commands:  # Optional override of defaults
        - rm -rf
        - sudo
      working_directory: /home/user/sandbox  # Optional constraint
```

**Default Blocked Commands:**

`rm -rf`, `sudo`, `chmod 777`, `chown`, `wget`, `curl`, `dd if=`, `mkfs`, fork bombs

**Usage Example:**

```
User: "What files are in the current directory?"
Agent: [Calls shell with command "ls -la"]
Agent: "Here are the files in the directory..."
```

---

### ssh

**Group:** `system`
**Type:** Tool
**Prerequisites:** `asyncssh`, `poetry install -E system`

Execute commands on remote hosts via SSH with mandatory host allowlisting.

**Security:**

- Mandatory host allowlist — connections to non-allowlisted hosts are rejected
- Uses system SSH keys or specified key paths
- Configurable connection timeout

**Configuration:**

```yaml
builtins:
  ssh:
    enabled: true
    config:
      allowed_hosts:  # REQUIRED
        - server1.example.com
        - 192.168.1.100
      default_user: deploy
      default_key_path: ~/.ssh/id_rsa
      timeout: 30
```

**Usage Example:**

```
User: "Check disk space on the dev server"
Agent: [Calls ssh(host="server1.example.com", command="df -h")]
Agent: "The dev server has 45% disk usage..."
```

---

### elevenlabs

**Group:** `voice`
**Type:** Tool
**Prerequisites:** `ELEVENLABS_API_KEY`, `poetry install -E voice`

Text-to-speech for voice responses using ElevenLabs API.

**Configuration:**

```yaml
builtins:
  elevenlabs:
    enabled: true
    config:
      voice_id: 21m00Tcm4TlvDq8ikWAM  # ElevenLabs voice ID
      model_id: eleven_turbo_v2_5
```

**Usage Example:**

```
User: "Read me the summary"
Agent: [Calls elevenlabs to generate audio]
Agent: [Sends voice message via Telegram]
```

To find voice IDs, visit the [ElevenLabs Voice Library](https://elevenlabs.io/voice-library).

---

## Processors

### file_persistence

**Group:** None
**Type:** Processor
**Prerequisites:** None (always available)

Universal file upload handling with date partitioning. First processor in the pipeline — saves all uploaded files to `{workspace}/uploads/{YYYY-MM-DD}/`.

**Configuration:**

```yaml
builtins:
  file_persistence:
    enabled: true
    config:
      max_file_size: 52428800  # 50 MB default
      clear_data_after_save: false  # Free memory after saving
```

**Behavior:**

Sets `attachment.saved_path` (relative to workspace root) so downstream processors can read from disk. Enriches message content with file receipt notifications:

```
[File received: report.pdf (2.3 MB, application/pdf)]
[Saved to: uploads/2026-02-07/report.pdf]
```

**Filename Handling:**

`sanitize_filename()` normalizes filenames (lowercases, removes special chars, replaces spaces with underscores). `deduplicate_path()` appends counters (1), (2), etc. to prevent overwrites.

---

### whisper

**Group:** `voice`
**Type:** Processor
**Prerequisites:** `OPENAI_API_KEY`, `poetry install -E voice`

Audio transcription for voice and audio messages using OpenAI's Whisper API.

**Configuration:**

```yaml
builtins:
  whisper:
    enabled: true
    config:
      model: whisper-1
      language: en  # Optional: auto-detect if omitted
```

**Behavior:**

Transcribes audio/voice messages and saves transcript as `.txt` sibling to the audio file (e.g., `voice_123.ogg` → `voice_123.txt`). Appends transcript inline to message content.

**Usage Example:**

```
User: [Sends voice message]
Channel: [Downloads audio file]
Whisper: [Transcribes to text, saves voice_123.txt]
Agent: [Processes transcribed text as normal message]
```

---

### timestamp

**Group:** `context`
**Type:** Processor
**Prerequisites:** None (always available)

Prepends current date/time context to inbound messages, helping agents understand the current time in the user's timezone.

**Configuration:**

```yaml
builtins:
  timestamp:
    enabled: true
    config:
      format: "%Y-%m-%d %H:%M %Z"  # Optional datetime format (strftime)
      template: "[Current time: {datetime}]"  # Optional prefix template
```

**Behavior:**

Automatically adds timestamp context to every message:

```
User: "What's the weather today?"
[Timestamp processor adds: "[Current time: 2026-02-17 14:30 PST]"]
Agent sees: "[Current time: 2026-02-17 14:30 PST]\n\nWhat's the weather today?"
```

**Format Examples:**

```yaml
# ISO 8601
format: "%Y-%m-%d %H:%M:%S %Z"
# Output: [Current time: 2026-02-17 14:30:00 PST]

# Human-readable
format: "%A, %B %d, %Y at %I:%M %p %Z"
# Output: [Current time: Monday, February 17, 2026 at 02:30 PM PST]
```

**Note:** Timestamp formatting uses the workspace timezone (configurable in `agent.yaml`).

---

### docling

**Group:** None
**Type:** Processor
**Prerequisites:** `docling` (core dependency)

Document conversion (PDF, DOCX, PPTX, etc.) to markdown with OCR support.

**Configuration:**

```yaml
builtins:
  docling:
    enabled: true
```

**Behavior:**

Converts documents to markdown and saves as `.md` sibling file (e.g., `report.pdf` → `report.md`). Appends converted markdown inline to message content.

**OCR Support:**

- macOS: Uses `OcrMacOptions(force_full_page_ocr=True)` for scanned PDFs
- Linux: Uses `EasyOcrOptions` for OCR

**Usage Example:**

```
User: [Uploads report.pdf]
FilePersistence: [Saves to uploads/2026-02-17/report.pdf]
Docling: [Converts to markdown, saves report.md]
Agent: [Processes markdown content]
```

---

## Configuration

### Global Configuration

Configure builtins in `config.yaml`:

```yaml
builtins:
  # Allow/deny lists
  allow: []  # Empty = allow all available
  deny:
    - group:voice  # Deny all voice-related builtins

  # Individual builtin configs
  browser:
    enabled: true
    config:
      headless: true
      allowed_domains: ["calendly.com"]

  brave_search:
    enabled: true
    config:
      count: 5

  whisper:
    enabled: true
    config:
      model: whisper-1

  spawn:
    enabled: true
    config:
      max_concurrent: 8

  cron:
    enabled: true
    config:
      max_tasks: 50
      min_interval_seconds: 300

  file_persistence:
    enabled: true
    config:
      max_file_size: 52428800
```

### Per-Workspace Configuration

Override builtin settings per workspace in `agent.yaml`:

```yaml
# workspace1/agent.yaml - Enable web search only
builtins:
  allow:
    - brave_search
  deny:
    - elevenlabs

# workspace2/agent.yaml - Enable voice features
builtins:
  allow:
    - group:voice  # Allow all voice builtins
  deny:
    - brave_search
```

### Allow/Deny Behavior

**Empty allow list** — Allow all available builtins (default)

```yaml
builtins:
  allow: []  # Allow everything
```

**Specific allow list** — Only enable listed builtins

```yaml
builtins:
  allow:
    - brave_search
    - whisper
  # elevenlabs is denied (not in allow list)
```

**Group allow** — Enable all builtins in a group

```yaml
builtins:
  allow:
    - group:voice  # Allows whisper, elevenlabs
```

**Deny list** — Block specific builtins or groups

```yaml
builtins:
  allow: []  # Allow all
  deny:
    - elevenlabs  # Except this one
```

**Group deny** — Block all builtins in a group

```yaml
builtins:
  deny:
    - group:voice  # Blocks whisper, elevenlabs
```

**Priority:** Deny takes precedence over allow.

---

## Builtin Groups

| Group | Members |
|-------|---------|
| `voice` | whisper, elevenlabs |
| `web` | brave_search |
| `system` | shell, ssh |
| `context` | timestamp |
| `agent` | spawn, cron, task_tracker, send_message, followup, send_file |
| `browser` | browser |
| `memory` | memory_search |

**Usage:**

```yaml
builtins:
  allow:
    - group:web  # Allow all web builtins
  deny:
    - group:voice  # Deny all voice builtins
```

---

## Installation

Builtins require optional dependencies. Install only what you need:

**Voice capabilities:**
```bash
poetry install -E voice
```
Installs: `openai`, `elevenlabs`

**Web capabilities:**
```bash
poetry install -E web
```
Installs: `langchain-community`

**System capabilities:**
```bash
poetry install -E system
```
Installs: `langchain-experimental`, `asyncssh`

**Memory search:**
```bash
poetry install -E memory
```
Installs: `sqlite-vec`

**All builtins:**
```bash
poetry install -E all-builtins
```

**Core dependencies** (included in base install):
- `playwright` — Browser automation
- `docling` — Document conversion

---

## Adding Custom Builtins

You can extend OpenPaw with custom tools and processors.

### Creating a Custom Tool

1. **Create tool file:** `openpaw/builtins/tools/my_tool.py`

```python
from langchain_core.tools import StructuredTool
from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinType,
    BuiltinPrerequisite,
)


class MyCustomTool(BaseBuiltinTool):
    """Custom tool implementation."""

    metadata = BuiltinMetadata(
        name="my_custom_tool",
        display_name="My Custom Tool",
        description="Custom functionality for X",
        builtin_type=BuiltinType.TOOL,
        group="custom",
        prerequisites=BuiltinPrerequisite(
            env_vars=["MY_API_KEY"],
            packages=["my-package"],
        ),
    )

    def get_langchain_tool(self) -> list:
        """Return LangChain tool instances."""

        def my_tool_func(query: str) -> str:
            """Execute the tool."""
            api_key = self.config.get("api_key") or os.getenv("MY_API_KEY")
            # Implementation here
            return result

        return [
            StructuredTool.from_function(
                func=my_tool_func,
                name="my_custom_tool",
                description="What this tool does",
            )
        ]
```

**Key Points:**

- Extend `BaseBuiltinTool`, not `BaseTool` from LangChain
- Use `StructuredTool.from_function()` factory pattern
- `get_langchain_tool()` returns a **list** (can contain multiple tools)
- Access config via `self.config`

2. **Register in registry:** `openpaw/builtins/registry.py`

```python
try:
    from openpaw.builtins.tools.my_tool import MyCustomTool
    self.register_tool(MyCustomTool)
except ImportError as e:
    logger.debug(f"My custom tool not available: {e}")
```

3. **Configure in config.yaml:**

```yaml
builtins:
  my_custom_tool:
    enabled: true
    config:
      option1: value1
```

4. **Set environment variable:**

```bash
export MY_API_KEY="your-key"
```

### Creating a Custom Processor

1. **Create processor file:** `openpaw/builtins/processors/my_processor.py`

```python
from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinType,
    BuiltinPrerequisite,
    ProcessorResult,
)
from openpaw.domain.message import Message


class MyCustomProcessor(BaseBuiltinProcessor):
    """Custom message processor."""

    metadata = BuiltinMetadata(
        name="my_processor",
        display_name="My Processor",
        description="Processes messages before agent sees them",
        builtin_type=BuiltinType.PROCESSOR,
        group="custom",
        prerequisites=BuiltinPrerequisite(
            env_vars=["MY_API_KEY"],
        ),
    )

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Transform the message."""
        # Access config
        option = self.config.get("option1", "default")

        # Transform message content
        message.content = f"[Processed] {message.content}"

        return ProcessorResult(message=message)
```

2. **Register in registry:** `openpaw/builtins/registry.py`

```python
try:
    from openpaw.builtins.processors.my_processor import MyCustomProcessor
    self.register_processor(MyCustomProcessor)
except ImportError as e:
    logger.debug(f"My processor not available: {e}")
```

3. **Configure and use:**

```yaml
builtins:
  my_processor:
    enabled: true
    config:
      option1: value1
```

Processors run automatically on all messages in the channel layer.

---

## Best Practices

### 1. Use Environment Variables for Secrets

Never hardcode API keys:

```yaml
# Bad
builtins:
  brave_search:
    config:
      api_key: "actual-key-here"  # Don't do this

# Good — relies on BRAVE_API_KEY environment variable
builtins:
  brave_search:
    enabled: true
```

### 2. Install Only Needed Extras

Minimize dependencies:

```bash
# Only need voice features
poetry install -E voice

# Don't install all if you only need some
```

### 3. Deny Unused Builtins

Reduce attack surface:

```yaml
builtins:
  deny:
    - elevenlabs  # Don't need TTS in this workspace
    - group:system  # Disable shell/ssh for security
```

**Security Note:** System tools (shell, ssh) should be denied unless explicitly needed. The shell tool is disabled by default and requires explicit enablement.

### 4. Use Groups for Bulk Operations

Simplify configuration:

```yaml
# Instead of denying individual tools:
builtins:
  deny:
    - whisper
    - elevenlabs

# Use group deny:
builtins:
  deny:
    - group:voice
```

### 5. Test Prerequisites

Verify API keys before deploying:

```bash
# Test OpenAI key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Test ElevenLabs key
curl https://api.elevenlabs.io/v1/voices \
  -H "xi-api-key: $ELEVENLABS_API_KEY"
```

---

## Troubleshooting

**Builtin not available:**
- Check environment variable is set: `echo $OPENAI_API_KEY`
- Verify extras are installed: `poetry install -E voice`
- Check allow/deny lists in config
- Enable verbose logging: `poetry run openpaw -w agent -v`

**API key errors:**
- Verify key is valid and active
- Check API quota/billing status
- Test key with curl (see examples above)

**Import errors:**
- Missing optional dependency
- Run `poetry install -E <extra-name>`
- Check `pyproject.toml` for correct package versions

**Processor not running:**
- Verify `enabled: true` in config
- Check processor isn't denied
- Ensure processor is registered in registry
- Check logs for initialization errors

**Tool not available to agent:**
- Verify tool prerequisites are met
- Check allow/deny lists
- Tool must be properly registered
- Agent must have permission to use tools (model capability)

---

## Security Considerations

### System Tools (shell, ssh)

The `shell` and `ssh` tools provide powerful system access and require careful configuration:

**Shell Tool:**
- Disabled by default — must explicitly enable in config
- Use `allowed_commands` for strict allowlisting when possible
- Default `blocked_commands` list prevents common dangerous operations
- Consider constraining `working_directory` to a sandbox
- Never enable in untrusted environments

**SSH Tool:**
- Requires mandatory `allowed_hosts` configuration
- Rejects connections to non-allowlisted hosts
- Uses system SSH keys — ensure keys have appropriate permissions
- Consider separate keys for agent SSH access
- Audit `allowed_hosts` list regularly

**Best Practices:**
1. Enable system tools only in workspaces that need them
2. Use `group:system` deny rule in untrusted workspaces
3. Configure minimal permissions (minimal allowed_commands, minimal allowed_hosts)
4. Monitor logs for blocked command attempts
5. Keep SSH keys secured with appropriate file permissions (600)

### Browser Tool

**Domain Security:**
- Use `allowed_domains` allowlist for production workspaces
- `blocked_domains` takes precedence over allowlist
- Wildcard subdomain support with `*.example.com`
- Consider `persist_cookies: false` to avoid session leakage

**Best Practices:**
1. Configure domain allowlist for untrusted agents
2. Monitor downloads directory for unexpected files
3. Set reasonable timeout values
4. Review screenshot captures for sensitive data
