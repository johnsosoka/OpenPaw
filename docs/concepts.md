# Concepts

OpenPaw is built around a small set of ideas that compose into a flexible agent platform. This page explains those ideas — workspaces, built-in tools and processors, scheduling, message queuing, approval gates, conversation memory, and sub-agents — at the level you need to make sense of the deeper documentation. Each section gives you the mental model, a concrete example, and a pointer to the topic-specific guide where you can go further. None of these sections require you to read code or understand implementation details; they are purely about how the system behaves from the outside.

If you've completed [Getting Started](getting-started.md), you already have a running workspace. This page explains what is actually happening behind the scenes and why it is designed that way. Read this before diving into the topic-specific guides — it will save you from reading sections out of context.

---

## Workspaces

A workspace is a fully isolated agent instance. Every workspace has its own identity, its own conversation history, its own scheduled tasks, and its own filesystem sandbox. Two workspaces running at the same time share no state — they cannot read each other's files, they do not share a message queue, and they each respond on their own channel. You can run a personal assistant workspace and a systems monitoring workspace side by side, and they will never interfere with each other.

### Identity Files

Each workspace gets its identity from four markdown files that you write and maintain. These are loaded at startup and become part of the agent's system prompt:

| File | Purpose |
|------|---------|
| `AGENT.md` | Defines what the agent can do, what tools it should use, and any behavioral rules or task boundaries |
| `USER.md` | Describes the person or people who interact with the agent — preferences, background, context the agent should always carry |
| `SOUL.md` | Establishes core personality, values, tone, and communication style |
| `HEARTBEAT.md` | A scratchpad the agent maintains itself to track what it should check during scheduled check-ins |

Changing any of these files and restarting the workspace immediately changes how the agent behaves. There is no code to modify. A workspace named "gilfoyle" might have a terse, systems-focused personality and access to shell tools. A workspace named "assistant" might have a warm, conversational personality and access to calendar integrations. The same underlying framework powers both — only the markdown files differ.

The identity files are intentionally separate from each other. `AGENT.md` describes capability and behavior. `USER.md` describes the person being served. `SOUL.md` describes how the agent expresses itself. Keeping these concerns in separate files makes each one easier to reason about and update independently. You can refine the personality in `SOUL.md` without touching the capability definition in `AGENT.md`.

!!! tip "Start with the scaffold"
    Running `poetry run openpaw init my_agent` generates all four files with `TODO` markers to guide you. The `AGENT.md` scaffold includes a capabilities section, a limitations section, and placeholder instructions for tool use. Edit these before customizing anything else.

### Filesystem Sandbox

Each workspace has a sandboxed filesystem. The agent can read and write files within its own workspace directory — notes, task lists, research output, downloaded documents — but it cannot reach files outside that boundary. If you have two workspaces, neither can read the other's files.

Framework internals such as the conversation database and token usage logs are additionally protected. The agent cannot read or overwrite them, even though they live inside the workspace directory. This means an agent cannot accidentally corrupt its own conversation history or tamper with session state.

The sandbox supports a full set of file operations: listing directories, reading and writing files, searching by glob pattern, and grepping file contents. Agents are encouraged to use their workspace filesystem as a persistent scratch space — writing notes between sessions, maintaining task lists, and organizing output from background research. A well-organized workspace filesystem lets the agent build institutional memory over time without relying on external storage.

[![Workspace Structure](../assets/diagrams/workspace-structure.png)](../assets/diagrams/workspace-structure.png)

### Isolation and Concurrency

When you run multiple workspaces with `--all`, OpenPaw launches each workspace concurrently. They share the same process but nothing else. Each workspace has its own queue, its own channel connection, its own scheduler, and its own conversation database file. A failure in one workspace — a bad API call, an exception in a tool — does not affect the others.

This isolation also applies to configuration. A workspace can override the global model, queue mode, and built-in configuration without affecting other workspaces. You define defaults globally in `config.yaml` and override only what differs in each workspace's `agent.yaml`. For example, you might run most workspaces on a cost-efficient model globally, but configure one specialized workspace to use a more capable model for demanding tasks.

Each workspace also has its own channel — a Telegram bot, for instance. One workspace can listen on one bot token while another listens on a different token. Users who interact with each bot only see responses from the workspace connected to that bot. Channel access control (allowlisted user IDs or groups) is configured per workspace in `agent.yaml`.

### Custom Tools

Beyond the built-in tools that OpenPaw provides, each workspace can load its own custom tools from a `tools/` directory inside the workspace. These are standard Python functions decorated with `@tool` from LangChain. You can load any library, call any API, or run any logic — as long as it returns a string the agent can read.

```python
from langchain_core.tools import tool

@tool
def get_current_sprint(project: str) -> str:
    """Return the current sprint goals for a Jira project.

    Args:
        project: The Jira project key

    Returns:
        A summary of the current sprint goals
    """
    # Your implementation here
    return fetch_sprint_data(project)
```

If your custom tools require additional Python packages, add a `tools/requirements.txt` file to the workspace. OpenPaw installs missing dependencies automatically at workspace startup, so you do not need to modify the global dependency configuration.

Custom tools in one workspace are not available to other workspaces. Each workspace's tool directory is loaded exclusively for that workspace. This keeps each workspace's capability set explicit and controlled.

See [Workspaces](workspaces.md) for a complete walkthrough of the directory layout, identity files, custom tools, and advanced workspace patterns.

---

## Built-in Tools and Processors

OpenPaw ships with two categories of optional capabilities: tools and processors. Understanding the difference matters because they operate at different points in the message lifecycle and serve different roles.

### Tools

Tools are capabilities the agent chooses to invoke. The agent sees a list of available tools and decides when and whether to call them — just like a function call in code. When the agent decides to search the web, browse a URL, spawn a background worker, create a scheduled task, or send you a mid-run status update, it calls a tool.

The built-in tools cover several categories:

| Category | Examples |
|----------|---------|
| Information retrieval | Web search via Brave, browser navigation and interaction |
| File operations | Reading, writing, editing, globbing, and grepping within the sandbox |
| Communication | Sending messages or files to the user during long-running tasks |
| Autonomy | Self-scheduling, spawning sub-agents, self-continuation across turns |
| Organization | Task tracking via a persistent task list, session-scoped planning |

Tools are registered with the agent at startup. If a tool's prerequisites are not met — for example, the Brave Search tool requires a `BRAVE_API_KEY` — the tool is silently skipped and the agent does not see it. You can also explicitly deny tools or entire capability groups using the `builtins.deny` configuration.

### Processors

Processors run automatically on every inbound message before the agent sees it. They are transparent middleware: the user sends a message, processors transform it, and the agent receives the enriched result. The agent never sees raw file bytes or unprocessed audio.

The three built-in processors are:

- **File persistence** — Saves every uploaded file to the workspace's `uploads/` directory with date partitioning. Sets metadata so downstream processors know where to find the file on disk. Enabled by default.
- **Whisper transcription** — Converts voice messages and audio files to text. Requires `OPENAI_API_KEY`. The transcript appears inline in the message the agent receives, alongside the original file path.
- **Docling document conversion** — Converts PDFs, DOCX files, PPTX presentations, and other documents to markdown. The converted markdown appears inline. Requires the `docling` package, which is a core dependency.

Processors run in a fixed order: file persistence first, then transcription, then document conversion. This order matters — file persistence saves the file to disk so the downstream processors can read it from a known path rather than handling raw bytes. The agent sees the final enriched message and can act on the extracted content without any awareness of the transformation pipeline.

### Configuring Built-ins

The `builtins` configuration block appears in both `config.yaml` (global defaults) and `agent.yaml` (per-workspace overrides). You can allow or deny capabilities at the individual tool level or by group:

```yaml
builtins:
  # Deny an entire capability group
  deny:
    - group:voice    # Disables both Whisper transcription and ElevenLabs TTS

  # Configure a specific tool
  brave_search:
    enabled: true
    config:
      count: 10      # Return 10 results per search

  # Configure a specific processor
  whisper:
    enabled: true
    config:
      model: whisper-1
```

!!! note "API key gating"
    Tools with API key prerequisites are automatically disabled if the key is not set. You do not need to explicitly disable them — missing credentials are enough. The agent simply does not see tools whose prerequisites are unmet.

See [Built-ins](builtins.md) for the full list of tools and processors, their prerequisites, group memberships, and all configuration options.

---

## Scheduling

OpenPaw supports two distinct kinds of scheduled activity: cron jobs and heartbeats. They serve different purposes and run independently. Understanding the difference helps you decide which one to reach for.

### Cron Jobs

A cron job runs a specific prompt on a schedule. You define cron jobs as YAML files in your workspace's `crons/` directory. When the scheduled time arrives, the framework constructs a fresh agent instance, runs it with your prompt, and delivers the result to the configured destination.

```yaml
name: daily-summary
schedule: "0 9 * * *"    # Every day at 9:00 AM (workspace timezone)
enabled: true

prompt: |
  Review active tasks and workspace state.
  Provide a brief daily summary of pending work and any blockers.

output:
  channel: telegram
  chat_id: 123456789
  delivery: channel       # channel, agent, or both
```

The `schedule` field uses standard cron syntax: `minute hour day-of-month month day-of-week`. Schedules fire in the workspace's configured timezone. A job scheduled at `0 9 * * *` runs at 9:00 AM in your local timezone, not UTC.

The `delivery` field controls where the result goes. `channel` sends it directly to you. `agent` injects the result into the main agent's message queue as a system event, so the interactive agent can react to it and take follow-up actions. `both` does both simultaneously.

Cron agents are stateless — each run starts with a fresh context and no conversation history. This is by design. A cron job that relies on prior state is fragile. Instead, write prompts that instruct the agent where to look for current state: "read TASKS.yaml and summarize what is in progress," or "read the latest file in uploads/ and report its contents." The workspace filesystem bridges stateless cron runs — the cron agent writes output to a file, and the main agent or the next cron run can read it.

Common cron patterns include daily digests, nightly cleanup tasks, periodic API polling, and timed reminders. Because each cron agent is independent and stateless, you can run many of them in parallel without risk of interference.

!!! tip "Disable without deleting"
    Set `enabled: false` to pause a cron job without removing the file. This is useful when you want to temporarily stop a job and resume it later.

### Dynamic Scheduling

Agents can schedule their own tasks at runtime using the scheduling tool. This enables patterns like "remind me in 20 minutes" or "check this deploy every 15 minutes for the next hour." The agent calls the scheduling tool with a timestamp or interval and a prompt, and the framework handles the rest.

Dynamic tasks persist across restarts. If you restart a workspace, any agent-created scheduled tasks survive and will fire on schedule. One-time tasks are automatically cleaned up after they execute. Recurring tasks continue firing until the agent or a user explicitly cancels them. This makes dynamic scheduling suitable for autonomous workflows that span multiple sessions.

The agent manages its own scheduled tasks through four operations: create a one-time task, create a recurring task, list pending tasks, and cancel a task by ID. These operations are available as tools the agent can call, which means you can instruct the agent in plain language: "set a reminder for 3pm to check on the database migration" or "poll the build status every ten minutes until it passes."

### Heartbeats

Heartbeats are proactive agent check-ins. Rather than waiting for you to send a message, a heartbeat wakes the agent on an interval so it can evaluate its own state and report anything that needs your attention.

The key difference between a heartbeat and a cron job is intent. A cron job executes a fixed, well-defined prompt on a schedule — "generate a daily summary," "fetch stock prices," "check for new emails." A heartbeat runs the agent in a more open-ended mode, asking it to review `HEARTBEAT.md`, check active tasks, and decide whether there is anything worth reporting. The agent itself determines what to check and whether to speak up.

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30
  active_hours: "09:00-17:00"    # Only run during these hours (workspace timezone)
  suppress_ok: true               # Don't message the user if nothing to report
  delivery: channel
  output:
    channel: telegram
    chat_id: 123456789
```

The `active_hours` field limits heartbeats to a window of time in the workspace timezone. Outside that window, heartbeats are silently skipped — no agent run, no API call, no message. This prevents the agent from messaging you at 3:00 AM about things that can wait until morning, and it keeps API costs predictable by bounding when scheduled calls can occur.

If you do not configure `active_hours`, heartbeats run at all hours. This is appropriate for monitoring workspaces that should alert you immediately regardless of time of day.

### The HEARTBEAT_OK Protocol

When `suppress_ok` is enabled (the default), the agent can respond with exactly `HEARTBEAT_OK` to indicate there is nothing to report. The framework silently discards this response and does not send you any notification. This prevents a stream of "all clear" messages when your workspace is idle. The agent learns this convention from its system prompt — you do not need to instruct it manually. Simply enabling heartbeats gives the agent the context it needs to use `HEARTBEAT_OK` appropriately.

This protocol also enables the pre-flight skip optimization. Before making any API call, the scheduling engine checks whether `HEARTBEAT.md` has meaningful content and whether any active tasks exist in the workspace. If both are empty, the heartbeat fires at zero cost — no language model call, no API usage, no message. For idle workspaces, this means heartbeat scheduling adds negligible overhead regardless of how frequently you configure it to run.

When active tasks do exist, a compact task summary is automatically injected into the heartbeat prompt. The agent sees what tasks are in progress without needing to call the task listing tool — saving a round trip and reducing token usage.

[![Heartbeat Decision Flow](../assets/diagrams/heartbeat-decision.png)](../assets/diagrams/heartbeat-decision.png)

See [Scheduling](scheduling.md) for the full cron file format, heartbeat configuration fields, dynamic task scheduling, delivery routing, and session logging for scheduled runs.

---

## Message Queue

When you interact with an AI assistant, there is an inherent tension: you might send a new message while the agent is still working on your previous one. Language model calls take time, and users do not always wait. The message queue controls how the agent handles this situation.

Every workspace has a configurable queue mode. The mode determines what happens when a new message arrives during an active agent run. You set the default mode in `config.yaml` or `agent.yaml`, and you can switch modes at runtime without restarting using the `/queue` command.

### Why This Matters

Without a queue, you face two bad options: either discard the agent's in-progress work whenever a new message arrives, or make the user wait in silence with no way to redirect the agent mid-task. Neither is acceptable for a useful assistant.

The queue system gives you a spectrum of behaviors between those extremes. Each mode makes a different trade-off between responsiveness and continuity. The right choice depends on your workspace's purpose and your own working style.

### Collect Mode (Default)

In collect mode, new messages accumulate in a queue while the agent works. When the agent finishes its current task, the framework combines all queued messages into a single input and processes them together. A debounce window — one second by default — groups rapid-fire messages into a single batch before processing begins.

Collect mode is the right default for most conversational workspaces. It respects your full input before the agent responds, and it ensures the agent completes what it was doing before taking on new work. The agent is never interrupted mid-task. If you send three messages in quick succession, they arrive as a single combined message after the debounce window closes.

```yaml
queue:
  mode: collect
  debounce_ms: 1000    # Group messages sent within 1 second of each other
```

### Steer Mode

In steer mode, the agent actively monitors for new messages while it runs. When a new message arrives during a tool call, the agent skips its remaining planned tool calls and receives your new message alongside its current context. The agent sees both what it was working on and what you just sent — and it can adjust course accordingly.

Steer mode is useful when you want the agent to be responsive to course corrections without completely discarding in-progress work. If the agent is halfway through a multi-step research task and you realize the direction is wrong, steer mode lets you redirect it without starting over from scratch. The agent is informed of which tool calls it skipped, so it knows what it did and did not complete before receiving your new direction.

### Interrupt Mode

In interrupt mode, any new message during an active run causes the current run to abort immediately. The partial response is discarded, and the new message is processed from scratch as if the previous run never started.

This is the most aggressive mode. Use it when strict responsiveness matters more than continuity — for example, in a time-sensitive operations context where a mid-run "stop, this changed" message needs to take full effect immediately. The trade-off is clear: in-progress work is always lost when you send a new message during a run.

### Followup Mode

Followup mode is reserved for the agent's self-continuation capability. When an agent uses the followup tool to chain multi-step autonomous work — executing a plan across multiple agent turns without waiting for user input — messages flow through a dedicated queue to continue the task. You do not set this mode manually; it activates automatically when the self-continuation tool is in use.

[![Queue Modes](../assets/diagrams/queue-modes.png)](../assets/diagrams/queue-modes.png)

You can switch modes at runtime without restarting the workspace:

```
/queue steer
/queue collect
/queue interrupt
```

!!! tip "Choosing a mode"
    Start with `collect` for interactive assistants. Switch to `steer` if you find yourself wanting to redirect the agent mid-task. Reserve `interrupt` for operational or monitoring workspaces where responsiveness is the top priority.

See [Queue System](queue-system.md) for detailed behavior descriptions, sequence diagrams, timing considerations, and guidance on choosing the right mode.

---

## Approval Gates

Approval gates add a human-in-the-loop checkpoint for sensitive operations. When the agent attempts to call a gated tool, execution pauses and the framework sends you a prompt asking you to approve or deny the action. The agent does not proceed until you respond.

### How It Works

The flow is straightforward:

1. The agent determines it needs to perform a sensitive action — for example, overwriting a file with new content.
2. The framework intercepts the tool call before it executes and sends you an approval request. If `show_args: true` is configured, you see the tool name and its arguments — in this case, the filename and the new content.
3. You tap **Approve** or **Deny**.
4. If you approve, the agent continues exactly where it left off and the tool executes normally.
5. If you deny, the agent receives a message indicating the action was not permitted. It typically responds by explaining what it could not do or asking you how to proceed differently.

The entire interaction is synchronous from the agent's perspective — it does not know how long it waited. From your perspective, the agent is simply paused until you respond. Approval gates work at the tool level, so you can gate specific operations while leaving others ungated.

### Timeout Behavior

Approval gates have a configurable timeout. If you do not respond within the timeout window, the gate resolves according to the `default_action` setting. A `default_action` of `deny` is the safer choice — if you step away and miss the prompt, the agent does not proceed with potentially destructive operations on its own.

```yaml
approval_gates:
  enabled: true
  timeout_seconds: 120       # Wait up to 2 minutes for a response
  default_action: deny       # Deny if no response within timeout

  tools:
    overwrite_file:
      require_approval: true
      show_args: true        # Show the filename and content in the approval prompt
    delete_task:
      require_approval: true
      show_args: false       # Show only the tool name, not arguments
```

!!! warning "Cron and heartbeat agents are excluded"
    Scheduled agents (cron jobs, heartbeats, sub-agents) do not have approval gates. Gates only apply to the main interactive agent running in response to your messages. A cron job that calls `overwrite_file` will not pause for approval — design scheduled prompts with this in mind.

See [Configuration](configuration.md) for the full approval gates configuration reference including all supported fields.

---

## Conversation Memory

Conversations persist across restarts. When you stop and restart a workspace, the agent resumes with full knowledge of your prior exchanges. The conversation is stored in a durable local database — not in memory — so a crash or planned restart does not lose your history.

Each conversation has a thread identifier that the agent uses to retrieve prior context. As long as you stay in the same thread, the agent always has the full conversation history available, regardless of how many times the workspace has been restarted between sessions.

### Starting Fresh

Two commands let you manage conversation boundaries:

- `/new` — Archives the current conversation to disk and starts a clean thread. The agent begins with no memory of the archived conversation.
- `/compact` — Summarizes the current conversation, archives it, then starts a new thread with the summary injected as context. The agent retains high-level continuity without carrying the full token history.

Use `/compact` when a conversation has grown long and you want to preserve context without carrying the full history into the next session. Use `/new` when you genuinely want a fresh start — no carryover, no summary, clean slate.

!!! tip "When to compact"
    Conversations naturally grow toward the model's context limit. Compacting before you hit that limit gives the agent a clean, focused summary to work from. If you wait until the context is nearly full, earlier parts of the conversation may already be compressed or dropped by the model.

### Auto-Compact

When auto-compact is enabled, the workspace monitors context window utilization before each agent run. If the conversation exceeds a configured threshold — for example, 80% of the model's context window — the workspace automatically performs a compact before processing your next message. You receive a notification that this happened, and the conversation continues in the new thread with the summary already injected.

```yaml
auto_compact:
  enabled: true
  trigger: 0.8             # Trigger at 80% context utilization
  summary_model: null      # Use the workspace model for summaries (null = default)
```

Auto-compact uses the same mechanism as `/compact` — it summarizes, archives, and starts fresh. The only difference is that it happens automatically when the threshold is crossed, so you do not have to remember to compact long-running conversations manually.

### Conversation Archives

When a conversation ends — whether via `/new`, `/compact`, auto-compact, or workspace shutdown — it is archived to the workspace's `memory/conversations/` directory. Archives are saved in two formats:

- **Markdown** — A human-readable transcript of the full conversation, useful for reviewing past interactions and understanding what the agent did.
- **JSON** — A machine-readable version of the same data, suitable for automated processing or analysis.

The agent can read archived conversations using its filesystem tools. This allows long-running projects to span multiple conversation threads — the agent starts a new thread, reads the relevant archive, and picks up where it left off with full context about prior decisions and work.

### Session Logging for Scheduled Runs

Cron jobs, heartbeats, and sub-agents all write structured session logs to the workspace's `memory/sessions/` directory. Each log captures the prompt that was used, the agent's response, the tools it called, and token usage metrics.

These logs serve two purposes. First, they create an audit trail so you can see exactly what the agent did during a scheduled run without setting up external logging. Second, they give the main interactive agent a way to learn about scheduled activity — it can read a heartbeat log to understand what was checked overnight, or read a cron session to see what the daily summary contained.

```
memory/
├── conversations/           # Interactive conversation archives
│   ├── conv_2026-03-01.md
│   └── conv_2026-03-01.json
└── sessions/                # Scheduled run logs
    ├── heartbeat/           # Heartbeat session JSONL files
    ├── cron/                # Cron job session JSONL files
    └── subagent/            # Sub-agent session JSONL files
```

See [Workspaces](workspaces.md) for the full filesystem layout, archive formats, and guidance on organizing long-running projects across multiple conversation threads.

---

## Sub-Agents

Sub-agents are background workers the main agent can spawn to run tasks concurrently. While the main agent continues interacting with you, a sub-agent works independently on a separate, well-defined task. When the sub-agent finishes, the main agent receives a notification and can retrieve the full result.

### What Sub-Agents Can Do

A sub-agent has access to most of the same tools as the main agent — web search, browser automation, file operations, and so on. The important difference is what sub-agents cannot do: they cannot spawn their own sub-agents, they cannot send you messages directly, and they cannot create scheduled tasks. These restrictions prevent runaway recursion and ensure sub-agents remain focused, single-purpose workers rather than autonomous agents that grow in scope.

Sub-agents run in their own isolated context with no shared conversation history. They do not affect the main agent's thread, and their output does not appear directly in the conversation. Instead, when a sub-agent completes, the main agent receives a notification containing a brief summary of the result. The main agent can then retrieve the full output using the sub-agent's ID and decide how to present or act on it.

### A Typical Sub-Agent Interaction

> **You:** "Research the top five open-source vector databases and compare them on performance, ease of use, and license. Keep chatting with me while that runs."
>
> **Agent:** "I've kicked off a background research task labeled 'vector-db-comparison'. While that runs, what else can I help with?"
>
> *(A few minutes later, after the sub-agent finishes)*
>
> **Agent:** "The vector database research is done. Here's the summary: Chroma and Qdrant scored highest for ease of use, both under Apache 2.0. Weaviate has the most features but more operational complexity. Want me to write the full comparison to a file?"

The main agent remained responsive throughout. You could have sent additional messages, asked other questions, or redirected the conversation — and the sub-agent would have kept running in the background regardless.

### Concurrency and Limits

Up to eight sub-agents run concurrently by default. You can adjust this limit in configuration. Each sub-agent also has a configurable timeout — by default, 30 minutes — after which it is marked as timed out and its result is discarded.

```yaml
builtins:
  spawn:
    enabled: true
    config:
      max_concurrent: 8     # Maximum simultaneous sub-agents
```

Each sub-agent run produces a session log in `memory/sessions/subagent/` capturing the full prompt, the agent's response, the tools it used, and token metrics. The main agent can read these logs for the complete picture beyond the brief notification summary.

!!! tip "When to use sub-agents"
    Sub-agents work best for tasks that are well-defined, independent, and time-consuming — things like "research these ten papers and extract the key findings" or "convert all PDFs in uploads/ to markdown and summarize each one." For quick lookups that take a few seconds, a direct tool call is simpler and faster than spawning a sub-agent.

!!! note "Notification delivery"
    When a sub-agent completes, the main agent receives a brief summary (up to 500 characters) injected into its message queue. For the full result, the main agent uses the result retrieval tool with the sub-agent's ID. The complete output is also always available in the session log file.

See [Built-ins](builtins.md) for the complete sub-agent configuration, available tools, and guidance on designing effective sub-agent tasks.

---

## Framework Commands

A small set of slash commands let you interact with the framework itself rather than the agent. These commands are intercepted before they reach the agent and are handled directly by the platform. They work regardless of which model is running and do not consume tokens.

| Command | What it does |
|---------|-------------|
| `/help` | Lists all available commands with descriptions |
| `/status` | Shows the active model, context window utilization, conversation statistics, active tasks, active sub-agents, and token usage for today and the current session |
| `/new` | Archives the current conversation and starts a fresh thread |
| `/compact` | Summarizes the conversation, archives it, and starts fresh with the summary injected |
| `/queue <mode>` | Changes the queue mode for the current workspace (`collect`, `steer`, `interrupt`) |
| `/model [provider:model]` | Shows the active model or switches to a different one at runtime |
| `/model reset` | Reverts to the model configured in `agent.yaml` |

The `/model` command enables live model switching without restarting the workspace or losing conversation history. If you want to try a different model for a specific task, you can switch, complete the task, and switch back — all within the same conversation. Runtime model overrides are ephemeral; they reset when the workspace restarts. Scheduled agents (cron, heartbeat, sub-agents) always use the model from `agent.yaml`, regardless of any runtime override on the interactive agent.

```
/model openai:gpt-4o
/model anthropic:claude-opus-4-20250514
/model reset
```

!!! note "Commands are channel-aware"
    Commands are processed at the channel layer, before any inbound processors run. This means commands work correctly even in workspaces with active document conversion or transcription processors.

---

## Provider Catalog

When you run multiple workspaces, repeating the same API key and connection details in every `agent.yaml` is tedious and error-prone. The provider catalog lets you define connection details once in the global `config.yaml` and reference them by name from any workspace.

```yaml
# config.yaml (global)
providers:
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
  openai:
    api_key: ${OPENAI_API_KEY}
  moonshot:
    type: openai                          # Uses OpenAI-compatible API
    api_key: ${MOONSHOT_API_KEY}
    base_url: https://api.moonshot.ai/v1
```

With the catalog defined, individual workspaces reference providers by name using a simple `provider:model` shorthand:

```yaml
# agent.yaml (workspace)
model: moonshot:kimi-k2.5
temperature: 0.6
```

When the workspace starts, the framework resolves "moonshot" against the catalog, retrieves the API key and base URL, and passes them to the model — no duplication required. Adding a new workspace that uses the same provider takes one line instead of five.

The catalog also powers the `/model` command. When you switch models at runtime with `/model moonshot:kimi-k2.5`, the framework resolves the provider name through the catalog and applies the correct connection details automatically.

The provider catalog supports all connection types that OpenPaw understands: Anthropic, OpenAI, xAI (Grok), AWS Bedrock, and any OpenAI-compatible API endpoint. For Bedrock, there is no API key field — the framework uses your configured AWS credentials instead. The catalog handles that detail automatically based on the provider type.

See [Configuration](configuration.md) for the full provider catalog reference, all supported provider types, and AWS Bedrock configuration.

---

## How the Pieces Connect

Each concept on this page is independent, but they are designed to work together. Here is how a realistic workflow touches multiple systems at once.

Imagine a workspace configured as a research assistant. You send a PDF — the file persistence processor saves it, and the Docling processor converts it to markdown. The agent receives the enriched message and begins reading the document. While reading, it calls a web search tool to look up references. You notice it is going in the wrong direction and send a correction — in steer mode, the agent receives your message and adjusts course without discarding its work. It writes a summary to a file in the workspace. A cron job runs at 9:00 AM the next day, reads the summary file, and sends you a formatted digest. Meanwhile, you asked the agent to research three follow-up topics — it spawns three sub-agents to run in parallel, then assembles the results into a final report.

That sequence touches seven distinct systems: inbound processors, filesystem tools, web search, the message queue, scheduled cron jobs, conversation persistence, and sub-agent spawning. Each system is configured independently and has its own documentation page, but they operate as a coherent whole.

The workspace is the unit of isolation. Everything else — tools, processors, scheduling, queuing, memory — operates within a workspace's boundary. When you understand workspaces, the rest of the concepts fall into place as capabilities that a workspace can enable or configure.

One useful way to think about the overall system: the workspace defines *what* the agent is, the identity files define *who* it is, the queue determines *how* it responds to you, and scheduling, memory, and sub-agents determine *what it does when you are not there*. Each dimension is independently configurable, which is what makes OpenPaw flexible enough to serve as both a personal assistant and an autonomous monitoring agent — often in the same installation.

For a visual overview of how components relate to each other, see [Architecture](architecture.md).

---

*Ready to go deeper? The sidebar navigation takes each concept on this page and expands it into a full reference: [Configuration](configuration.md) for all config fields, [Workspaces](workspaces.md) for the filesystem and identity system, [Scheduling](scheduling.md) for cron and heartbeat details, [Built-ins](builtins.md) for tools and processors, [Queue System](queue-system.md) for queue mode behavior, and [Architecture](architecture.md) for design rationale and system diagrams.*
