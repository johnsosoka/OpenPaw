# Getting Started

<div align="center">
  <img src="../assets/images/openpaw-golden.png" alt="Getting Started with OpenPaw" width="500">
</div>

This guide walks through installing OpenPaw, creating your first agent workspace, and running it. Examples use Telegram, but Discord is also supported — see [Channels](channels.md) for Discord setup and multi-channel configuration.

## Prerequisites

- **Python 3.11+**
- **Poetry 2.0+** for dependency management ([installation guide](https://python-poetry.org/docs/#installation))
- **A channel (choose one):**
  - **Stdio** *(work in progress)* — Zero-config terminal channel for quick local testing; not recommended for actually operating a bot (log output interleaves with the chat)
  - **Telegram** — Bot token from [@BotFather](https://core.telegram.org/bots#botfather)
  - **Discord** — Bot token from [Developer Portal](https://discord.com/developers/applications)
- **At least one model provider credential:**
  - Anthropic API key ([get one here](https://console.anthropic.com/))
  - OpenAI API key ([get one here](https://platform.openai.com/api-keys))
  - AWS credentials for Bedrock ([configure AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html))

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/johnsosoka/OpenPaw.git
cd OpenPaw
```

### 2. Install Dependencies

```bash
# Core installation (lean — no OCR/CV stack)
poetry install

# Install the Playwright browser (only needed for the browser builtin)
poetry run playwright install chromium
```

### 3. Optional Extras

Install additional builtins based on your needs:

```bash
# Document conversion + OCR (Docling; pulls torch — large)
poetry install -E documents

# Voice capabilities (Whisper transcription + ElevenLabs TTS)
poetry install -E voice

# Web search (Brave Search API)
poetry install -E web

# Memory search (semantic search over past conversations)
poetry install -E memory

# Install everything
poetry install -E all-builtins
```

**Extra descriptions:**

| Extra | Provides | Requires |
|-------|----------|----------|
| `documents` | Docling PDF/DOCX/PPTX → markdown conversion with OCR | pulls `torch`, `easyocr`, `opencv` (large) |
| `voice` | Whisper audio transcription, ElevenLabs text-to-speech | `OPENAI_API_KEY`, `ELEVENLABS_API_KEY` |
| `web` | Brave Search web search | `BRAVE_API_KEY` |
| `memory` | Semantic search over conversation archives | `sqlite-vec` package |
| `all-builtins` | All of the above | All API keys above |

**Note:** Playwright (browser automation) and all LLM providers (Anthropic, OpenAI, AWS Bedrock, xAI, Fireworks.ai) are **core dependencies** installed automatically with `poetry install`. Document conversion (Docling) lives behind the `documents` extra because its OCR/CV stack pulls `torch` and hundreds of MB — install it only if you need scanned-PDF/OCR features.

### 4. Set Up Environment Variables

Create a `.env` file or export variables:

```bash
# Required: Channel (at least one)
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
export DISCORD_BOT_TOKEN="your-discord-bot-token"

# Required: Model provider (choose at least one)
export ANTHROPIC_API_KEY="your-anthropic-key"        # Anthropic Claude
export OPENAI_API_KEY="your-openai-key"              # OpenAI GPT (also used by Whisper)

# AWS Bedrock (Kimi K2, Claude, Mistral, Nova, etc.)
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Optional: Builtin API keys
export BRAVE_API_KEY="your-brave-key"                # Web search
export ELEVENLABS_API_KEY="your-elevenlabs-key"      # Text-to-speech
```

**Per-workspace secrets:** You can also create a `.env` file in any workspace directory (`agent_workspaces/<name>/config/.env`) for workspace-specific environment variables. These are automatically loaded at workspace startup.

## Initial Configuration

### 1. Get a config.yaml

`openpaw init` (in the next section) scaffolds a minimal `config.yaml` for you, so you can skip ahead. To start from the fully-commented reference instead, copy it from the repo (source checkouts only — this file is not shipped in the PyPI wheel):

```bash
cp config.example.yaml config.yaml
```

### 2. Edit config.yaml

The default configuration works for most use cases. Key sections:

```yaml
# Path to agent workspaces
workspaces_path: agent_workspaces

# Queue behavior
queue:
  mode: collect       # collect, steer, followup, interrupt
  debounce_ms: 1000   # wait 1 second before processing collected messages

# Agent defaults
agent:
  model: anthropic:claude-sonnet-4-20250514  # or openai:gpt-4o, bedrock_converse:moonshot.kimi-k2-thinking
  max_turns: 50
  temperature: 0.7
```

**Note:** Channel configuration is no longer in global config. Each workspace configures its own channel in `agent.yaml`.

See [configuration.md](configuration.md) for detailed reference.

## Creating Your First Workspace

Each workspace represents an isolated agent with its own personality, tools, and conversation state. The fastest way to create one is with `openpaw init`:

### 1. Scaffold a Workspace

```bash
# Basic scaffold
poetry run openpaw init my_agent

# With model and channel pre-configured
poetry run openpaw init my_agent --model anthropic:claude-sonnet-4-20250514 --channel telegram
```

This creates `agent_workspaces/my_agent/` with all required files:

| File | Purpose |
|------|---------|
| `agent/AGENT.md` | Capabilities, behavior guidelines |
| `agent/USER.md` | User context and preferences |
| `agent/SOUL.md` | Core personality and values |
| `agent/HEARTBEAT.md` | Session state scratchpad |
| `agent/team/` | Spawn profiles for sub-agents (pre-populated with defaults) |
| `config/agent.yaml` | Model, channel, and queue config |
| `config/.env` | API key placeholders |

Each file includes TODO markers to guide customization.

### 2. Configure Your Workspace

Edit `config/agent.yaml` with your model and channel settings. If you passed `--model` and `--channel` to `init`, these sections are already populated (as shown below). If you did **not** pass them, `init` leaves the `model:` and `channel:` blocks commented out, and the workspace inherits the global default from `config.yaml`. Uncomment and edit them to override per workspace:

```yaml
name: my_agent
description: ""

model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.7

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: []

queue:
  mode: collect
  debounce_ms: 1000
```

Add your API keys to `config/.env`:

```bash
ANTHROPIC_API_KEY=your-key-here
TELEGRAM_BOT_TOKEN=your-bot-token
```

**Model precedence:** The effective model resolves in this order — the global `config.yaml` `agent.model` default → an optional per-workspace `config/agent.yaml` `model:` override → API keys referenced via `${VAR}` are read from the workspace `config/.env` (or your shell environment).

**Timezone:** Add a `timezone` field (IANA identifier, e.g., `America/New_York`) to control cron timing, heartbeat hours, and display timestamps. Defaults to UTC.

### 3. Customize Personality

Edit the markdown files to define your agent's identity:

- **AGENT.md** — What the agent can do and how it should behave
- **USER.md** — Context about the user(s) who will interact with it
- **SOUL.md** — Core personality, values, and communication style
- **HEARTBEAT.md** — Can start empty; the agent updates it to track session state

See [workspaces.md](workspaces.md) for detailed examples of each file.

!!! tip "List existing workspaces"
    Use `poetry run openpaw list` to see all valid workspaces in `agent_workspaces/`.

### 4. Optional: Custom Tools

Drop LangChain `@tool` functions into `agent/tools/` directory:

```bash
mkdir -p agent/tools
```

Example `agent/tools/weather.py`:

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city.

    Args:
        city: The city name

    Returns:
        Current weather description
    """
    # Your implementation here
    return f"Weather for {city}: Sunny, 72°F"
```

Add tool-specific dependencies to `agent/tools/requirements.txt`:

```
requests>=2.31.0
```

Dependencies are auto-installed at workspace startup.

### 5. Optional: Spawn Profiles

The `agent/team/` directory is pre-populated with default sub-agent profiles when you run `openpaw init`. These YAML files define specialized personas the main agent can spawn as background workers using the `spawn` builtin. Each profile specifies a system prompt, allowed tools, and optional model overrides.

You can edit existing profiles or create new ones. The `spawn` builtin lets the agent delegate independent tasks — such as research or file processing — to these profiles while remaining responsive to you.

See [Builtins](builtins.md) and [Workspaces](workspaces.md) for the full spawn profile format and sub-agent behavior.

### 6. Optional: Scheduled Tasks

Create cron jobs in `config/crons/` directory:

```bash
mkdir -p config/crons
```

Example `config/crons/daily-summary.yaml`:

```yaml
name: daily-summary
schedule: "0 9 * * *"  # Every day at 9:00 AM (workspace timezone)
enabled: true

prompt: |
  Review active tasks and workspace state.
  Provide a brief daily summary of pending work.

output:
  channel: telegram
  chat_id: 123456789  # Your Telegram user ID
```

See [scheduling.md](scheduling.md) for detailed configuration.

## Running Your Agent

### 1. Single Workspace (Telegram / Discord)

```bash
poetry run openpaw -c config.yaml -w my_agent
```

### 2. Multiple Workspaces

```bash
poetry run openpaw -c config.yaml -w agent1,agent2
```

### 3. All Workspaces

```bash
# Either syntax works
poetry run openpaw -c config.yaml --all
poetry run openpaw -c config.yaml -w "*"
```

### 4. Verbose Logging

```bash
poetry run openpaw -c config.yaml -w my_agent -v
```

### Local Testing with Stdio

> **Work in progress.** The `stdio` channel lets you chat from the terminal without a bot token (`--channel stdio`), which is convenient for a quick smoke test. It is **not** recommended for actually operating a bot — log output interleaves with the chat. Use Telegram or Discord for real use.

```bash
poetry run openpaw init test_agent --model anthropic:claude-sonnet-4-20250514 --channel stdio
poetry run openpaw -c config.yaml -w test_agent
```

Type messages directly in your terminal; the agent responds to stdout. Press `Ctrl+D` or send an empty line to stop.

## Testing Your Agent

1. **Find your bot in Telegram** - Search for the bot username you configured with BotFather
2. **Send a message** - "Hello! What can you do?"
3. **The agent should respond** based on its personality files (AGENT.md, USER.md, SOUL.md)

### Try Built-in Commands

Commands are intercepted by the framework before reaching the agent:

- `/help` - List available commands
- `/status` - Show model, conversation stats, active tasks, token usage
- `/new` - Archive current conversation and start fresh
- `/compact` - Summarize conversation, archive it, start new with summary
- `/queue collect` - Change queue mode (collect, steer, interrupt, followup)

### Upload a File

Send a PDF, DOCX, or image to test document conversion:

- **PDFs/DOCX/PPTX** are converted to markdown via Docling with OCR
- **Voice messages** are transcribed via Whisper (if `OPENAI_API_KEY` is set)
- Files are saved to `uploads/{YYYY-MM-DD}/` with sibling output files (e.g., `report.pdf` → `report.md`)

## Next Steps

Now that you have a working agent, explore advanced features:

- **[Configuration](configuration.md)** - Deep-dive into global and workspace config options
- **[Queue System](queue-system.md)** - Understand queue modes (collect, steer, interrupt, followup)
- **[Scheduling](scheduling.md)** - Set up scheduled tasks and heartbeats
- **[Builtins](builtins.md)** - Enable web search, voice, browser automation, sub-agents
- **[Workspaces](workspaces.md)** - Advanced workspace organization and custom tools
- **[Channels](channels.md)** - Channel system details and access control
- **[Architecture](architecture.md)** - System design and component interactions

## Troubleshooting

### Bot Doesn't Respond

**Check environment variables:**
```bash
# Verify variables are set
echo $TELEGRAM_BOT_TOKEN   # or DISCORD_BOT_TOKEN
echo $ANTHROPIC_API_KEY    # or OPENAI_API_KEY
```

**Check allowed_users list:**
If you configured `allowed_users` in `agent.yaml`, ensure your user ID is in the list. To find your user ID, temporarily set `allowed_users: []` and check the logs when you send a message.

**Check logs:**
```bash
poetry run openpaw -c config.yaml -w my-agent -v
```

Look for errors like `Unauthorized message from user 123456` or `Invalid API key`.

### "Module not found" Errors

Ensure you're using `poetry run` prefix:

```bash
# Wrong
openpaw -c config.yaml -w my-agent

# Correct
poetry run openpaw -c config.yaml -w my-agent
```

Verify installation:

```bash
poetry install
poetry show  # List installed packages
```

### "No API key" Errors

**For global environment variables:**
```bash
# Check if variables are exported in your current shell
env | grep API_KEY
```

**For workspace-specific variables:**
Ensure `.env` file exists in `agent_workspaces/<name>/config/.env` and contains the required keys.

**Test API key directly:**
```python
import anthropic
client = anthropic.Anthropic(api_key="your-key")
# Should not raise an error
```

### Playwright Browser Errors

If browser automation fails:

```bash
# Ensure Playwright is installed
poetry run playwright install chromium

# Check installed browsers
poetry run playwright install --help
```

### Docling OCR Issues

First ensure the document stack is installed: `poetry install -E documents` (or `pip install 'openpaw-ai[documents]'`). If scanned PDFs produce `<!-- image -->` instead of text:

- **macOS:** Docling uses native OCR (no additional setup needed)
- **Linux:** Docling falls back to EasyOCR (included in the `documents` extra)

Check logs for OCR-related errors when processing PDFs.

### Agent Responds Incorrectly

**Review workspace markdown files:**
- Check for typos or inconsistent instructions in `agent/AGENT.md`, `agent/USER.md`, `agent/SOUL.md`
- Ensure AGENT.md clearly defines capabilities and communication style

**Adjust temperature:**
```yaml
# In agent.yaml
model:
  temperature: 0.5  # Lower = more focused, higher = more creative
```

**Check conversation context:**
Use `/new` to start a fresh conversation if the agent seems confused by prior context.

### Performance Issues

**Reduce concurrency:**
```yaml
# In config.yaml
lanes:
  main_concurrency: 2      # Reduce from default 4
  subagent_concurrency: 4  # Reduce from default 8
```

**Enable heartbeat pre-flight skip:**
Heartbeats skip LLM calls when HEARTBEAT.md is empty and no active tasks exist (enabled by default).

**Monitor token usage:**
```
/status  # Shows token usage for today and current session
```

### Database Locked Errors

If you see `database is locked` errors, this indicates concurrent access to the SQLite conversation database. This should be rare but can happen with aggressive concurrency settings.

**Temporary fix:**
```bash
# Restart the workspace
pkill -f "openpaw.*my-agent"
poetry run openpaw -c config.yaml -w my-agent
```

### Still Having Issues?

- Check the [GitHub Issues](https://github.com/johnsosoka/OpenPaw/issues) for similar problems
- Review the full logs in `logs/<workspace>_YYYY-MM-DD.log`
- Ensure your Poetry environment is up to date: `poetry update`
