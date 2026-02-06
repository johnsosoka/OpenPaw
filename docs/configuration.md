# Configuration

OpenPaw uses a two-tier configuration system: global configuration (`config.yaml`) and per-workspace overrides (`agent.yaml`).

## Global Configuration

The global configuration file (`config.yaml`) defines defaults for all workspaces.

### Structure

```yaml
# Path to agent workspaces directory
workspaces_path: agent_workspaces

# Queue settings
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
      model_id: eleven_monolingual_v1
```

### Configuration Sections

#### Workspaces Path

```yaml
workspaces_path: agent_workspaces
```

Directory containing agent workspace folders. Can be absolute or relative to config file.

#### Queue Settings

```yaml
queue:
  mode: collect          # Queue mode
  debounce_ms: 1000      # Debounce delay in milliseconds
  cap: 20                # Max messages per session
  drop_policy: summarize # Policy when cap is reached
```

**mode** - How messages are queued and processed:
- `collect` - Gather messages briefly before processing (default)
- `steer` - Process immediately, cancel in-flight on new message
- `followup` - Process sequentially, no cancellation
- `interrupt` - Cancel current processing on new message

**debounce_ms** - Wait time before processing collected messages (only for `collect` mode)

**cap** - Maximum queued messages per session. When exceeded, `drop_policy` applies.

**drop_policy** - Action when queue cap is reached:
- `old` - Drop oldest messages
- `new` - Drop newest messages
- `summarize` - Compress old messages into a summary

See [queue-system.md](queue-system.md) for detailed behavior.

#### Lane Concurrency

```yaml
lanes:
  main_concurrency: 4      # User messages
  subagent_concurrency: 8  # Delegated tasks
  cron_concurrency: 2      # Scheduled jobs
```

Controls how many concurrent tasks can run per lane. Higher values allow more parallelism but consume more resources.

#### Channel Configuration

```yaml
channels:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}  # Bot token
    allowed_users: []              # Telegram user IDs
    allowed_groups: []             # Telegram group IDs
```

**token** - Telegram bot token. Use environment variable syntax `${VAR}` for secrets.

**allowed_users** - List of allowed Telegram user IDs. Empty list = allow all users.

**allowed_groups** - List of allowed Telegram group IDs. Empty list = allow all groups.

To get your Telegram user ID, message [@userinfobot](https://t.me/userinfobot).

#### Agent Defaults

```yaml
agent:
  model: anthropic:claude-sonnet-4-20250514
  max_turns: 50
  temperature: 0.7
```

**model** - Format: `provider:model-name`. Currently supports `anthropic:*` models.

**max_turns** - Maximum conversation turns before agent stops (prevents infinite loops)

**temperature** - Model temperature (0.0-1.0). Lower = more focused, higher = more creative.

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

## Workspace Configuration

Per-workspace configuration (`agent.yaml`) overrides global defaults for a specific agent.

### Location

```
agent_workspaces/<workspace-name>/agent.yaml
```

### Example

```yaml
name: Gilfoyle
description: Sarcastic systems architect

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
```

### Merging Behavior

Workspace configuration deep-merges over global configuration:

- **Missing fields** inherit from global config
- **Present fields** override global values
- **Nested objects** merge recursively

Example:

**Global config.yaml:**
```yaml
agent:
  model: claude-sonnet-4-20250514
  temperature: 0.7
  max_turns: 50
```

**Workspace agent.yaml:**
```yaml
agent:
  temperature: 0.5  # Override only temperature
```

**Result:**
```yaml
agent:
  model: claude-sonnet-4-20250514      # From global
  temperature: 0.5                     # From workspace
  max_turns: 50                        # From global
```

## Environment Variables

OpenPaw supports environment variable expansion in configuration files using `${VAR_NAME}` syntax.

### Example

```yaml
channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}

agent:
  api_key: ${ANTHROPIC_API_KEY}
```

At runtime, OpenPaw expands these from the environment:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Best Practices

1. **Never commit secrets** - Use environment variables for all API keys and tokens
2. **Use .env files** - Create a `.env` file for local development (add to `.gitignore`)
3. **Document required variables** - List all required environment variables in README
4. **Provide defaults** - Set sensible defaults in `config.yaml` where possible

### Required Variables

For basic operation:
- `ANTHROPIC_API_KEY` - Claude API access
- `TELEGRAM_BOT_TOKEN` - Telegram bot token

For optional builtins:
- `BRAVE_API_KEY` - Web search capability
- `OPENAI_API_KEY` - Whisper audio transcription
- `ELEVENLABS_API_KEY` - Text-to-speech

## Configuration Validation

OpenPaw validates configuration on startup using Pydantic models. Common errors:

**Missing required field:**
```
ValidationError: field required (type=value_error.missing)
```
Solution: Add the missing field to your config file.

**Invalid value:**
```
ValidationError: value is not a valid enumeration member (type=type_error.enum)
```
Solution: Check allowed values in this document.

**Environment variable not set:**
```
Error: Environment variable TELEGRAM_BOT_TOKEN not set
```
Solution: Export the variable or set it in your `.env` file.

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
