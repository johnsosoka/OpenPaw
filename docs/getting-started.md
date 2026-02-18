# Getting Started

This guide walks through installing OpenPaw, creating your first agent workspace, and running it with a Telegram channel.

## Prerequisites

- **Python 3.11+**
- **Poetry 2.0+** for dependency management ([installation guide](https://python-poetry.org/docs/#installation))
- **A Telegram bot token** ([create one via BotFather](https://core.telegram.org/bots#botfather))
- **At least one model provider credential:**
  - Anthropic API key ([get one here](https://console.anthropic.com/))
  - OpenAI API key ([get one here](https://platform.openai.com/api-keys))
  - AWS credentials for Bedrock ([configure AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html))

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/jsosoka/OpenPaw.git
cd OpenPaw
```

### 2. Install Dependencies

```bash
# Core installation (includes Docling + Playwright)
poetry install

# Install Playwright browser
poetry run playwright install chromium
```

### 3. Optional Extras

Install additional builtins based on your needs:

```bash
# Voice capabilities (Whisper transcription + ElevenLabs TTS)
poetry install -E voice

# Web search (Brave Search API)
poetry install -E web

# System tools (SSH remote execution)
poetry install -E system

# Memory search (semantic search over past conversations)
poetry install -E memory

# Install everything
poetry install -E all-builtins
```

**Extra descriptions:**

| Extra | Provides | Requires |
|-------|----------|----------|
| `voice` | Whisper audio transcription, ElevenLabs text-to-speech | `OPENAI_API_KEY`, `ELEVENLABS_API_KEY` |
| `web` | Brave Search web search | `BRAVE_API_KEY` |
| `system` | Shell command execution, SSH remote execution | `asyncssh` package |
| `memory` | Semantic search over conversation archives | `sqlite-vec` package |
| `all-builtins` | All of the above | All API keys above |

**Note:** Docling (document conversion) and Playwright (browser automation) are **core dependencies** and installed automatically with `poetry install`.

### 4. Set Up Environment Variables

Create a `.env` file or export variables:

```bash
# Required: Channel
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"

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

**Per-workspace secrets:** You can also create a `.env` file in any workspace directory (`agent_workspaces/<name>/.env`) for workspace-specific environment variables. These are automatically loaded at workspace startup.

## Initial Configuration

### 1. Copy the Example Configuration

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

Each workspace represents an isolated agent with its own personality, tools, and conversation state.

### 1. Create Workspace Directory

```bash
mkdir -p agent_workspaces/my-agent
cd agent_workspaces/my-agent
```

### 2. Create Required Markdown Files

Every workspace needs four markdown files:

**AGENT.md** - Capabilities and behavior guidelines

```markdown
# Agent Profile

You are a helpful AI assistant with the following capabilities:
- Answering questions and providing information
- Managing tasks via the TASKS.yaml system
- Processing uploaded documents (PDF, DOCX, PPTX)
- Browsing the web when needed
- Scheduling your own follow-up actions

## Communication Style

Be concise and friendly. Use clear, straightforward language.
When working on complex tasks, use send_message to keep the user informed of progress.
```

**USER.md** - User context and preferences

```markdown
# User Profile

## Name
John

## Preferences
- Prefers brief, actionable responses
- Works in Pacific Time (America/Los_Angeles)
- Values transparency and proactive updates

## Context
Primary use cases include research, document analysis, and task management.
```

**SOUL.md** - Core personality and values

```markdown
# Core Values

Be helpful, honest, and respectful.
Prioritize clarity over cleverness.
When uncertain, ask for clarification rather than making assumptions.

## Operating Principles

- Break complex tasks into manageable steps
- Maintain organized workspace files for continuity
- Use HEARTBEAT.md to track session state and ongoing work
```

**HEARTBEAT.md** - Current state and session notes

This file is the agent's scratchpad for maintaining context across sessions and heartbeats. It can start empty or with minimal content:

```markdown
# Current State

No active tasks.
```

**Note:** The agent can modify HEARTBEAT.md during conversations to track state. This file is also used by the heartbeat system (if enabled) to determine what to check during proactive check-ins.

### 3. Optional: Per-Workspace Configuration

Create `agent.yaml` to override global defaults:

```yaml
name: My Agent
description: A helpful personal assistant
timezone: America/Los_Angeles  # IANA timezone identifier (default: UTC)

model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.5
  max_turns: 50

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: [123456789]  # Your Telegram user ID (optional, empty = allow all)
  allowed_groups: []

queue:
  mode: collect
  debounce_ms: 1000

heartbeat:
  enabled: false  # Set to true for proactive check-ins
  interval_minutes: 30
  active_hours: "09:00-17:00"
  suppress_ok: true
```

**Timezone:** The `timezone` field uses IANA identifiers (e.g., `America/New_York`, `Europe/London`, `Asia/Tokyo`). This controls:
- Cron schedule timing
- Heartbeat active hours
- File upload date partitions
- Display timestamps in `/status` and conversation archives

### 4. Optional: Custom Tools

Drop LangChain `@tool` functions into `tools/` directory:

```bash
mkdir tools
```

Example `tools/weather.py`:

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

Add tool-specific dependencies to `tools/requirements.txt`:

```
requests>=2.31.0
```

Dependencies are auto-installed at workspace startup.

### 5. Optional: Scheduled Tasks

Create cron jobs in `crons/` directory:

```bash
mkdir crons
```

Example `crons/daily-summary.yaml`:

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

See [cron-scheduler.md](cron-scheduler.md) for detailed configuration.

## Running Your Agent

### 1. Single Workspace

```bash
poetry run openpaw -c config.yaml -w my-agent
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
poetry run openpaw -c config.yaml -w my-agent -v
```

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
- **[Cron Scheduler](cron-scheduler.md)** - Set up scheduled tasks and heartbeats
- **[Builtins](builtins.md)** - Enable web search, voice, browser automation, sub-agents
- **[Workspaces](workspaces.md)** - Advanced workspace organization and custom tools
- **[Channels](channels.md)** - Channel system details and access control
- **[Architecture](architecture.md)** - System design and component interactions

## Troubleshooting

### Bot Doesn't Respond

**Check environment variables:**
```bash
# Verify variables are set
echo $TELEGRAM_BOT_TOKEN
echo $ANTHROPIC_API_KEY  # or OPENAI_API_KEY
```

**Check allowed_users list:**
If you configured `allowed_users` in `agent.yaml`, ensure your Telegram user ID is in the list. To find your user ID, temporarily set `allowed_users: []` and check the logs when you send a message.

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
Ensure `.env` file exists in `agent_workspaces/<name>/.env` and contains the required keys.

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

If scanned PDFs produce `<!-- image -->` instead of text:

- **macOS:** Docling uses native OCR (no additional setup needed)
- **Linux:** Docling falls back to EasyOCR (auto-installed)

Check logs for OCR-related errors when processing PDFs.

### Agent Responds Incorrectly

**Review workspace markdown files:**
- Check for typos or inconsistent instructions in AGENT.md, USER.md, SOUL.md
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

- Check the [GitHub Issues](https://github.com/jsosoka/OpenPaw/issues) for similar problems
- Review the full logs in `logs/<workspace>_YYYY-MM-DD.log`
- Ensure your Poetry environment is up to date: `poetry update`
