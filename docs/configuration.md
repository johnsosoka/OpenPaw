# Configuration

<div align="center">
  <img src="../assets/images/openpaw-fox-1.png" alt="OpenPaw Configuration" width="500">
</div>

OpenPaw uses a two-tier configuration system: global configuration (`config.yaml`) and per-workspace overrides (`agent.yaml`).

Configuration is managed by Pydantic models in `openpaw/core/config/models.py` with loading and merging logic in `openpaw/core/config/loader.py`.

## Global Configuration

The global configuration file (`config.yaml`) defines defaults for all workspaces.

### Complete Example

```yaml
# Path to agent workspaces directory
workspaces_path: agent_workspaces

# Logging configuration
logging:
  level: INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
  directory: logs          # Directory for log files
  max_size_mb: 10          # Maximum log file size before rotation
  backup_count: 5          # Number of backup files to keep
  per_workspace: true      # Create separate log files per workspace

# Queue settings (OpenClaw-inspired)
queue:
  mode: collect          # collect, steer, followup, interrupt
  debounce_ms: 1000      # Wait before processing collected messages
  cap: 20                # Max queued messages per session
  drop_policy: summarize # old, new, summarize

# Lane concurrency limits
lanes:
  main_concurrency: 4      # Interactive message processing
  subagent_concurrency: 8  # Delegated subagent tasks
  cron_concurrency: 2      # Scheduled jobs

# Channel configurations
channels:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users: []
    allowed_groups: []

# Agent defaults
agent:
  # Model format: provider:model_id
  model: anthropic:claude-sonnet-4-20250514
  max_turns: 50
  temperature: 0.7

# Builtin capabilities
builtins:
  allow: []
  deny: []

  brave_search:
    enabled: true
    config:
      count: 5

  whisper:
    enabled: true
    config:
      model: whisper-1

  elevenlabs:
    enabled: true
    config:
      voice_id: 21m00Tcm4TlvDq8ikWAM
      model_id: eleven_turbo_v2_5

  browser:
    enabled: true
    config:
      headless: true
      allowed_domains: []
      blocked_domains: []
      timeout_seconds: 30
      persist_cookies: false

  file_persistence:
    enabled: true
    config:
      max_file_size: 52428800  # 50 MB
      clear_data_after_save: false
```

### Configuration Sections

#### Workspaces Path

```yaml
workspaces_path: agent_workspaces
```

Directory containing agent workspace folders. Can be absolute or relative to config file location.

---

#### Logging

```yaml
logging:
  level: INFO              # Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  directory: logs          # Directory for log files
  max_size_mb: 10          # Max log file size before rotation
  backup_count: 5          # Number of backup files to keep
  per_workspace: true      # Separate log file per workspace
```

**level** — Logging verbosity. Use `DEBUG` for troubleshooting, `INFO` for normal operation.

**directory** — Where log files are written. Created if it doesn't exist.

**max_size_mb** — When a log file exceeds this size, it's rotated.

**backup_count** — Number of rotated log files to keep (e.g., `openpaw.log.1`, `openpaw.log.2`).

**per_workspace** — If `true`, each workspace gets its own log file (e.g., `gilfoyle.log`, `assistant.log`).

---

#### Queue Settings

```yaml
queue:
  mode: collect          # Queue mode
  debounce_ms: 1000      # Debounce delay in milliseconds
  cap: 20                # Max messages per session
  drop_policy: summarize # Policy when cap is reached
```

**mode** — How messages are queued and processed:
- `collect` — Gather messages briefly before processing (default)
- `steer` — Process immediately, redirect agent if new message arrives during run
- `followup` — Process sequentially, no redirection
- `interrupt` — Cancel current processing on new message

**debounce_ms** — Wait time before processing collected messages (only for `collect` mode). This batches rapid-fire messages into a single agent invocation.

**cap** — Maximum queued messages per session. When exceeded, `drop_policy` applies.

**drop_policy** — Action when queue cap is reached:
- `old` — Drop oldest messages
- `new` — Drop newest messages
- `summarize` — Compress old messages into a summary

See [queue-system.md](queue-system.md) for detailed behavior and middleware interactions.

---

#### Lane Concurrency

```yaml
lanes:
  main_concurrency: 4      # User messages
  subagent_concurrency: 8  # Delegated tasks
  cron_concurrency: 2      # Scheduled jobs
```

Controls how many concurrent tasks can run per lane. Higher values allow more parallelism but consume more resources.

**main_concurrency** — Interactive user messages processing

**subagent_concurrency** — Background sub-agent tasks spawned via `spawn_agent`

**cron_concurrency** — Scheduled tasks (static cron YAML + dynamic agent-scheduled jobs)

---

#### Channel Configuration

Channel configuration is typically done per-workspace in `agent.yaml` rather than globally. See [Channels](channels.md) for full setup guides for each platform.

```yaml
# Global defaults (config.yaml) — optional
channels:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users: []
    allowed_groups: []
```

---

#### Agent Defaults

```yaml
agent:
  model: anthropic:claude-sonnet-4-20250514
  max_turns: 50
  temperature: 0.7
```

**model** — Default model for all workspaces. Format: `provider:model_id`.

**max_turns** — Maximum conversation turns before agent stops (prevents infinite loops).

**temperature** — Model temperature (0.0-1.0). Lower = more focused, higher = more creative.

---

#### Builtins Configuration

```yaml
builtins:
  allow: []  # Empty = allow all available
  deny:
    - group:voice  # Deny entire groups

  brave_search:
    enabled: true
    config:
      count: 5  # Number of search results
```

See [builtins.md](builtins.md) for detailed builtin configuration.

---

## Workspace Configuration

Per-workspace configuration (`agent.yaml`) overrides global defaults for a specific agent.

### Location

```
agent_workspaces/<workspace-name>/config/agent.yaml
```

### Complete Example

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
  allowed_users: [123456789]  # Only this user
  allowed_groups: []

queue:
  mode: steer          # Override global queue mode
  debounce_ms: 500     # Faster response

builtins:
  deny:
    - elevenlabs       # Disable TTS for this workspace

  browser:
    enabled: true
    config:
      allowed_domains:
        - "calendly.com"
        - "*.google.com"
      blocked_domains: []
      persist_cookies: true

heartbeat:
  enabled: true
  interval_minutes: 30
  active_hours: "09:00-17:00"
  suppress_ok: true
  delivery: channel
  target_channel: telegram
  target_id: 123456789

approval_gates:
  enabled: true
  timeout_seconds: 120
  default_action: deny
  tools:
    overwrite_file:
      require_approval: true
      show_args: true
```

### Workspace-Specific Fields

#### Basic Identity

```yaml
name: Gilfoyle
description: Sarcastic systems architect
timezone: America/Denver  # IANA timezone identifier
```

**name** — Display name for the agent (optional)

**description** — Brief description (optional)

**timezone** — IANA timezone identifier for scheduling, display, and file partitioning. Defaults to `UTC` if not specified. Examples: `America/Denver`, `Europe/London`, `Asia/Tokyo`.

**Timezone Validation:** Workspace config validates timezone at load time using Pydantic. Invalid IANA identifiers are rejected with a clear error message.

**What uses workspace timezone:**
- Heartbeat active hours window (`active_hours: "09:00-17:00"`)
- Cron schedule expressions (APScheduler `CronTrigger`)
- Agent-created scheduled tasks (`schedule_at` timestamp parsing)
- File upload date partitions (`data/uploads/{YYYY-MM-DD}/`)
- `/status` "tokens today" day boundary
- Display timestamps in conversation archives, task notes, and filesystem listings

**What remains UTC (internal storage):**
- JSONL logs (token_usage.jsonl, heartbeat_log.jsonl)
- Session state (sessions.json)
- Task internal timestamps (created_at, started_at, completed_at in TASKS.yaml)
- Conversation archive JSON sidecar files
- LangGraph checkpoint data

---

#### Model Configuration

```yaml
model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.5
  max_turns: 50
```

**provider** — Model provider: `anthropic`, `openai`, `bedrock_converse`, or any OpenAI-compatible API via `openai` with `base_url`.

**model** — Model identifier (provider-specific).

**api_key** — API key for the model provider. Use `${VAR}` syntax for environment variables.

**temperature** — Model temperature (0.0-1.0).

**max_turns** — Maximum agent turns per run.

**Extra kwargs:** The model config supports `extra="allow"` — any additional fields beyond the standard set are passed through to `init_chat_model()`. This enables OpenAI-compatible APIs via `base_url` and other provider-specific options.

---

#### Channel Configuration

Single channel (backward compatible):

```yaml
channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: [123456789]
  allowed_groups: []
```

Multi-channel (same workspace, multiple platforms):

```yaml
channels:
  - type: telegram
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users: [123456789]
  - type: discord
    token: ${DISCORD_BOT_TOKEN}
    allowed_users: [916552354470461470]
    mention_required: true
    triggers: ["!ask"]
```

**type** — Channel type: `telegram` or `discord`.

**token** — Channel-specific bot token.

**allowed_users** — List of allowed user IDs for this workspace.

**allowed_groups** — List of allowed group/guild IDs for this workspace.

**mention_required** — Only respond in group channels when @mentioned (default: `false`).

**triggers** — List of keyword triggers for group chat activation. Uses OR logic with `mention_required`.

**name** — Explicit channel name (required when using two channels of the same type).

**context_messages** — Number of recent channel messages to fetch as context when the bot is triggered in a group channel (default: `25`, set to `0` to disable). Only applies to group/server messages, not DMs.

**channel_log** — Persistent JSONL logging of all visible channel messages (disabled by default):

```yaml
channels:
  - type: discord
    token: ${DISCORD_BOT_TOKEN}
    allowed_groups: [111222333]
    mention_required: true
    context_messages: 25        # On-demand context fetch (default: 25)
    channel_log:
      enabled: true             # Opt-in, default: false
      retention_days: 30        # Days before old logs are archived (default: 30)
```

Logs are written to `memory/logs/channel/{server}/{channel}/{YYYY-MM-DD}.jsonl` and are readable by the agent via `read_file()` and `grep_files()`. DMs are never logged. See [Channel History](channels.md#channel-history) for full details.

See [Channels](channels.md) for full setup guides, multi-channel configuration, trigger-based activation, and channel history.

---

#### Queue Configuration

```yaml
queue:
  mode: steer
  debounce_ms: 500
```

**mode** — Override global queue mode for this workspace.

**debounce_ms** — Override global debounce delay.

---

#### Heartbeat Configuration

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30           # How often to check in
  active_hours: "09:00-17:00"    # Only run during these hours (optional)
  suppress_ok: true              # Don't send message if agent responds "HEARTBEAT_OK"
  delivery: channel              # Where to deliver: channel, agent, or both
  target_channel: telegram       # Which channel to deliver to
  target_id: 123456789           # Channel-agnostic user/chat ID (preferred over chat_id)
```

**enabled** — Enable proactive heartbeat check-ins.

**interval_minutes** — How often to run heartbeats.

**active_hours** — Only run heartbeats within this window (workspace timezone). Format: `"HH:MM-HH:MM"`. Outside active hours, heartbeats are silently skipped.

**suppress_ok** — If `true` and the agent responds with exactly `"HEARTBEAT_OK"`, no message is sent. This prevents noisy "all clear" messages.

**output** — Where to send heartbeat messages.

See [Scheduling](scheduling.md) for detailed heartbeat behavior including pre-flight skip, task-aware prompts, and the HEARTBEAT_OK protocol.

---

#### Approval Gates Configuration

```yaml
approval_gates:
  enabled: true
  timeout_seconds: 120            # Seconds to wait for user response
  default_action: deny            # Action on timeout: "deny" or "approve"
  tools:
    overwrite_file:
      require_approval: true
      show_args: true             # Show tool arguments in approval prompt
    delete_task:
      require_approval: true
```

---

#### Session TTL

```yaml
# Conversation auto-reset after inactivity (default: 180 minutes, 0 to disable)
session_ttl_minutes: 180

lifecycle:
  notify_session_ttl: true  # Notify user when session expires
```

**session_ttl_minutes** — Auto-resets the conversation (equivalent to `/new`) after the specified minutes of inactivity. The check is lazy — it only triggers when a new message arrives. Set to `0` to disable. Archives are tagged `["ttl_expired"]`.

**enabled** — Enable human-in-the-loop authorization for dangerous tools.

**timeout_seconds** — Seconds to wait for user response before applying `default_action`.

**default_action** — Action on timeout: `approve` or `deny`. This prevents agents from hanging indefinitely.

**tools** — Per-tool approval settings.

When a gated tool is called, execution pauses and the user sees approve/deny buttons in their chat. On approval, the agent re-runs with tool execution allowed. On denial, the agent receives a system message and can adjust its approach. See [Concepts](concepts.md) for a detailed walkthrough of the approval flow.

---

### Merging Behavior

Workspace configuration deep-merges over global configuration:

- **Missing fields** inherit from global config
- **Present fields** override global values
- **Nested objects** merge recursively

**Example:**

**Global config.yaml:**
```yaml
agent:
  model: anthropic:claude-sonnet-4-20250514
  temperature: 0.7
  max_turns: 50
```

**Workspace agent.yaml:**
```yaml
model:
  temperature: 0.5  # Override only temperature
```

**Result:**
```yaml
model:
  provider: anthropic                   # From global (parsed from model string)
  model: claude-sonnet-4-20250514       # From global
  temperature: 0.5                      # From workspace
  max_turns: 50                         # From global
```

---

## Environment Variables

OpenPaw supports environment variable expansion in configuration files using `${VAR_NAME}` syntax. This is handled by `openpaw/core/config/env_expansion.py`.

### Example

```yaml
channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}

model:
  provider: anthropic
  api_key: ${ANTHROPIC_API_KEY}
```

At runtime, OpenPaw expands these from the environment:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Per-Workspace .env Files

Each workspace can have its own `.env` file for workspace-specific secrets:

```
agent_workspaces/my-agent/config/.env
```

These are automatically loaded via `python-dotenv` when the workspace starts.

### Best Practices

1. **Never commit secrets** — Use environment variables for all API keys and tokens
2. **Use .env files** — Create a `.env` file for local development (add to `.gitignore`)
3. **Document required variables** — List all required environment variables in README
4. **Provide defaults** — Set sensible defaults in `config.yaml` where possible

### Required Variables

**For basic operation:**
- At least one channel bot token:
  - `TELEGRAM_BOT_TOKEN` — Telegram bot token
  - `DISCORD_BOT_TOKEN` — Discord bot token
- At least one model provider credential:
  - `ANTHROPIC_API_KEY` — Claude API access
  - `OPENAI_API_KEY` — OpenAI GPT access
  - AWS credentials for Bedrock (see below)

**For optional builtins:**
- `BRAVE_API_KEY` — Web search capability
- `OPENAI_API_KEY` — Whisper audio transcription (also used for GPT models)
- `ELEVENLABS_API_KEY` — Text-to-speech

---

## Model Providers

### Anthropic

```yaml
model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.7
```

**Available models:**
- `claude-sonnet-4-20250514`
- `claude-opus-4-20250514`
- `claude-haiku-4-20250514`

---

### OpenAI

```yaml
model:
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
  temperature: 0.7
```

**Available models:**
- `gpt-4o`
- `gpt-4o-mini`
- `gpt-4-turbo`

---

### AWS Bedrock

OpenPaw supports AWS Bedrock models via the `bedrock_converse` provider. Available models include Kimi K2 Thinking, Claude, Mistral, Amazon Nova, and others.

**Configuration:**

```yaml
model:
  provider: bedrock_converse
  model: moonshot.kimi-k2-thinking
  region: us-east-1  # Optional, defaults to AWS_REGION env var
```

**Available Bedrock Models:**
- `moonshot.kimi-k2-thinking` — Moonshot Kimi K2 (1T MoE, 256K context)
- `us.anthropic.claude-haiku-4-5-20251001-v1:0` — Claude Haiku 4.5
- `amazon.nova-pro-v1:0` — Amazon Nova Pro
- `amazon.nova-lite-v1:0` — Amazon Nova Lite
- `mistral.mistral-large-2402-v1:0` — Mistral Large

**Note:** Newer Bedrock models may require inference profile IDs (prefixed with `us.` or `global.`) instead of bare model IDs. Use `aws bedrock list-inference-profiles` to discover available profiles.

**AWS Credentials:**

Configure via environment variables or AWS CLI profile:

```bash
# Environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Or use AWS CLI profile
aws configure
```

**Region Availability** (Kimi K2): `us-east-1`, `us-east-2`, `us-west-2`, `ap-northeast-1`, `ap-south-1`, `sa-east-1`

**API Key Exclusion:** The `api_key` field is automatically excluded for Bedrock providers (uses AWS credentials instead).

---

### OpenAI-Compatible APIs

Any OpenAI-compatible provider can be used by specifying `base_url` in the workspace model config. Extra kwargs beyond the standard set (`provider`, `model`, `api_key`, `temperature`, `max_turns`, `timeout_seconds`, `region`) are passed through to `init_chat_model()`.

**Example (Moonshot Kimi K2.5):**

```yaml
model:
  provider: openai
  model: kimi-k2.5
  api_key: ${MOONSHOT_API_KEY}
  base_url: https://api.moonshot.ai/v1
  temperature: 1.0
```

This enables any provider that implements the OpenAI API interface (Moonshot, Together AI, Groq, etc.).

---

## Configuration Validation

OpenPaw validates configuration on startup using Pydantic models. Common errors and solutions:

**Missing required field:**
```
ValidationError: field required (type=value_error.missing)
```
**Solution:** Add the missing field to your config file.

**Invalid value:**
```
ValidationError: value is not a valid enumeration member (type=type_error.enum)
```
**Solution:** Check allowed values in this document.

**Environment variable not set:**
```
Error: Environment variable TELEGRAM_BOT_TOKEN not set
```
**Solution:** Export the variable or set it in your `.env` file.

**Invalid timezone:**
```
ValidationError: Invalid IANA timezone identifier: 'America/InvalidCity'
```
**Solution:** Use a valid IANA timezone from the [tz database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

---

## Multiple Configurations

You can maintain multiple configuration files for different environments:

```bash
# Development
poetry run openpaw -c config.dev.yaml -w my-agent

# Production
poetry run openpaw -c config.prod.yaml -w my-agent

# Testing
poetry run openpaw -c config.test.yaml -w my-agent
```

This enables environment-specific settings without modifying workspace files.

**Example use cases:**
- Development: verbose logging, low concurrency, test API keys
- Production: INFO logging, high concurrency, production API keys
- Testing: minimal logging, minimal concurrency, mock channels

---

## Advanced Configuration

### Custom Model Timeout

```yaml
model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  timeout_seconds: 120  # Override default timeout
```

**timeout_seconds** — Maximum time to wait for a model response. Defaults to 60 seconds. Useful for long-running tasks or slow providers.

---

### Queue Modes

The four queue modes — `collect`, `steer`, `interrupt`, and `followup` — control how the system handles messages that arrive while the agent is already working. See [Queue System](queue-system.md) for detailed behavior and examples of each mode.

---

### Builtins Allow/Deny Patterns

**Allow all, deny specific:**
```yaml
builtins:
  allow: []  # Empty = allow all
  deny:
    - elevenlabs
    - group:system
```

**Allow specific, deny all others:**
```yaml
builtins:
  allow:
    - brave_search
    - whisper
  # Everything else is denied (not in allow list)
```

**Allow group, deny one member:**
```yaml
builtins:
  allow:
    - group:voice
  deny:
    - elevenlabs  # Deny takes precedence over allow
```

**Priority:** Deny always takes precedence over allow.

---

## Configuration File Locations

**Global config:**
```
/path/to/project/config.yaml
```

**Workspace config:**
```
agent_workspaces/<workspace-name>/config/agent.yaml
```

**Workspace .env:**
```
agent_workspaces/<workspace-name>/config/.env
```

**Static cron definitions:**
```
agent_workspaces/<workspace-name>/config/crons/*.yaml
```

**Dynamic cron storage:**
```
agent_workspaces/<workspace-name>/data/dynamic_crons.json
```

**Task storage:**
```
agent_workspaces/<workspace-name>/data/TASKS.yaml
```

**Framework-managed state (data/ is write-protected from agents):**
```
agent_workspaces/<workspace-name>/data/
├── conversations.db      # AsyncSqliteSaver checkpoint database
├── sessions.json         # Session/conversation thread state
├── token_usage.jsonl     # Token usage metrics (append-only)
└── subagents.yaml        # Sub-agent requests and results
```

---

## Configuration Tips

### 1. Start with config.example.yaml

Copy the example and modify:

```bash
cp config.example.yaml config.yaml
```

This ensures you have all required sections.

### 2. Use Workspace-Specific Overrides Sparingly

Only override what you need:

```yaml
# Good — only overrides temperature
model:
  temperature: 0.5

# Bad — duplicates global config unnecessarily
model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.5  # This is the only thing that changed
  max_turns: 50
```

### 3. Document Your Environment Variables

Create a `.env.example` file:

```bash
# .env.example
TELEGRAM_BOT_TOKEN=
DISCORD_BOT_TOKEN=
ANTHROPIC_API_KEY=
BRAVE_API_KEY=
OPENAI_API_KEY=
ELEVENLABS_API_KEY=
```

This helps onboarding and documents required credentials.

### 4. Test Configuration Changes

After modifying config, test with verbose logging:

```bash
poetry run openpaw -c config.yaml -w my-agent -v
```

Watch startup logs for validation errors.

### 5. Use Separate Configs for Environments

Don't modify `config.yaml` for different environments. Instead:

```bash
# config.dev.yaml
logging:
  level: DEBUG

# config.prod.yaml
logging:
  level: INFO

# Run with -c flag
poetry run openpaw -c config.dev.yaml -w my-agent
```

---

## Troubleshooting

**Config file not found:**
```
Error: Configuration file not found: config.yaml
```
**Solution:** Ensure the file exists and the path is correct. Use `-c` flag to specify path.

**YAML syntax error:**
```
yaml.scanner.ScannerError: while scanning a simple key
```
**Solution:** Check YAML syntax. Ensure consistent indentation (use spaces, not tabs).

**Environment variable not expanded:**
```
Warning: Token contains literal '${TELEGRAM_BOT_TOKEN}'
```
**Solution:** Ensure the environment variable is set before running OpenPaw.

**Workspace not found:**
```
Error: Workspace 'my-agent' not found in agent_workspaces/
```
**Solution:** Ensure workspace directory exists and contains required identity files (`agent/AGENT.md`, `agent/USER.md`, `agent/SOUL.md`, `agent/HEARTBEAT.md`).

**Model provider error:**
```
Error: Invalid model provider: 'invalid-provider'
```
**Solution:** Use a supported provider: `anthropic`, `openai`, `bedrock_converse`, or configure OpenAI-compatible API via `base_url`.

**Timezone validation error:**
```
ValidationError: Invalid IANA timezone identifier: 'America/InvalidCity'
```
**Solution:** Use a valid IANA timezone. See [list of tz database time zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).
