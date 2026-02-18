# Channels

Channels connect agents to communication platforms. OpenPaw currently supports Telegram with an extensible architecture for additional platforms.

## Channel Architecture

```
Platform (Telegram) → Channel Adapter → Unified Message Format → Queue → Agent
```

Channel adapters translate platform-specific messages into OpenPaw's unified `Message` format, enabling consistent agent behavior across platforms.

### Channel Factory Pattern

Channels are created via the factory pattern in `openpaw/channels/factory.py`:

```python
def create_channel(channel_type: str, config: ChannelConfig, workspace_name: str) -> ChannelAdapter:
    """Create a channel instance based on type.

    Args:
        channel_type: Channel type ("telegram", etc.)
        config: Channel configuration
        workspace_name: Name of workspace this channel belongs to

    Returns:
        Configured channel adapter instance
    """
```

This decouples `WorkspaceRunner` from concrete channel types, enabling extensibility without framework modifications.

## Unified Message Format

All channels convert platform-specific messages to OpenPaw's unified format defined in `openpaw/domain/message.py`:

```python
@dataclass
class Message:
    """Unified message format across all channels."""

    id: str                                    # Unique message ID
    channel: str                               # Channel type ("telegram")
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

   Global config (`config.yaml`):
   ```yaml
   channels:
     telegram:
       token: ${TELEGRAM_BOT_TOKEN}
       allowed_users: []    # Empty = allow all
       allowed_groups: []   # Empty = allow all
   ```

   Or per-workspace (`agent.yaml`):
   ```yaml
   channel:
     type: telegram
     token: ${TELEGRAM_BOT_TOKEN}
     allowed_users: [123456789]
     allowed_groups: []
   ```

3. **Set environment variable:**

   ```bash
   export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
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

Only listed users can message the bot. Messages from other users are silently ignored.

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

Only messages from listed groups are processed.

#### Combined Allowlists

```yaml
channel:
  type: telegram
  allowed_users: [123456789]
  allowed_groups: [-1001234567890]
```

Bot will respond in:
- Direct messages from user `123456789`
- Messages in group `-1001234567890` from any member

### Supported Message Types

#### Text Messages

Standard text messages are processed directly.

```
User: "What's the weather like?"
Agent: [Processes and responds]
```

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
2. `FilePersistenceProcessor` saves audio to `uploads/{YYYY-MM-DD}/voice_123.ogg`
3. `WhisperProcessor` transcribes audio to text
4. Transcript saved as sibling file `uploads/{YYYY-MM-DD}/voice_123.txt`
5. Message content enriched with file receipt notification and transcript
6. Agent processes enriched message

If transcription fails, the user receives an error message.

#### Audio Files

Audio files (MP3, M4A, etc.) are treated the same as voice messages if `whisper` is enabled.

#### Documents

Document files (PDF, DOCX, PPTX, etc.) are automatically processed if the `docling` builtin is enabled.

**Configuration:**

```yaml
builtins:
  docling:
    enabled: true
```

**Requirements:**
- `docling` package installed

**Processing Flow:**
1. User uploads document
2. `FilePersistenceProcessor` saves to `uploads/{YYYY-MM-DD}/report.pdf`
3. `DoclingProcessor` converts document to markdown
4. Markdown saved as sibling file `uploads/{YYYY-MM-DD}/report.md`
5. Message content enriched with file receipt notification and conversion summary
6. Agent can read the converted markdown or original file

Supported formats: PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, and more.

#### Photos

Photos are automatically saved to the workspace uploads directory.

**Processing Flow:**
1. User sends photo
2. `FilePersistenceProcessor` downloads and saves to `uploads/{YYYY-MM-DD}/photo_123.jpg`
3. Message content enriched with file receipt notification
4. Agent can access the saved image file

### File Persistence

All uploaded files are automatically saved to `{workspace}/uploads/{YYYY-MM-DD}/` with date partitioning by the `FilePersistenceProcessor` (enabled by default).

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
[Saved to: uploads/2026-02-17/report.pdf]
```

Processors (Whisper, Docling) create sibling output files alongside the original:
- `voice_123.ogg` → `voice_123.txt` (transcript)
- `report.pdf` → `report.md` (converted markdown)

### Framework Commands

Framework commands are handled by `CommandRouter` before messages reach the agent. These commands bypass the inbound processor pipeline to avoid content modification breaking detection.

**Built-in Commands:**
- `/start` - Welcome message (hidden from `/help`, for onboarding)
- `/new` - Archive current conversation and start fresh
- `/compact` - Summarize current conversation, archive it, start new with summary injected
- `/help` - List available commands with descriptions
- `/queue <mode>` - Change queue mode (`collect`, `steer`, `followup`, `interrupt`)
- `/status` - Show workspace info: model, conversation stats, active tasks, token usage

**Command Registration:**

Channels automatically register bot commands using `channel.register_commands()` which pulls from the `CommandRouter`'s definition list. For Telegram, this creates the command menu visible in the chat interface.

**Note:** These are framework commands intercepted before reaching the agent, NOT regular text processed by the agent's personality files.

### Approval Gate UI

Telegram channels support approval gates for dangerous tool operations via inline keyboards.

**Example Approval Request:**

```
The agent wants to run: overwrite_file

Arguments:
  path: important_config.yaml
  content: [300 characters]

[Approve] [Deny]
```

When a gated tool is called:
1. Execution pauses
2. Telegram sends inline keyboard with Approve/Deny buttons
3. User clicks a button
4. On approval: agent re-runs with tool execution allowed
5. On denial: agent receives system message that tool was denied

**Configuration:**

```yaml
approval_gates:
  enabled: true
  timeout_seconds: 120
  default_action: deny
  tools:
    overwrite_file:
      require_approval: true
      show_args: true
```

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

This metadata is available to the agent and custom tools via the `Message.metadata` dict.

### Session Keys

Telegram session keys follow the format `"telegram:{user_id}"` for direct messages and `"telegram:{group_id}"` for group chats.

Examples:
- Direct message: `"telegram:123456789"`
- Group chat: `"telegram:-1001234567890"`

Session keys are used for:
- Conversation thread tracking
- Queue management
- Session state persistence

### Multi-Workspace Telegram Setup

Each workspace can have its own Telegram bot or share a bot with user-specific routing.

#### Option 1: Separate Bots per Workspace

```yaml
# workspace1/agent.yaml
channel:
  type: telegram
  token: ${WORKSPACE1_TELEGRAM_TOKEN}
  allowed_users: [123456789]
```

```yaml
# workspace2/agent.yaml
channel:
  type: telegram
  token: ${WORKSPACE2_TELEGRAM_TOKEN}
  allowed_users: [987654321]
```

Each workspace has its own bot and user allowlist.

#### Option 2: Shared Bot with User Routing

```yaml
# Global config.yaml
channels:
  telegram:
    token: ${TELEGRAM_BOT_TOKEN}
```

```yaml
# workspace1/agent.yaml
channel:
  allowed_users: [123456789]
```

```yaml
# workspace2/agent.yaml
channel:
  allowed_users: [987654321]
```

Single bot token, but each workspace only responds to specific users.

### Error Handling

**Bot token invalid:**
```
Error: telegram.error.InvalidToken
```
Solution: Verify `TELEGRAM_BOT_TOKEN` is correct and active. Check BotFather conversation for the correct token.

**Forbidden error:**
```
Error: telegram.error.Forbidden
```
Solution: User has blocked the bot. Remove from `allowed_users` or ask user to unblock.

**Message too long:**
Telegram messages have a 4096 character limit. OpenPaw automatically splits long responses into multiple messages.

**Rate limiting:**
Telegram enforces rate limits (30 messages per second to different users). If the agent sends too many messages too quickly, requests will be throttled. The framework handles retries automatically.

**File size limits:**
Telegram has a 50 MB file size limit for bots. The `FilePersistenceProcessor` enforces this limit and returns an error for larger files.

## Adding New Channels

OpenPaw's channel system is extensible. To add a new platform:

### 1. Create Channel Adapter

Create `openpaw/channels/<platform>.py` extending `ChannelAdapter`:

```python
from openpaw.channels.base import ChannelAdapter
from openpaw.domain.message import Message, Attachment, MessageDirection
from openpaw.channels.commands.router import CommandRouter, CommandContext, CommandResult
from typing import Callable, Awaitable
import discord  # Platform SDK

class DiscordChannel(ChannelAdapter):
    """Discord channel adapter."""

    def __init__(
        self,
        workspace_name: str,
        config: dict,
        command_router: CommandRouter,
        on_message: Callable[[Message], Awaitable[None]],
        on_command: Callable[[Message], Awaitable[CommandResult]],
    ):
        super().__init__(workspace_name, config, command_router, on_message, on_command)
        self.client = discord.Client(...)
        self.allowed_guilds = config.get("allowed_guilds", [])

        # Register message handler
        @self.client.event
        async def on_message(discord_msg):
            if discord_msg.author == self.client.user:
                return

            # Access control
            if self.allowed_guilds and discord_msg.guild.id not in self.allowed_guilds:
                return

            # Convert to unified format
            message = self._to_unified_message(discord_msg)

            # Handle commands or regular messages
            if message.is_command:
                await self._handle_command(message)
            else:
                await self.on_message(message)

    async def start(self):
        """Initialize Discord connection."""
        await self.client.start(self.config["token"])

    async def stop(self):
        """Shutdown Discord connection."""
        await self.client.close()

    async def send_message(self, session_key: str, content: str):
        """Send message to Discord channel."""
        # Parse channel ID from session_key
        _, channel_id = session_key.split(":", 1)
        channel = self.client.get_channel(int(channel_id))
        await channel.send(content)

    async def send_file(
        self,
        session_key: str,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ):
        """Send file to Discord channel."""
        _, channel_id = session_key.split(":", 1)
        channel = self.client.get_channel(int(channel_id))
        with open(file_path, "rb") as f:
            await channel.send(content=caption, file=discord.File(f, filename=filename))

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict,
    ):
        """Send approval request with UI."""
        # Implement Discord-specific approval UI (buttons, reactions, etc.)
        pass

    def _to_unified_message(self, discord_msg) -> Message:
        """Convert Discord message to unified format."""
        # Build session key
        session_key = f"discord:{discord_msg.channel.id}"

        # Handle attachments
        attachments = [
            Attachment(
                type="document",
                url=att.url,
                filename=att.filename,
                mime_type=att.content_type,
            )
            for att in discord_msg.attachments
        ]

        return Message(
            id=str(discord_msg.id),
            channel="discord",
            session_key=session_key,
            user_id=str(discord_msg.author.id),
            content=discord_msg.content,
            direction=MessageDirection.INBOUND,
            timestamp=discord_msg.created_at,
            metadata={
                "channel_id": discord_msg.channel.id,
                "guild_id": discord_msg.guild.id if discord_msg.guild else None,
                "author_name": discord_msg.author.name,
                "author_discriminator": discord_msg.author.discriminator,
            },
            attachments=attachments,
        )
```

### 2. Register in Channel Factory

Update `openpaw/channels/factory.py`:

```python
from openpaw.channels.telegram import TelegramChannel
from openpaw.channels.discord import DiscordChannel  # New

def create_channel(
    channel_type: str,
    config: ChannelConfig,
    workspace_name: str,
    command_router: CommandRouter,
    on_message: Callable[[Message], Awaitable[None]],
    on_command: Callable[[Message], Awaitable[CommandResult]],
) -> ChannelAdapter:
    """Create a channel instance based on type."""
    if channel_type == "telegram":
        return TelegramChannel(workspace_name, config, command_router, on_message, on_command)
    elif channel_type == "discord":  # New
        return DiscordChannel(workspace_name, config, command_router, on_message, on_command)
    else:
        raise ValueError(f"Unknown channel type: {channel_type}")
```

### 3. Update Configuration Models

Add to `openpaw/core/config/models.py`:

```python
class ChannelConfig(BaseModel):
    """Channel configuration."""

    type: Literal["telegram", "discord"]  # Add new type
    token: str | None = None
    allowed_users: list[int] = Field(default_factory=list)
    allowed_groups: list[int] = Field(default_factory=list)
    allowed_guilds: list[int] = Field(default_factory=list)  # Discord-specific
```

### 4. Test the Channel

Create a workspace using the new channel:

```yaml
# agent.yaml
channel:
  type: discord
  token: ${DISCORD_BOT_TOKEN}
  allowed_guilds: [123456789]
```

### Channel Adapter Requirements

New channel implementations must:

1. **Extend `ChannelAdapter`** - Base class in `openpaw/channels/base.py`
2. **Implement core methods:**
   - `async def start()` - Initialize platform connection
   - `async def stop()` - Shutdown platform connection
   - `async def send_message(session_key, content)` - Send text message
   - `async def send_file(session_key, file_path, filename, caption)` - Send file to user
   - `async def send_approval_request(session_key, approval_id, tool_name, tool_args)` - Optional approval UI
   - `def _to_unified_message(platform_msg) -> Message` - Convert platform message to unified format
3. **Handle platform-specific errors gracefully** - Don't crash on malformed messages
4. **Support access control** - Implement allowlisting for users/channels/servers
5. **Register commands** - Call `register_commands()` with command definitions
6. **Convert attachments** - Map platform attachments to `Attachment` objects with proper metadata
7. **Session key format** - Use `"{channel}:{id}"` format (e.g., `"discord:987654321"`)

## Best Practices

1. **Use environment variables** - Never commit bot tokens to version control
2. **Restrict access** - Use allowlists (`allowed_users`, `allowed_groups`) for production bots
3. **Test in private chats** - Verify bot behavior before adding to groups
4. **Handle errors gracefully** - Log errors but don't crash on malformed messages
5. **Enable verbose logging** - Use `-v` flag during setup to debug channel issues
6. **Rate limit awareness** - Don't spam platforms with rapid messages; respect rate limits
7. **Platform-specific features** - Leverage inline keyboards, buttons, reactions when available
8. **File size limits** - Enforce platform-specific file size limits in adapters
9. **Session key consistency** - Always use `"{channel}:{id}"` format for session keys
10. **Command registration** - Let the framework handle command registration; don't set manually

## Future Channels

Planned channel support:

- **Discord** - Server/channel-based conversations
- **Slack** - Workspace integration with slash commands
- **WhatsApp** - Direct messaging via WhatsApp Business API
- **CLI** - Terminal-based interface for local testing
- **HTTP** - REST API endpoint for custom integrations
- **WebSocket** - Real-time web interface

Each channel will follow the same unified message architecture, enabling agents to work across platforms without modification.
