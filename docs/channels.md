# Channels

<div align="center">
  <img src="../assets/images/openpaw-dog-bernese.png" alt="OpenPaw Channels" width="500">
</div>

Channels connect agents to communication platforms. OpenPaw supports Telegram and Discord, with an extensible architecture for additional platforms. A single workspace can connect to multiple channels simultaneously.

## Channel Architecture

```
Platform (Telegram / Discord) → Channel Adapter → Unified Message Format → Queue → Agent
```

Channel adapters translate platform-specific messages into OpenPaw's unified `Message` format, enabling consistent agent behavior across platforms.

### Channel Factory Pattern

Channels are created via the factory pattern in `openpaw/channels/factory.py`:

```python
def create_channel(
    channel_type: str,
    config: dict,
    workspace_name: str,
    channel_name: str | None = None,
) -> ChannelAdapter:
    """Create a channel instance based on type."""
```

This decouples `WorkspaceRunner` from concrete channel types, enabling extensibility without framework modifications.

## Unified Message Format

All channels convert platform-specific messages to OpenPaw's unified format defined in `openpaw/model/message.py`:

```python
@dataclass
class Message:
    """Unified message format across all channels."""

    id: str                                    # Unique message ID
    channel: str                               # Channel name ("telegram", "discord")
    session_key: str                           # Format: "channel:id" (e.g., "telegram:123456")
    user_id: str                               # User identifier
    content: str                               # Message text
    direction: MessageDirection                # INBOUND or OUTBOUND
    timestamp: datetime                        # Message timestamp
    reply_to_id: str | None                    # ID of message being replied to
    metadata: dict[str, Any]                   # Platform-specific data
    attachments: list[Attachment]              # Files, images, audio, etc.
```

### Message Attachments

```python
@dataclass
class Attachment:
    """Represents a message attachment."""

    type: str                                  # "audio", "image", "document", "video"
    data: bytes | None                         # Raw binary data (if downloaded)
    url: str | None                            # Remote URL (if not downloaded)
    filename: str | None                       # Original filename
    mime_type: str | None                      # MIME type
    metadata: dict[str, Any]                   # Type-specific metadata
    saved_path: str | None                     # Workspace-relative path (set by FilePersistenceProcessor)
```

## Telegram Channel

The Telegram channel uses [python-telegram-bot](https://python-telegram-bot.org/) to interface with Telegram's Bot API.

### Setup

1. **Create a Telegram bot:**

   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Send `/newbot` and follow prompts
   - Save the bot token (format: `123456:ABC-DEF...`)

2. **Configure OpenPaw:**

   Per-workspace (`agent.yaml`):
   ```yaml
   channel:
     type: telegram
     token: ${TELEGRAM_BOT_TOKEN}
     allowed_users: [123456789]
     allowed_groups: []
   ```

3. **Set environment variable:**

   Add to `config/.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   ```

4. **Run the workspace:**

   ```bash
   poetry run openpaw -c config.yaml -w my-agent
   ```

5. **Test the bot:**

   - Search for your bot in Telegram
   - Send `/start` to initiate conversation
   - Agent should respond with welcome message

### Access Control

Restrict who can interact with the bot using allowlists.

#### User Allowlist

```yaml
channel:
  type: telegram
  allowed_users: [123456789, 987654321]
```

To get your Telegram user ID:
- Message [@userinfobot](https://t.me/userinfobot)
- It will reply with your user ID

Only listed users can DM the bot. Messages from other users are silently ignored.

#### Group Allowlist

```yaml
channel:
  type: telegram
  allowed_groups: [-1001234567890]
```

To get a group ID:
1. Add [@RawDataBot](https://t.me/RawDataBot) to your group
2. It will post the group's chat ID (negative number for groups)
3. Remove the bot after getting the ID

When a group is in `allowed_groups`, **any user** in that group can interact with the bot — they do not need to be individually listed in `allowed_users`. The `allowed_users` list controls who can DM the bot directly.

### Supported Message Types

#### Text Messages

Standard text messages are processed directly.

#### Voice Messages

Voice messages are automatically transcribed if the `whisper` builtin is enabled.

**Configuration:**

```yaml
builtins:
  whisper:
    enabled: true
    config:
      model: whisper-1
```

**Requirements:**
- `OPENAI_API_KEY` environment variable
- `whisper` builtin enabled (enabled by default)

**Processing Flow:**
1. User sends voice message
2. `FilePersistenceProcessor` saves audio to `data/uploads/{YYYY-MM-DD}/voice_123.ogg`
3. `WhisperProcessor` transcribes audio to text
4. Transcript saved as sibling file `data/uploads/{YYYY-MM-DD}/voice_123.txt`
5. Message content enriched with file receipt notification and transcript
6. Agent processes enriched message

#### Documents

Document files (PDF, DOCX, PPTX, etc.) are automatically processed if the `docling` builtin is enabled.

**Processing Flow:**
1. User uploads document
2. `FilePersistenceProcessor` saves to `data/uploads/{YYYY-MM-DD}/report.pdf`
3. `DoclingProcessor` converts document to markdown
4. Markdown saved as sibling file `data/uploads/{YYYY-MM-DD}/report.md`
5. Agent can read the converted markdown or original file

Supported formats: PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, and more.

#### Photos

Photos are automatically saved to the workspace uploads directory by `FilePersistenceProcessor`.

### Telegram Metadata Fields

When messages are converted to the unified format, platform-specific data is stored in the `metadata` field:

```python
{
    "chat_id": 123456789,        # Telegram chat ID
    "message_id": 12345,         # Message ID
    "username": "johndoe",       # Telegram username (if available)
    "first_name": "John",        # User's first name
    "last_name": "Doe",          # User's last name (if available)
    "is_group": False,           # True if from a group chat
}
```

### Session Keys

Telegram session keys follow the format `"telegram:{user_id}"` for direct messages and `"telegram:{group_id}"` for group chats.

Examples:
- Direct message: `"telegram:123456789"`
- Group chat: `"telegram:-1001234567890"`

### Error Handling

**Bot token invalid:**
```
Error: telegram.error.InvalidToken
```
Solution: Verify `TELEGRAM_BOT_TOKEN` is correct and active.

**Message too long:**
Telegram messages have a 4096 character limit. OpenPaw automatically splits long responses into multiple messages.

**File size limits:**
Telegram has a 50 MB file size limit for bots. The `FilePersistenceProcessor` enforces this limit.

---

## Discord Channel

The Discord channel uses [discord.py](https://discordpy.readthedocs.io/) to interface with Discord's Bot API. It supports text messages, file attachments, slash commands, and approval gate buttons.

### Setup

1. **Create a Discord application:**

   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application" and give it a name
   - Navigate to **Bot** in the sidebar
   - Click "Reset Token" and save the bot token

2. **Enable required intents:**

   In the Developer Portal under **Bot > Privileged Gateway Intents**:
   - Enable **Message Content Intent** (required for reading message text)
   - Enable **Server Members Intent** (optional, for user resolution)

3. **Generate an invite URL:**

   Under **OAuth2 > URL Generator**:
   - Select scopes: `bot`, `applications.commands`
   - Select permissions: `Send Messages`, `Read Message History`, `Attach Files`, `Use Slash Commands`
   - Copy the generated URL and open it to invite the bot to your server

4. **Configure OpenPaw:**

   Per-workspace (`agent.yaml`):
   ```yaml
   channel:
     type: discord
     token: ${DISCORD_BOT_TOKEN}
     allowed_users: [916552354470461470]  # Discord user ID (snowflake)
     allowed_groups: []                    # Guild (server) IDs
     mention_required: true                # Only respond when @mentioned in servers
   ```

5. **Set environment variable:**

   Add to `config/.env`:
   ```bash
   DISCORD_BOT_TOKEN=your-bot-token-here
   ```

6. **Run the workspace:**

   ```bash
   poetry run openpaw -c config.yaml -w my-agent
   ```

7. **Test the bot:**

   - In a server where the bot was invited, @mention the bot with a message
   - In DMs, message the bot directly (no mention needed)

### Access Control

Discord uses the same allowlist model as Telegram.

#### User Allowlist

```yaml
channel:
  type: discord
  allowed_users: [916552354470461470]
```

To get your Discord user ID:
1. Enable Developer Mode in Discord (Settings > App Settings > Advanced > Developer Mode)
2. Right-click your username and select "Copy User ID"

#### Guild (Server) Allowlist

```yaml
channel:
  type: discord
  allowed_groups: [123456789012345678]  # Guild IDs
```

When a guild is in `allowed_groups`, **any user** in that guild can interact with the bot — they do not need to be individually listed in `allowed_users`. The `allowed_users` list controls who can DM the bot directly. Messages from guilds not in the allowlist are rejected unless the sender is individually allowlisted.

### Activation Filters

Discord supports `mention_required` and `triggers` for controlling when the bot responds in server channels. See [Trigger-Based Activation](#trigger-based-activation) below.

### Discord Metadata Fields

```python
{
    "guild_id": 123456789012345678,  # Server ID (None for DMs)
    "username": "johndoe",           # Discord username
    "display_name": "John",          # Server nickname or display name
}
```

### Session Keys

Discord session keys follow the format `"discord:{channel_id}"`:

- Server channel: `"discord:1234567890123456"`
- DM channel: `"discord:9876543210987654"`

### Error Handling

**Bot token invalid:**
```
RuntimeError: Discord bot failed to connect in time
```
Solution: Verify the bot token in Developer Portal. Regenerate if needed.

**Missing intents:**
```
discord.errors.PrivilegedIntentsRequired
```
Solution: Enable "Message Content Intent" in Developer Portal under Bot settings.

**Message too long:**
Discord messages have a 2000 character limit. OpenPaw automatically splits long responses, breaking at paragraph boundaries.

**File size limits:**
Discord free-tier bots have a 25 MB file size limit. Files exceeding this limit are rejected with a clear error.

---

## Multi-Channel Configuration

A single workspace can connect to multiple channels simultaneously, receiving messages from Telegram and Discord (or multiple bots of the same type) through a single agent.

### Basic Multi-Channel

Use `channels:` (plural) instead of `channel:` (singular) in `agent.yaml`:

```yaml
channels:
  - type: telegram
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users: [123456789]

  - type: discord
    token: ${DISCORD_BOT_TOKEN}
    allowed_users: [916552354470461470]
    mention_required: true
```

The agent receives messages from both platforms through the same queue and responds on whichever channel the message came from.

### Named Channels

When running two channels of the same type (e.g., two Telegram bots), use the `name` field to distinguish them:

```yaml
channels:
  - name: telegram-personal
    type: telegram
    token: ${TELEGRAM_BOT_TOKEN_1}
    allowed_users: [123456789]

  - name: telegram-work
    type: telegram
    token: ${TELEGRAM_BOT_TOKEN_2}
    allowed_users: [987654321]
```

Without explicit names, channels default to using their type as the name. Duplicate names cause a startup error.

### Backward Compatibility

The singular `channel:` syntax continues to work and is automatically normalized to a single-element `channels:` list. Existing configurations require no changes.

```yaml
# These are equivalent:
channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}

channels:
  - type: telegram
    token: ${TELEGRAM_BOT_TOKEN}
```

You cannot use both `channel:` and `channels:` in the same config — this produces a validation error.

### User Aliases

When a workspace has multiple channels, `user_aliases` from all channels are aggregated. If the same user ID appears in multiple channels, the first occurrence wins.

```yaml
channels:
  - type: telegram
    token: ${TELEGRAM_BOT_TOKEN}
    allowed_users: [123456789]
    user_aliases:
      123456789: "John"

  - type: discord
    token: ${DISCORD_BOT_TOKEN}
    allowed_users: [916552354470461470]
    user_aliases:
      916552354470461470: "John"
```

### Cron and Heartbeat Routing

When scheduling cron jobs or heartbeats with multi-channel workspaces, use `target_id` for channel-agnostic routing:

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30
  target_channel: telegram        # Which channel to deliver to
  target_id: 123456789            # Channel-agnostic user/chat ID
```

```yaml
# crons/daily-summary.yaml
output:
  channel: discord                # Channel type
  target_id: 1234567890123456     # Discord channel ID
```

The `target_id` field is preferred over legacy `chat_id` (Telegram-specific) and `channel_id` (Discord-specific), though both legacy fields still work.

---

## Trigger-Based Activation

Activation filters control when an agent responds in group channels (Discord servers, Telegram groups). They have no effect on direct messages — DMs always pass through.

### Configuration

```yaml
channel:
  type: discord
  token: ${DISCORD_BOT_TOKEN}
  allowed_users: [916552354470461470]
  mention_required: true          # Respond when @mentioned
  triggers:                       # Respond to keyword triggers
    - "!ask"
    - "hey bot"
```

### Behavior

Activation uses **OR logic** — either condition is sufficient:

| `mention_required` | `triggers` | Behavior |
|---------------------|------------|----------|
| `false` | `[]` | All messages pass (no filtering) |
| `true` | `[]` | Only @mentions pass |
| `false` | `["!ask"]` | Only trigger keywords pass |
| `true` | `["!ask"]` | @mentions OR trigger keywords pass |

**Trigger matching** is case-insensitive substring matching. A trigger of `"hey bot"` matches "Hey Bot, what time is it?" and "HEY BOT" equally.

**Commands and DMs** always bypass activation filters:
- `/help`, `/status`, and other slash commands always work
- Direct messages are never filtered

### Examples

**Discord bot that only responds when mentioned:**
```yaml
channel:
  type: discord
  mention_required: true
```

**Telegram bot that responds to keyword triggers in groups:**
```yaml
channel:
  type: telegram
  triggers: ["!ask", "hey assistant"]
```

**Both mention and triggers (OR logic):**
```yaml
channel:
  type: discord
  mention_required: true
  triggers: ["!help", "!ask"]
```

In this configuration, the bot responds in server channels when either @mentioned OR when a message contains "!help" or "!ask".

---

## File Persistence

All uploaded files are automatically saved to `{workspace}/data/uploads/{YYYY-MM-DD}/` with date partitioning by the `FilePersistenceProcessor` (enabled by default). This works identically across Telegram and Discord.

**Configuration:**

```yaml
builtins:
  file_persistence:
    enabled: true
    config:
      max_file_size: 52428800  # 50 MB default
      clear_data_after_save: false
```

**Filename Handling:**
- Filenames are sanitized (lowercased, special chars removed, spaces replaced with underscores)
- Duplicates get counters appended: `report.pdf`, `report_1.pdf`, `report_2.pdf`

**Content Enrichment:**

Uploaded files are enriched with metadata notifications:
```
[File received: report.pdf (2.3 MB, application/pdf)]
[Saved to: data/uploads/2026-02-17/report.pdf]
```

Processors (Whisper, Docling) create sibling output files alongside the original:
- `voice_123.ogg` → `voice_123.txt` (transcript)
- `report.pdf` → `report.md` (converted markdown)

---

## Framework Commands

Framework commands are handled by `CommandRouter` before messages reach the agent. These commands bypass the inbound processor pipeline to avoid content modification breaking detection.

**Built-in Commands:**
- `/start` - Welcome message (hidden from `/help`, for onboarding)
- `/new` - Archive current conversation and start fresh
- `/compact` - Summarize current conversation, archive it, start new with summary injected
- `/help` - List available commands with descriptions
- `/queue <mode>` - Change queue mode (`collect`, `steer`, `followup`, `interrupt`)
- `/status` - Show workspace info: model, conversation stats, active tasks, token usage
- `/model <provider:model>` - Switch LLM model at runtime

**Command Registration:**

Channels automatically register bot commands using `channel.register_commands()` which pulls from the `CommandRouter`'s definition list. For Telegram, this creates the command menu visible in the chat interface. For Discord, commands are registered as slash commands via the command tree.

**Note:** These are framework commands intercepted before reaching the agent, NOT regular text processed by the agent's personality files.

### Approval Gate UI

Both Telegram and Discord support approval gates with native UI:
- **Telegram:** Inline keyboard buttons (Approve / Deny)
- **Discord:** Interactive buttons with visual feedback

See [Concepts](concepts.md) for how approval gates work and [Configuration](configuration.md) for the full config reference.

---

## Channel History

OpenPaw can give agents awareness of the conversation that preceded their activation in group channels. Two complementary features work together: on-demand context fetch (the last N messages injected when the bot is triggered) and persistent channel logging (a continuous JSONL record of all visible messages).

Both features are per-channel and designed with privacy in mind. DMs are excluded from both. Persistent logging is enabled by default for group channels.

---

### On-Demand Context Fetch

When an agent is @mentioned or triggered by a keyword in a server channel, it normally only sees the triggering message. On-demand context fetch grabs the last N messages from that channel and prepends them to the message the agent receives — giving it the conversational context to respond intelligently.

**How it works:**

The channel adapter fetches recent messages from the platform API when activated. The history is formatted as an XML block and prepended to the message content before it reaches the agent:

```
<channel_context source="discord" channel="#general" messages="25">
[5m ago] Alice: Has anyone looked at the PR?
[3m ago] Bob: Yeah I left some comments
[2m ago] [BOT]: I can review it if you'd like
[1m ago] Alice: @bot please review PR #42
</channel_context>

@bot please review PR #42
```

The agent can clearly distinguish the channel context from the actual user request. Relative timestamps are used to keep the output compact and timezone-neutral. The bot's own previous messages are marked with `[BOT]` so the agent has self-awareness of its prior contributions.

**Configuration:**

```yaml
channel:
  type: discord
  token: ${DISCORD_BOT_TOKEN}
  allowed_groups: [111222333]
  mention_required: true
  context_messages: 25    # Messages to fetch on trigger (default: 25, 0 to disable)
```

`context_messages` accepts values from `0` (disabled) to `100`. Set to `0` to turn off context fetch for a channel.

**Notes:**

- Context fetch only runs for group/server messages, not DMs.
- The fetch is best-effort: if the platform API call fails or times out, the agent proceeds without context rather than blocking the message.
- Currently implemented for Discord. Telegram's Bot API does not expose a channel history endpoint, so context fetch returns empty for Telegram channels.
- Fetching history requires the `Read Message History` permission in Discord.

---

### Persistent Channel Logging

Persistent channel logging captures all visible messages to daily JSONL files, giving the agent a long-term, searchable record of channel activity. The agent can use its existing filesystem tools (`read_file`, `grep_files`) to search history without any new tooling.

**Enabling logging:**

```yaml
channel:
  type: discord
  token: ${DISCORD_BOT_TOKEN}
  allowed_groups: [111222333]
  channel_log:
    enabled: true          # Enabled by default
    retention_days: 30     # Days before old logs are archived (default: 30)
```

**Directory structure:**

Logs are organized by server and channel under `memory/logs/channel/`:

```
{workspace}/
└── memory/
    └── logs/
        └── channel/
            └── {server-name}/
                └── {channel-name}/
                    ├── 2026-03-05.jsonl
                    ├── 2026-03-06.jsonl
                    └── 2026-03-07.jsonl
```

Server and channel names are sanitized for filesystem compatibility.

**Log record format:**

Each line in a daily log file is a JSON object:

```json
{
  "ts": "2026-03-07T14:30:00+00:00",
  "msg_id": "1234567890",
  "user_id": "987654321",
  "display_name": "Alice",
  "content": "Has anyone tried the new deployment?",
  "attachments": ["screenshot.png"],
  "server_id": "111222333",
  "channel_id": "444555666"
}
```

Timestamps are stored in UTC, consistent with OpenPaw's "store in UTC, display in workspace timezone" convention.

**Reading logs from the agent:**

When channel logging is enabled, the agent is informed about the log location in its system prompt. It can read and search logs using filesystem tools:

```
# Read a specific day's log
read_file("memory/logs/channel/my-server/general/2026-03-07.jsonl")

# Search across all channel logs for a keyword
grep_files("deploy", glob="memory/logs/channel/**/*.jsonl")

# Search a specific channel for a user's messages
grep_files("Alice", glob="memory/logs/channel/my-server/general/*.jsonl")
```

**Retention and archival:**

Log files older than `retention_days` are moved to `memory/logs/channel/_archive/` rather than deleted. This preserves history for forensic or reference purposes while keeping the active log directory tidy. Archival runs automatically on workspace startup.

**Privacy notes:**

- Logging is **enabled by default** — set `channel_log.enabled: false` to disable.
- **DMs are never logged**, regardless of configuration.
- Only messages visible to the bot are captured (i.e., in channels the bot has access to).
- The framework writes log files; agents can read them but cannot write or modify them.
- Server operators deploying OpenPaw with logging enabled should inform their users.

**Extensibility:**

Channel logging uses an observer callback pattern on the channel adapter. Any channel adapter that implements the `on_channel_event` callback will automatically have its messages logged when the feature is enabled. Adding logging support to a new channel adapter requires a single callback invocation.

---

OpenPaw's channel system is extensible. To add a new platform:

### 1. Create Channel Adapter

Create `openpaw/channels/<platform>.py` extending `ChannelAdapter`:

```python
from openpaw.channels.base import ChannelAdapter
from openpaw.model.message import Message, Attachment, MessageDirection

class SlackChannel(ChannelAdapter):
    """Slack channel adapter."""

    name = "slack"

    def __init__(self, token: str, workspace_name: str = "unknown", **kwargs):
        self._token = token
        self.workspace_name = workspace_name
        # ... platform SDK setup

    async def start(self): ...
    async def stop(self): ...
    async def send_message(self, session_key, content, **kwargs) -> Message: ...
    async def send_file(self, session_key, file_data, filename, **kwargs): ...
    async def send_approval_request(self, session_key, approval_id, tool_name, tool_args, **kwargs): ...
```

### 2. Register in Channel Factory

Update `openpaw/channels/factory.py` to handle the new type string.

### 3. Test the Channel

Create a workspace using the new channel:

```yaml
channel:
  type: slack
  token: ${SLACK_BOT_TOKEN}
  allowed_users: [U12345678]
```

### Channel Adapter Requirements

New channel implementations must:

1. **Extend `ChannelAdapter`** - Base class in `openpaw/channels/base.py`
2. **Implement core methods:**
   - `async def start()` - Initialize platform connection
   - `async def stop()` - Shutdown platform connection
   - `async def send_message(session_key, content)` - Send text message
   - `async def send_file(session_key, file_data, filename, caption)` - Send file to user
   - `async def send_approval_request(session_key, approval_id, tool_name, tool_args)` - Approval UI
3. **Handle platform-specific errors gracefully** - Don't crash on malformed messages
4. **Support access control** - Implement allowlisting for users/channels/servers
5. **Register commands** - Call `register_commands()` with command definitions
6. **Convert attachments** - Map platform attachments to `Attachment` objects with proper metadata
7. **Session key format** - Use `"{channel_name}:{id}"` format (e.g., `"slack:C12345"`)

## Best Practices

1. **Use environment variables** - Never commit bot tokens to version control
2. **Restrict access** - Use allowlists (`allowed_users`, `allowed_groups`) for production bots
3. **Test in private chats** - Verify bot behavior before adding to groups
4. **Use activation filters** - Set `mention_required: true` in busy group channels
5. **Handle errors gracefully** - Log errors but don't crash on malformed messages
6. **Enable verbose logging** - Use `-v` flag during setup to debug channel issues
7. **Rate limit awareness** - Don't spam platforms with rapid messages; respect rate limits
8. **Platform-specific features** - Leverage inline keyboards, buttons, reactions when available
9. **File size limits** - Telegram allows 50 MB, Discord free-tier allows 25 MB
10. **Session key consistency** - Always use `"{channel_name}:{id}"` format for session keys

## Future Channels

Planned channel support:

- **Slack** - Workspace integration with slash commands
- **WhatsApp** - Direct messaging via WhatsApp Business API
- **CLI** - Terminal-based interface for local testing
- **HTTP** - REST API endpoint for custom integrations
- **WebSocket** - Real-time web interface

Each channel will follow the same unified message architecture, enabling agents to work across platforms without modification.
