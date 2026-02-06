# Builtins

Builtins are optional capabilities conditionally loaded based on API key availability. They come in two types: **tools** (agent-invokable functions) and **processors** (message transformers).

## Architecture

```
Builtins Registry
  ├─ Tools (LangChain-compatible)
  │   ├─ brave_search    (requires BRAVE_API_KEY)
  │   ├─ elevenlabs      (requires ELEVENLABS_API_KEY)
  │   ├─ shell           (no prerequisites, disabled by default)
  │   └─ ssh             (no prerequisites, requires config)
  └─ Processors (message transformers)
      ├─ whisper         (requires OPENAI_API_KEY)
      └─ timestamp       (no prerequisites)
```

Builtins are discovered at runtime. If prerequisites (API keys, dependencies) are missing, the builtin is unavailable.

## Available Builtins

### brave_search (Tool)

Web search capability using the Brave Search API.

**Prerequisites:**
- `BRAVE_API_KEY` environment variable
- `poetry install --extras web`

**Configuration:**

```yaml
builtins:
  brave_search:
    enabled: true
    config:
      count: 5  # Number of search results
```

**Usage:**

The agent can invoke web searches during conversations:

```
User: "What's the latest news about Python 3.13?"
Agent: [Uses brave_search tool to find recent articles]
Agent: "According to recent sources, Python 3.13 introduces..."
```

**Groups:** `web`

### whisper (Processor)

Audio transcription for voice and audio messages using OpenAI's Whisper API.

**Prerequisites:**
- `OPENAI_API_KEY` environment variable
- `poetry install --extras voice`

**Configuration:**

```yaml
builtins:
  whisper:
    enabled: true
    config:
      model: whisper-1
      language: en  # Optional: 'en', 'es', 'fr', etc. Omit for auto-detection
```

**Usage:**

Automatically transcribes voice/audio messages from Telegram:

```
User: [Sends voice message]
Channel: Downloads audio file
Whisper: Transcribes to text
Agent: Processes transcribed text as normal message
```

If transcription fails, the user receives an error message.

**Groups:** `voice`

### elevenlabs (Tool)

Text-to-speech for voice responses using ElevenLabs API.

**Prerequisites:**
- `ELEVENLABS_API_KEY` environment variable
- `poetry install --extras voice`

**Configuration:**

```yaml
builtins:
  elevenlabs:
    enabled: true
    config:
      voice_id: 21m00Tcm4TlvDq8ikWAM  # ElevenLabs voice ID
      model_id: eleven_monolingual_v1
```

**Usage:**

The agent can generate voice responses:

```
User: "Read me the summary"
Agent: [Uses elevenlabs tool to generate audio]
Agent: [Sends voice message via Telegram]
```

To find voice IDs:
- Visit [ElevenLabs Voice Library](https://elevenlabs.io/voice-library)
- Select a voice and copy the voice ID

**Groups:** `voice`

### shell (Tool)

Execute shell commands on the host system with configurable security controls.

**Prerequisites:**
- None (always available if enabled)
- `poetry install --extras system`

**Security:**
- Disabled by default - must explicitly enable
- Default blocked commands list prevents dangerous operations (rm -rf, sudo, etc.)
- Optional command allowlist for strict control
- Optional working directory constraint

**Configuration:**

```yaml
builtins:
  shell:
    enabled: true  # Must explicitly enable (disabled by default)
    config:
      allowed_commands:  # Optional allowlist - command must start with one of these
        - ls
        - cat
        - grep
        - echo
      blocked_commands:  # Optional override of defaults (defaults include rm -rf, sudo, etc.)
        - rm -rf
        - sudo
        - chmod 777
      working_directory: /home/user/sandbox  # Optional: constrain to directory
```

**Default blocked commands:**
- `rm -rf`, `rm -r`, `rm --recursive`
- `sudo`
- `chmod 777`, `chmod -R`
- `chown`, `chgrp`
- `> /dev/`, `dd if=`
- `mkfs`, `:(){:|:&};:`
- `wget`, `curl` (downloading arbitrary content)

**Usage:**

The agent can execute safe shell commands:

```
User: "What files are in the current directory?"
Agent: [Uses shell tool with command "ls -la"]
Agent: "Here are the files in the directory..."
```

Blocked commands return clear error messages:

```
Agent: [Attempts "sudo rm -rf /"]
Shell Tool: "Command blocked: contains blocked pattern 'sudo'"
```

**Groups:** `system`

### ssh (Tool)

Execute commands on remote hosts via SSH with mandatory host allowlisting.

**Prerequisites:**
- SSH keys available on the system
- `poetry install --extras system`

**Security:**
- Mandatory host allowlist - connections to non-allowlisted hosts are rejected
- Uses system SSH keys or specified key paths
- Configurable connection timeout

**Configuration:**

```yaml
builtins:
  ssh:
    enabled: true
    config:
      allowed_hosts:  # REQUIRED: Only these hosts can be accessed
        - server1.example.com
        - 192.168.1.100
        - dev-box
      default_user: deploy  # Optional: default SSH username
      default_key_path: ~/.ssh/id_rsa  # Optional: default SSH key (supports ~ expansion)
      timeout: 30  # Optional: connection timeout in seconds (default: 30)
```

**Usage:**

The agent can execute commands on remote hosts:

```
User: "Check disk space on the dev server"
Agent: [Uses ssh tool: host="dev-box", command="df -h"]
Agent: "The dev server has 45% disk usage..."
```

Tool input parameters:
- `host` (required) - Target hostname (must be in allowed_hosts)
- `command` (required) - Command to execute
- `user` (optional) - Override default username
- `key_path` (optional) - Override default key path

Output format:
```
[SSH] hostname: command
[Exit Code] 0
[STDOUT]
command output

[STDERR]
error output if any
```

Blocked hosts return clear error messages:

```
Agent: [Attempts to SSH to "unknown-host"]
SSH Tool: "Host 'unknown-host' not in allowed_hosts list"
```

**Groups:** `system`

### timestamp (Processor)

Prepends current date/time context to inbound messages, helping agents understand the current time in the user's timezone.

**Prerequisites:**
- None (always available)
- No extra installation needed

**Configuration:**

```yaml
builtins:
  timestamp:
    enabled: true
    config:
      timezone: America/Los_Angeles  # Timezone string (default: UTC)
      format: "%Y-%m-%d %H:%M %Z"  # Optional datetime format (strftime format)
      template: "[Current time: {datetime}]"  # Optional prefix template
```

**Usage:**

Automatically adds timestamp context to every message:

```
User: "What's the weather today?"
[Timestamp processor adds: "[Current time: 2026-02-06 14:30 PST]"]
Agent sees: "[Current time: 2026-02-06 14:30 PST]\n\nWhat's the weather today?"
Agent: "For today, February 6th at 2:30 PM Pacific time..."
```

**Format Examples:**

```yaml
# ISO 8601 format
format: "%Y-%m-%d %H:%M:%S %Z"
# Output: [Current time: 2026-02-06 14:30:00 PST]

# Human-readable format
format: "%A, %B %d, %Y at %I:%M %p %Z"
# Output: [Current time: Thursday, February 06, 2026 at 02:30 PM PST]

# Date only
format: "%Y-%m-%d"
# Output: [Current time: 2026-02-06]
```

**Supported timezones:**
- IANA timezone database names: `America/Los_Angeles`, `Europe/London`, `Asia/Tokyo`
- `UTC` for UTC time
- Uses Python `zoneinfo` module

**Groups:** `context`

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

  shell:
    enabled: true
    config:
      allowed_commands: ["ls", "cat", "grep"]

  ssh:
    enabled: true
    config:
      allowed_hosts:
        - server1.example.com
        - 192.168.1.100

  timestamp:
    enabled: true
    config:
      timezone: America/Los_Angeles
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
    - whisper

# workspace2/agent.yaml - Enable voice features
builtins:
  allow:
    - group:voice  # Allow all voice builtins
  deny:
    - brave_search
```

### Allow/Deny Behavior

**Empty allow list** - Allow all available builtins (default)

```yaml
builtins:
  allow: []  # Allow everything
```

**Specific allow list** - Only enable listed builtins

```yaml
builtins:
  allow:
    - brave_search
    - whisper
  # elevenlabs is denied (not in allow list)
```

**Group allow** - Enable all builtins in a group

```yaml
builtins:
  allow:
    - group:voice  # Allows whisper, elevenlabs
```

**Deny list** - Block specific builtins or groups

```yaml
builtins:
  allow: []  # Allow all
  deny:
    - elevenlabs  # Except this one
```

**Group deny** - Block all builtins in a group

```yaml
builtins:
  deny:
    - group:voice  # Blocks whisper, elevenlabs
```

**Priority:** Deny takes precedence over allow.

## Builtin Groups

Builtins can be organized into groups for easier configuration.

**Current groups:**
- `voice` - Voice-related capabilities (whisper, elevenlabs)
- `web` - Web-related capabilities (brave_search)
- `system` - System operations (shell, ssh)
- `context` - Message context enrichment (timestamp)

**Usage:**

```yaml
builtins:
  allow:
    - group:web  # Allow all web builtins
  deny:
    - group:voice  # Deny all voice builtins
```

## Installation

Builtins require optional dependencies. Install only what you need:

**Voice capabilities:**
```bash
poetry install --extras voice
```

Installs: `openai`, `elevenlabs`

**Web capabilities:**
```bash
poetry install --extras web
```

Installs: `langchain-community`

**System capabilities:**
```bash
poetry install --extras system
```

Installs: `langchain-experimental`, `asyncssh`

**All builtins:**
```bash
poetry install --extras all-builtins
```

Installs all optional dependencies.

## Adding Custom Builtins

You can extend OpenPaw with custom tools and processors.

### Creating a Custom Tool

1. **Create tool file:** `openpaw/builtins/tools/my_tool.py`

```python
from langchain.tools import BaseTool
from openpaw.builtins.base import BaseBuiltinTool, BuiltinMetadata

class MyCustomTool(BaseBuiltinTool, BaseTool):
    """Custom tool description"""
    name = "my_custom_tool"
    description = "What this tool does"

    metadata = BuiltinMetadata(
        name="my_custom_tool",
        type="tool",
        description="Custom functionality",
        prerequisites={
            "env_vars": ["MY_API_KEY"],
            "packages": ["my-package"]
        },
        groups=["custom"]
    )

    def _run(self, query: str) -> str:
        """Execute the tool"""
        api_key = os.getenv("MY_API_KEY")
        # Implementation here
        return result

    def _arun(self, query: str) -> str:
        """Async version (optional)"""
        raise NotImplementedError("Async not supported")
```

2. **Register in registry:** `openpaw/builtins/registry.py`

```python
from openpaw.builtins.tools.my_tool import MyCustomTool

def _discover_builtins():
    registry = BuiltinRegistry()

    # Existing registrations...

    # Register custom tool
    try:
        registry.register(MyCustomTool())
    except ImportError:
        pass  # Dependencies not installed

    return registry
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
from openpaw.builtins.base import BaseBuiltinProcessor, BuiltinMetadata
from openpaw.channels.base import Message

class MyCustomProcessor(BaseBuiltinProcessor):
    """Custom message processor"""

    metadata = BuiltinMetadata(
        name="my_processor",
        type="processor",
        description="Processes messages before agent sees them",
        prerequisites={
            "env_vars": ["MY_API_KEY"],
            "packages": ["my-package"]
        },
        groups=["custom"]
    )

    async def process(self, message: Message, config: dict) -> Message:
        """Transform the message"""
        # Access config
        option = config.get("option1", "default")

        # Transform message content
        message.content = f"[Processed] {message.content}"

        return message
```

2. **Register in registry:** `openpaw/builtins/registry.py`

```python
from openpaw.builtins.processors.my_processor import MyCustomProcessor

def _discover_builtins():
    registry = BuiltinRegistry()

    # Existing registrations...

    # Register custom processor
    try:
        registry.register(MyCustomProcessor())
    except ImportError:
        pass

    return registry
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

## Builtin Lifecycle

### Discovery

On startup, OpenPaw:
1. Imports all builtin modules
2. Checks prerequisites (env vars, packages)
3. Registers available builtins in the registry
4. Logs which builtins are available

### Loading

Per workspace:
1. Check global `builtins.allow` and `builtins.deny` lists
2. Check workspace-specific allow/deny overrides
3. Load only allowed, available builtins
4. Pass configuration to each builtin

### Execution

**Tools:**
- Agent decides when to invoke (via LangChain tool calling)
- Tool executes with provided arguments
- Returns result to agent

**Processors:**
- Run on every message from channel
- Transform message before agent sees it
- Transparent to agent

## Best Practices

### 1. Use Environment Variables for Secrets

Never hardcode API keys:

```yaml
# Bad
builtins:
  brave_search:
    config:
      api_key: "actual-key-here"  # Don't do this

# Good
builtins:
  brave_search:
    enabled: true
```

```bash
export BRAVE_API_KEY="actual-key-here"
```

### 2. Install Only Needed Extras

Minimize dependencies:

```bash
# Only need voice features
poetry install --extras voice

# Don't install all if you only need some
# poetry install --extras all-builtins  # Unnecessary if you only need voice
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
# Instead of:
builtins:
  deny:
    - whisper
    - elevenlabs

# Use:
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

### 6. Document Custom Builtins

For custom builtins, document:
- Prerequisites (API keys, packages)
- Configuration options
- Example usage
- Error handling

## Troubleshooting

**Builtin not available:**
- Check environment variable is set: `echo $OPENAI_API_KEY`
- Verify extras are installed: `poetry install --extras voice`
- Check allow/deny lists in config
- Enable verbose logging: `poetry run openpaw -w agent -v`

**API key errors:**
- Verify key is valid and active
- Check API quota/billing status
- Test key with curl (see examples above)

**Import errors:**
- Missing optional dependency
- Run `poetry install --extras <extra-name>`
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

## Security Considerations

### System Tools (shell, ssh)

The `shell` and `ssh` tools provide powerful system access and require careful configuration:

**Shell Tool:**
- Disabled by default - must explicitly enable in config
- Use `allowed_commands` for strict allowlisting when possible
- Default `blocked_commands` list prevents common dangerous operations
- Consider constraining `working_directory` to a sandbox
- Never enable in untrusted environments

**SSH Tool:**
- Requires mandatory `allowed_hosts` configuration
- Rejects connections to non-allowlisted hosts
- Uses system SSH keys - ensure keys have appropriate permissions
- Consider separate keys for agent SSH access
- Audit `allowed_hosts` list regularly

**Best Practices:**
1. Enable system tools only in workspaces that need them
2. Use `group:system` deny rule in untrusted workspaces
3. Configure minimal permissions (minimal allowed_commands, minimal allowed_hosts)
4. Monitor logs for blocked command attempts
5. Keep SSH keys secured with appropriate file permissions (600)

### Context Processors (timestamp)

Context processors modify messages transparently:

**Timestamp Processor:**
- No security concerns - read-only time information
- Verify timezone configuration matches user's actual location
- Consider disabling if timestamp context causes issues with agent behavior

## Future Builtins

Planned additions:
- **google_search** - Alternative web search
- **screenshot** - Capture and analyze screenshots
- **file_upload** - Handle document uploads
- **calendar** - Calendar integration for scheduling
- **email** - Email sending capability

Each will follow the same prerequisite/configuration pattern.
