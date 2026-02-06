# Getting Started

This guide walks through installing OpenPaw, creating your first agent workspace, and running it with a Telegram channel.

## Prerequisites

- Python 3.11 or higher
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management
- A Telegram Bot Token ([create one with BotFather](https://core.telegram.org/bots#6-botfather))
- An Anthropic API key ([get one here](https://console.anthropic.com/))

## Installation

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/OpenPaw.git
cd OpenPaw
```

2. **Install dependencies**

```bash
# Base installation
poetry install

# Install with optional builtins
poetry install --extras voice      # Whisper transcription + ElevenLabs TTS
poetry install --extras web        # Brave Search
poetry install --extras all-builtins  # All optional capabilities
```

3. **Set up environment variables**

Create a `.env` file or export variables:

```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"

# Optional: For builtins
export BRAVE_API_KEY="your-brave-api-key"           # Web search
export OPENAI_API_KEY="your-openai-api-key"         # Whisper transcription
export ELEVENLABS_API_KEY="your-elevenlabs-api-key" # Text-to-speech
```

## Initial Configuration

1. **Copy the example configuration**

```bash
cp config.example.yaml config.yaml
```

2. **Edit config.yaml**

The default configuration works for most use cases. Key sections:

```yaml
# Path to agent workspaces
workspaces_path: agent_workspaces

# Queue behavior
queue:
  mode: collect       # collect messages briefly before processing
  debounce_ms: 1000   # wait 1 second

# Telegram channel
channels:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}  # Uses environment variable
    allowed_users: []              # Empty = allow all users

# Agent defaults
agent:
  model: anthropic:claude-sonnet-4-20250514
  max_turns: 50
  temperature: 0.7
```

See [configuration.md](configuration.md) for detailed reference.

## Creating Your First Workspace

Each workspace represents an isolated agent with its own personality and behavior.

1. **Create workspace directory**

```bash
mkdir -p agent_workspaces/my-agent
cd agent_workspaces/my-agent
```

2. **Create required markdown files**

Every workspace needs four files:

**AGENT.md** - Capabilities and behavior guidelines

```markdown
# Agent Profile

You are a helpful AI assistant with the following capabilities:
- Answering questions
- Managing tasks
- Providing information

## Communication Style

Be concise and friendly. Use clear, straightforward language.
```

**USER.md** - User context and preferences

```markdown
# User Profile

## Name
John

## Preferences
- Prefers brief responses
- Works in Pacific Time (PT)
```

**SOUL.md** - Core personality and values

```markdown
# Core Values

Be helpful, honest, and respectful.
Prioritize clarity over cleverness.
```

**HEARTBEAT.md** - Current state and session notes (agent can modify this)

```markdown
# Current State

Session started: 2026-02-05
No active tasks.
```

3. **Optional: Add workspace configuration**

Create `agent.yaml` to override global defaults:

```yaml
name: My Agent
description: A helpful assistant

model:
  model: claude-sonnet-4-20250514
  temperature: 0.5

channel:
  type: telegram
  allowed_users: [123456789]  # Your Telegram user ID
```

## Running Your Agent

1. **Single workspace**

```bash
poetry run openpaw -c config.yaml -w my-agent
```

2. **Multiple workspaces**

```bash
poetry run openpaw -c config.yaml -w agent1,agent2
```

3. **All workspaces**

```bash
poetry run openpaw -c config.yaml --all
```

4. **With verbose logging**

```bash
poetry run openpaw -c config.yaml -w my-agent -v
```

## Testing Your Agent

1. Open Telegram and find your bot (search for the bot username)
2. Send a message: "Hello!"
3. The agent should respond based on its personality files

## Next Steps

- [Configure queue behavior](queue-system.md) for your use case
- [Add scheduled tasks](cron-scheduler.md) for automated actions
- [Enable builtins](builtins.md) for web search, voice transcription, or TTS
- [Create custom skills](workspaces.md#skills) using DeepAgents' skill system

## Troubleshooting

**Bot doesn't respond**
- Verify `TELEGRAM_BOT_TOKEN` is set correctly
- Check `allowed_users` list if configured
- Run with `-v` flag for detailed logs

**"Module not found" errors**
- Ensure you're using `poetry run` prefix
- Verify installation: `poetry install`

**"No API key" errors**
- Check environment variables are exported
- Verify `.env` file if using one
- Try setting variables directly in `config.yaml` (not recommended for production)

**Agent responds incorrectly**
- Review workspace markdown files (AGENT.md, USER.md, SOUL.md)
- Check for typos or inconsistent instructions
- Adjust `temperature` in config (lower = more focused, higher = more creative)
