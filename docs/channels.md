# Channels

Channels connect agents to communication platforms. OpenPaw currently supports Telegram with an extensible architecture for additional platforms.

## Channel Architecture

```
Platform (Telegram) → Channel Adapter → Unified Message Format → Queue → Agent
```

Channel adapters translate platform-specific messages into OpenPaw's unified `Message` format, enabling consistent agent behavior across platforms.

## Telegram Channel

The Telegram channel uses [python-telegram-bot](https://python-telegram-bot.org/) to interface with Telegram's Bot API.

### Setup

1. **Create a Telegram bot:**

   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Send `/newbot` and follow prompts
   - Save the bot token (format: `123456:ABC-DEF...`)

2. **Configure OpenPaw:**

   ```yaml
   channels:
     telegram:
       token: ${TELEGRAM_BOT_TOKEN}
       allowed_users: []    # Empty = allow all
       allowed_groups: []   # Empty = allow all
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
   - Send a message
   - Agent should respond

### Access Control

Restrict who can interact with the bot using allowlists.

#### User Allowlist

```yaml
channels:
  telegram:
    allowed_users: [123456789, 987654321]
```

To get your Telegram user ID:
- Message [@userinfobot](https://t.me/userinfobot)
- It will reply with your user ID

Only listed users can message the bot. Messages from other users are ignored.

#### Group Allowlist

```yaml
channels:
  telegram:
    allowed_groups: [-1001234567890]
```

To get a group ID:
1. Add [@RawDataBot](https://t.me/RawDataBot) to your group
2. It will post the group's chat ID
3. Remove the bot after getting the ID

Only messages from listed groups are processed.

#### Combined Allowlists

```yaml
channels:
  telegram:
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

If the `whisper` builtin is enabled, voice messages are automatically transcribed.

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
- `poetry install --extras voice`

**Behavior:**
1. User sends voice message
2. OpenPaw downloads audio file
3. Whisper transcribes to text
4. Text is processed as a normal message
5. Agent responds

If transcription fails, the user receives an error message.

#### Audio Files

Treated the same as voice messages if `whisper` is enabled.

### Multi-Workspace Telegram Setup

Each workspace can have its own Telegram bot or share a bot with channel-specific routing.

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

### Bot Commands

Telegram bots can define custom commands visible in the chat interface.

**Set commands with BotFather:**

```
/setcommands
/help - Show available commands
/status - Check agent status
/reset - Clear conversation history
```

Agents receive commands as regular text messages and can handle them in their personality files:

```markdown
# AGENT.md

## Command Handling

When the user sends `/status`, respond with current workspace state from HEARTBEAT.md.

When the user sends `/reset`, acknowledge and start a fresh conversation context.
```

### Error Handling

**Bot token invalid:**
```
Error: telegram.error.InvalidToken
```
Solution: Verify `TELEGRAM_BOT_TOKEN` is correct and active.

**Forbidden error:**
```
Error: telegram.error.Forbidden
```
Solution: User has blocked the bot. Remove from `allowed_users` or ask user to unblock.

**Message too long:**
Telegram messages have a 4096 character limit. OpenPaw automatically splits long responses.

**Rate limiting:**
Telegram enforces rate limits. If the agent sends too many messages too quickly, requests will be throttled. Implement delays in agent logic if this occurs.

## Message Format

Channels convert platform messages to a unified format:

```python
@dataclass
class Message:
    content: str              # Message text
    sender: str               # User identifier
    channel: str              # Channel type ("telegram")
    session_id: str           # Conversation session ID
    metadata: dict[str, Any]  # Platform-specific data
```

### Metadata Fields (Telegram)

```python
{
    "chat_id": 123456789,        # Telegram chat ID
    "message_id": 12345,         # Message ID
    "username": "johndoe",       # Telegram username
    "first_name": "John",        # User's first name
    "is_group": False,           # True if from a group
    "audio_file": "/path/to.ogg" # Present if voice/audio message
}
```

## Adding New Channels

OpenPaw's channel system is extensible. To add a new platform:

### 1. Create Channel Adapter

Create `openpaw/channels/<platform>.py`:

```python
from openpaw.channels.base import BaseChannel, Message

class DiscordChannel(BaseChannel):
    def __init__(self, config: dict):
        super().__init__(config)
        self.client = discord.Client(...)  # Platform client

    async def start(self):
        """Initialize platform connection"""
        await self.client.start()

    async def stop(self):
        """Shutdown platform connection"""
        await self.client.close()

    async def send_message(self, message: Message):
        """Send message to platform"""
        await self.client.send_message(
            message.metadata["channel_id"],
            message.content
        )

    def _to_internal_message(self, platform_msg) -> Message:
        """Convert platform message to unified format"""
        return Message(
            content=platform_msg.content,
            sender=str(platform_msg.author.id),
            channel="discord",
            session_id=f"discord_{platform_msg.channel.id}",
            metadata={
                "channel_id": platform_msg.channel.id,
                "author_name": platform_msg.author.name,
                # ... other platform-specific data
            }
        )
```

### 2. Register Channel

Update `openpaw/channels/__init__.py`:

```python
from openpaw.channels.telegram import TelegramChannel
from openpaw.channels.discord import DiscordChannel  # New

CHANNEL_REGISTRY = {
    "telegram": TelegramChannel,
    "discord": DiscordChannel,  # New
}
```

### 3. Update Configuration Schema

Add to `openpaw/core/config.py`:

```python
class ChannelConfig(BaseModel):
    type: Literal["telegram", "discord"]  # Add new type
    # ... rest of config
```

### 4. Test the Channel

Create a workspace using the new channel:

```yaml
# agent.yaml
channel:
  type: discord
  token: ${DISCORD_BOT_TOKEN}
  guild_id: 123456789
```

### Channel Requirements

New channel implementations must:
- Extend `BaseChannel`
- Implement `start()`, `stop()`, `send_message()`
- Convert platform messages to unified `Message` format
- Handle platform-specific errors gracefully
- Support access control (allowlists)

## Best Practices

1. **Use environment variables** - Never commit bot tokens
2. **Restrict access** - Use allowlists for production bots
3. **Test in private chats** - Verify bot behavior before adding to groups
4. **Handle errors gracefully** - Don't crash on malformed messages
5. **Log channel activity** - Enable verbose logging (`-v`) during setup
6. **Rate limit awareness** - Don't spam platforms with rapid messages
7. **Platform-specific features** - Leverage buttons, inline keyboards, etc. when available

## Future Channels

Planned channel support:
- **Discord** - Server/channel-based conversations
- **Slack** - Workspace integration
- **WhatsApp** - Direct messaging
- **CLI** - Terminal-based testing interface
- **HTTP** - REST API for custom integrations

Each channel will follow the same unified message architecture, enabling agents to work across platforms without modification.
