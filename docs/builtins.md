# Builtins

<div align="center">
  <img src="../assets/images/openpaw-bear-1.png" alt="OpenPaw Built-in Tools" width="500">
</div>

Builtins are optional capabilities conditionally loaded based on API key availability and installed packages. They come in two types: **tools** (agent-invokable functions) and **processors** (message transformers).

## Overview

OpenPaw ships with 17 built-in tools and 4 message processors. Builtins are discovered at runtime — if prerequisites (API keys, packages) are missing, the builtin is unavailable. The allow/deny system provides fine-grained control over which capabilities are active in each workspace.

**Architecture:**

```
BuiltinRegistry
├─ Tools (17)
│  ├─ browser          Web automation via Playwright
│  ├─ email            Email send/receive via Gmail
│  ├─ brave_search     Web search
│  ├─ spawn            Sub-agent spawning
│  ├─ cron             Agent self-scheduling
│  ├─ cron_manager     Persistent YAML cron management
│  ├─ acknowledge      Silent system event acknowledgment
│  ├─ task_tracker     Persistent task management
│  ├─ send_message     Mid-execution messaging
│  ├─ report_progress  Structured progress reporting
│  ├─ send_file        Send workspace files to users
│  ├─ followup         Self-continuation
│  ├─ plan             Session-scoped planning
│  ├─ channel_history  Channel history browsing
│  ├─ memory_search    Semantic conversation search
│  ├─ shell            Local command execution
│  ├─ md2pdf            Markdown-to-PDF conversion
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
- `browser_screenshot` — Capture page screenshot (saved to `workspace/screenshots/`)
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

Files downloaded by the browser are saved to `{workspace}/workspace/downloads/` with sanitized filenames. Page screenshots are saved to `{workspace}/workspace/screenshots/` and returned as relative paths for agent reference.

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
      default_progress_interval: 5  # Minutes between progress updates (0 = disabled, default: 5)
```

**Tool Exclusions:**

Sub-agents have a restricted tool set to prevent recursion, unsolicited messaging, and persistent side effects:

- **Spawning**: no `spawn_agent` (prevents sub-agent recursion)
- **Messaging**: no `send_message`, `send_file` (sub-agents cannot contact users directly)
- **Self-continuation**: no `request_followup`
- **Scheduling**: no cron or dynamic scheduling tools (side effects outlive the sub-agent)
- **Browser**: no browser tools (browser sessions require a session key for cleanup)
- **Cron manager**: no persistent cron management tools (writes YAML files that persist after the sub-agent exits)
- **Plan**: no session-scoped planning tools (requires session key context)

**Lifecycle:**

`pending` → `running` → `completed`/`failed`/`cancelled`/`timed_out`. Running sub-agents exceeding their timeout are marked as `timed_out` during cleanup.

**Notifications:**

When `notify: true` (default), notifications are injected into the message queue for all terminal states — `completed`, `failed`, `timed_out`, and `cancelled`. Each notification includes a brief result summary and the session log path so the main agent can call `read_file()` on it for the full transcript.

**Progress Updates:**

Sub-agents emit progress updates every 5 minutes by default. Override per-spawn with `progress_interval_minutes`, or change the workspace default with `default_progress_interval` in the spawn config. Set to `0` to disable.

Progress messages are delivered as `[SYSTEM]` events to the main agent's queue and include elapsed time, tools called, and current activity. The main agent decides whether to relay updates to the user.

**Usage Example:**

```
User: "Research topic X in the background while I work on Y"
Agent: [Calls spawn_agent(task="Research topic X...", label="research-x", progress_interval_minutes=5)]
Sub-agent: [Runs concurrently, sends progress every 5 min, main agent continues working on Y]
System: [When complete, user receives notification with result summary]
```

**Limits:**

Maximum 8 concurrent sub-agents (configurable), timeout defaults to 30 minutes (1-120 range). Results are truncated at 50K characters to match `read_file` safety valve pattern.

**Storage:**

Sub-agent state persists to `{workspace}/data/subagents.yaml` and survives restarts. Completed/failed/cancelled requests older than 24 hours are automatically cleaned up on initialization.

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

Tasks persist to `{workspace}/data/dynamic_crons.json` and survive restarts. One-time tasks are automatically cleaned up after execution or if expired on startup.

**Routing:**

Responses are sent back to the first allowed user in the workspace's channel config.

**Usage Example:**

```
User: "Ping me in 10 minutes to check on the deploy"
Agent: [Calls schedule_at with timestamp 10 minutes from now]
System: [Task fires, agent sends reminder to user's chat]
```

---

### cron_manager

**Group:** `automation`
**Type:** Tool (4 functions)
**Prerequisites:** None (always available)

Persistent cron management — create, list, update, and delete YAML cron jobs that survive restarts. Unlike dynamic scheduling (`schedule_at`/`schedule_every`), cron_manager writes YAML files to `config/crons/` that are loaded by the cron scheduler at startup alongside any hand-authored cron files. Changes are also applied to the live scheduler immediately — no workspace restart required.

**Available Functions:**
- `create_cron` — Create a new persistent cron job (validates expression, writes YAML, hot-adds to scheduler)
- `list_crons` — List all YAML crons with name, schedule, enabled status, and next run time
- `update_cron` — Update fields on an existing cron job (hot-reloads in scheduler)
- `delete_cron` — Remove a cron job file and unregister from scheduler

**Configuration:**

```yaml
builtins:
  cron_manager:
    enabled: true
```

**Comparison with Dynamic Scheduling:**

| Feature | Dynamic (`cron`) | Persistent (`cron_manager`) |
|---------|------------------|------------------------------|
| Storage | `data/dynamic_crons.json` | `config/crons/{name}.yaml` |
| Scheduling | One-time or interval-based | Standard cron expressions |
| Lifecycle | Auto-cleaned after execution (one-time) | Permanent until deleted |
| Restarts | Loaded from JSON on restart | Loaded from YAML on restart |
| Use case | "Remind me in 10 minutes" | "Daily summary at 9am" |

**Name Validation:**

Cron names must be lowercase alphanumeric with hyphens only (`^[a-z0-9][a-z0-9-]*$`). Names become filenames (`{name}.yaml`).

**Usage Example:**

```
User: "Set up a daily summary cron at 9am"
Agent: [Calls create_cron(name="daily-summary", schedule="0 9 * * *", prompt="Generate a daily summary...", delivery="channel")]
Agent: "Done — 'daily-summary' will run every day at 9:00 AM and send results to this chat."
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

Tasks persist to `{workspace}/data/TASKS.yaml`. Thread-safe with atomic writes.

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

### report_progress

**Group:** `communication`
**Type:** Tool
**Prerequisites:** None (always available)

Structured progress reporting for long operations. Unlike `send_message`, this tool provides a dedicated schema with status label, optional detail, and optional percentage. Use it when you want to give the user more structured progress information than a plain text message.

**Configuration:**

```yaml
builtins:
  report_progress:
    enabled: true
```

**Usage Example:**

```
User: "Process this large dataset"
Agent: [Calls report_progress("Analyzing data", detail="Processing batch 1 of 10", percent=10)]
Agent: [Continues processing]
Agent: [Calls report_progress("Analyzing data", detail="Processing batch 5 of 10", percent=50, emoji="📊")]
Agent: [Finishes and responds with full results]
```

**Optional Emoji Parameter:**

Pass an `emoji` to prefix the status message with a custom emoji. If omitted, the framework uses a default emoji based on the status label.

```
Agent: [Calls report_progress("Deploying", detail="Pushing to staging", percent=30, emoji="🚀")]
User sees: "🚀 Deploying — Pushing to staging (30%)"
```

**Implementation:**

Uses shared `_channel_context` for session-safe state access to the active channel. Formats messages as: `Status — Detail (Percent%)` with an optional emoji prefix.

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
**Prerequisites:** None (core dependency)

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

### md2pdf

**Group:** `document`
**Type:** Tool
**Prerequisites:** `weasyprint`, `markdown`, `pygments` (core dependencies)

Convert workspace markdown files to polished PDF documents with CSS theming, Mermaid diagram rendering, and AI self-healing for broken diagrams.

**Themes:**

| Theme | Style |
|-------|-------|
| `minimal` | Clean serif font, light styling, academic feel |
| `professional` | Indigo accents, sans-serif, business report look |
| `technical` | Dark code blocks, monospace-heavy, engineering docs |

**Features:**

- Mermaid diagrams rendered via mermaid.ink API (no local dependencies)
- SVG auto-scaling to fit page width
- AI self-healing for broken Mermaid syntax (configurable LLM, default: gpt-4o-mini)
- Syntax-highlighted code blocks via Pygments
- Tables, table of contents, and standard markdown extensions

**Configuration:**

```yaml
builtins:
  md2pdf:
    theme: professional           # minimal, professional, or technical
    max_diagram_width: 6.5        # Max diagram width in inches
    self_heal: true               # AI repair for broken Mermaid diagrams
    self_heal_model: "openai:gpt-4o-mini"  # Any LangChain model spec
    max_heal_iterations: 3        # Max repair attempts per diagram
```

**Self-Healing:**

When a Mermaid diagram fails to render, the tool can optionally invoke a LangGraph subgraph that:

1. Sends the broken source + error to a configurable LLM
2. Validates the repair by re-rendering via mermaid.ink
3. Loops up to `max_heal_iterations` times
4. Marks repaired diagrams with a visual indicator in the PDF

Self-healing requires an API key for the configured model (e.g., `OPENAI_API_KEY` for gpt-4o-mini). If unavailable, the tool degrades gracefully — broken diagrams get an error placeholder instead.

**Usage Example:**

```
User: "Convert my research notes to a PDF"
Agent: [Calls markdown_to_pdf(source_path="reports/notes.md", theme="professional")]
Agent: "PDF created: reports/notes.pdf (3 Mermaid diagrams rendered, 1 repaired by AI)"
```

---

### plan

**Group:** `system`
**Type:** Tool
**Prerequisites:** None (always available)

Session-scoped planning tool for multi-step work. Agents use `write_plan` to externalize their thinking into a structured plan and `read_plan` to retrieve it later. Plans persist for the current session and reset on `/new` or `/compact`.

**Available tools:**

- `write_plan(plan)` — Write or overwrite the session plan
- `read_plan()` — Retrieve the current plan

**When agents use this:**

Agents create plans when tackling complex, multi-step tasks — especially when the work involves multiple tool calls, file operations, or research phases. The plan serves as working memory that survives across tool calls within a single session.

**Usage Example:**

```
User: "Research the latest AI safety papers and write a summary report"
Agent: [Calls write_plan("1. Search for recent AI safety papers\n2. Read top 5 results\n3. Synthesize findings\n4. Write summary to reports/ai-safety.md")]
Agent: [Proceeds to execute each step, updating the plan as steps complete]
```

---

### acknowledge

**Group:** `automation`
**Type:** Tool
**Prerequisites:** None (always available)

Silent acknowledgment for system events. When the agent receives a `[SYSTEM]` event (cron result, heartbeat injection, sub-agent completion) and determines there is nothing the user needs to know, it calls `acknowledge_event` to suppress channel delivery. Everything is still logged — conversation history, token usage, and the acknowledgment reason. Silence means "don't message the user," not "don't record."

**When to use:**

The agent receives a `[SYSTEM]` notification with routine information — a cron ran successfully with no notable output, a heartbeat check found nothing actionable, or a background sub-agent completed a task the user doesn't need to hear about. Instead of sending a noisy "nothing to report" message, the agent calls `acknowledge_event` with a brief reason.

**Key Behaviors:**

- Only suppresses channel delivery for system-originated events. Has no effect on user messages.
- One `acknowledge_event` call per agent invocation — duplicate calls return an error.
- The agent's text response is still written to conversation history; it just isn't delivered to the channel.

**Configuration:**

```yaml
builtins:
  acknowledge:
    enabled: true
```

**Usage Example:**

```
System: [SYSTEM] Cron 'daily-check' completed. Session log: memory/sessions/cron/daily-check_2026-03-25T09-00-00.jsonl
Agent: [Reads session log — routine status, no anomalies found]
Agent: [Calls acknowledge_event(reason="daily-check ran clean, no anomalies to report")]
Agent: "Checked the daily-check cron result — all systems nominal." (not delivered to user)
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

### email

**Group:** `communication`
**Type:** Tool (8 functions)
**Prerequisites:** `poetry install --extras email` (google-auth, google-api-python-client)

Send and receive email via Google service account with domain-wide delegation. Designed with an abstract provider interface for future SMTP/SES support.

**Security Model:**

The email builtin enforces a **safe-by-default** outbound policy via `RecipientPolicy`:
- An **empty `allowed_recipients` list blocks ALL outbound email** — sending must be explicitly enabled
- Recipient patterns use fnmatch glob syntax (e.g., `*@company.com`)
- All recipients (to, cc, bcc) are validated before sending
- Max recipients per message is configurable (default: 10)

**Available Functions:**
- `send_email` — Send email with recipient policy validation and optional file attachments
- `check_email` — List recent messages from a Gmail label (default: INBOX)
- `get_email` — Retrieve full content of a specific email by message ID
- `search_email` — Search using Gmail query syntax (from:, subject:, is:unread, etc.)
- `reply_email` — Reply to an email thread with proper In-Reply-To/References headers
- `download_attachment` — Download email attachment to workspace `downloads/email/`
- `mark_as_read` — Remove UNREAD label from a message
- `mark_as_unread` — Add UNREAD label to a message

**Configuration:**

```yaml
builtins:
  email:
    enabled: true
    config:
      provider: gmail
      service_account_file: config/service-account.json  # Relative to workspace root
      delegated_user: agent@yourdomain.com
      allowed_recipients:                     # Empty = block all sends (safe default)
        - "*@yourdomain.com"
        - "partner@external.com"
      max_recipients: 10
```

**Provider Setup (Gmail):**

1. Create a Google Cloud project with Gmail API enabled
2. Create a service account and download the JSON key file
3. Enable domain-wide delegation on the service account
4. In Google Workspace Admin, authorize the service account with scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.modify`
5. Place the JSON key file in your workspace (e.g., `config/service-account.json`)
6. Set `delegated_user` to the email address the agent should impersonate

**Usage Example:**

```
User: "Check my email for anything from Alice"
Agent: [Calls search_email(query="from:alice@example.com")]
Agent: "Found 3 emails from Alice. The most recent is about the Q4 report..."

User: "Download the PDF attachment from that email"
Agent: [Calls download_attachment(message_id="...", attachment_id="...", filename="q4-report.pdf")]
Agent: "Saved to downloads/email/q4-report.pdf"

User: "Reply and tell her I'll review it by Friday"
Agent: [Calls reply_email(message_id="...", body="Thanks Alice, I'll review the Q4 report by Friday.")]
Agent: "Reply sent to alice@example.com"
```

---

### status_reminder

**Group:** `agent`
**Type:** Middleware (not a tool — operates automatically)
**Prerequisites:** `send_message` builtin must be enabled

Automatic detection of long silent tool-calling runs. When the agent completes multiple tool-calling turns without calling `send_message()`, the middleware injects a reminder to communicate with the user. Uses a three-gate decision model to avoid nagging: threshold (minimum silent turns before first reminder), budget (maximum reminders per run), and cooldown (minimum turns between consecutive reminders).

This is not a tool the agent calls — it operates transparently as middleware on every agent run where `send_message` is available.

**Configuration:**

```yaml
status_reminder:
  enabled: true              # Default: true
  threshold: 5               # Tool-calling turns before first reminder (1-50)
  max_reminders: 3           # Max reminders per agent run (0-20)
  cooldown_turns: 1          # Min turns between consecutive reminders (0-10)
```

**Behavior:**

- Reminders are injected as `<framework_instruction>` tags into existing messages — no extra checkpoint entries, no additional API calls
- Only active when the `send_message` builtin is loaded for the workspace
- Resets between agent runs (each user message starts a fresh count)
- Set `max_reminders: 0` to disable reminders while keeping detection active
- Disabled entirely with `enabled: false`

---

### status_updates

**Group:** `communication`
**Type:** Middleware (not a tool — operates automatically)
**Prerequisites:** None (always available)

Automatic status updates sent to the user during agent execution. The middleware hooks into the agent run to detect and report:
- When the agent starts working (`"Starting work..."`)
- When the agent decides to call tools (`"Using tools: X, Y..."`)
- When a sub-agent is dispatched (`"Dispatched sub-agent: label"`)
- Optionally, per-tool start and completion messages

Status updates are sent directly to the channel, bypassing the agent state to avoid extra LLM calls. They are throttled by time and budget to prevent spam.

This is not a tool the agent calls — it operates transparently as middleware on every agent run.

**Configuration:**

```yaml
status_updates:
  enabled: true              # Default: true
  agent_start: true          # Report "Starting work..." (default: true)
  tool_calls_detected: true  # Report tool usage detection (default: true)
  tool_start: false          # Report per-tool start (default: false)
  tool_complete: false       # Report per-tool completion (default: false)
  subagent_spawned: true     # Report sub-agent dispatch (default: true)
  min_interval_seconds: 3    # Min seconds between auto-updates (default: 3)
  edit_in_place: true        # Edit single message in place (default: true)
```

**Behavior:**

- **Edit-in-place pattern** (default): A single status message is maintained and edited in place. First update sends a new message; subsequent updates edit the same message. The message is deleted after the agent run completes.
- **Run-aware labels**: First run shows `"Starting work..."`, subsequent runs show `"Continuing work..."`.
- **System events skip**: Cron, heartbeat, and sub-agent completion events do not trigger status updates to avoid mid-task confusion.
- Time-based throttle: `min_interval_seconds` between auto-detected status messages
- Deduplication: if the same tool set is detected twice, only report once
- Agent-driven `report_progress` tool calls bypass all throttling
- Resets between agent runs (each user message starts a fresh count)
- Disabled entirely with `enabled: false`

---

## Processors

[![Processor Pipeline](../assets/diagrams/processor-pipeline.png)](../assets/diagrams/processor-pipeline.png)

### file_persistence

**Group:** None
**Type:** Processor
**Prerequisites:** None (always available)

Universal file upload handling with date partitioning. First processor in the pipeline — saves all uploaded files to `{workspace}/data/uploads/{YYYY-MM-DD}/`.

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
[Saved to: data/uploads/2026-02-07/report.pdf]
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
FilePersistence: [Saves to data/uploads/2026-02-17/report.pdf]
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
      default_progress_interval: 5

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
| `system` | shell |
| `context` | timestamp |
| `agent` | spawn, cron, task_tracker, send_message, followup, send_file |
| `automation` | cron_manager, acknowledge |
| `browser` | browser |
| `communication` | email |
| `memory` | memory_search |
| `document` | md2pdf |

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

Most builtins are included in the core install. A few require optional extras:

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

**Memory search:**
```bash
poetry install -E memory
```
Installs: `sqlite-vec`

**Email capabilities:**
```bash
poetry install -E email
```
Installs: `google-auth`, `google-api-python-client`

**All optional builtins:**
```bash
poetry install -E all-builtins
```

**Core dependencies** (included in base `poetry install`):
- `docling`, `easyocr`, `opencv-python-headless` — Document conversion and OCR
- `playwright` — Browser automation
- `langchain-anthropic`, `langchain-openai`, `langchain-aws`, `langchain-xai`, `langchain-fireworks` — LLM providers
- `weasyprint`, `markdown`, `pygments` — Markdown-to-PDF conversion
- Shell tool — No extra dependencies required

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
    - group:system  # Disable shell for security
```

**Security Note:** The shell tool should be denied unless explicitly needed. It is disabled by default and requires explicit enablement.

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

### Shell Tool

The shell tool provides powerful system access and requires careful configuration:

- Disabled by default — must explicitly enable in config
- Use `allowed_commands` for strict allowlisting when possible
- Default `blocked_commands` list prevents common dangerous operations
- Consider constraining `working_directory` to a sandbox
- Never enable in untrusted environments

**Best Practices:**
1. Enable the shell tool only in workspaces that need it
2. Use `group:system` deny rule in untrusted workspaces
3. Configure minimal allowed_commands
4. Monitor logs for blocked command attempts

### Browser Tool

**Domain Security:**
- Use `allowed_domains` allowlist for production workspaces
- `blocked_domains` takes precedence over allowlist
- Wildcard subdomain support with `*.example.com`
- Consider `persist_cookies: false` to avoid session leakage

**Best Practices:**
1. Configure domain allowlist for untrusted agents
2. Monitor the `workspace/downloads/` directory for unexpected files
3. Set reasonable timeout values
4. Review screenshot captures for sensitive data
