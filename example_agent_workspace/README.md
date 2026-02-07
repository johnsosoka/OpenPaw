# Example Agent Workspace

This is a reference implementation showing the recommended structure for an OpenPaw agent workspace. Copy this directory to `agent_workspaces/<your_agent_name>/` and customize.

## Structure

```
example_agent_workspace/
├── SOUL.md          # Core identity, beliefs, personality, tone
├── AGENT.md         # Role, mission, responsibilities, success criteria
├── USER.md          # User context, assumptions, preferences
├── HEARTBEAT.md     # Current state, active threads, session notes
├── agent.yaml       # Configuration (model, channel, queue, builtins)
├── crons/           # Scheduled tasks
│   └── daily-checkin.yaml
└── skills/          # DeepAgents native skills (optional)
    └── .gitkeep
```

## File Purposes

### SOUL.md (Required)
Defines WHO the agent IS at its core. This shapes personality, values, and communication style. Think of it as the agent's character sheet.

**Key sections:**
- Identity - One-sentence essence
- Core Beliefs - What the agent holds true
- Tone - Communication style descriptors

### AGENT.md (Required)
Defines WHAT the agent DOES. Role, responsibilities, and how success is measured.

**Key sections:**
- Role - Job title or function
- Mission - Primary objective
- Responsibilities - Specific duties
- Success Criteria - How to measure effectiveness

### USER.md (Required)
Defines WHO the agent serves. Context about the user to inform responses.

**Key sections:**
- User Profile - Who they are
- Assumptions - What to take for granted
- Preferences - Communication and work style

### HEARTBEAT.md (Required)
Defines the agent's CURRENT STATE. Updated during sessions to maintain context.

**Key sections:**
- Current State - What's happening now
- Active Threads - Ongoing conversations/tasks
- Notes - Session-specific observations

### agent.yaml (Required)
Configuration for model, channel, queue behavior, and builtins.

**Key settings:**
- `model` - Provider, model name, temperature
- `channel` - Telegram token and allowlist
- `queue` - Message batching behavior
- `heartbeat` - Proactive check-in settings
- `builtins` - Tool availability

## Quick Start

1. Copy this directory:
   ```bash
   cp -r example_agent_workspace agent_workspaces/my_agent
   ```

2. Edit the markdown files to define your agent's personality and role

3. Update `agent.yaml` with your credentials:
   - Set `TELEGRAM_BOT_TOKEN` environment variable
   - Add your Telegram user ID to `allowed_users`
   - Choose your model provider

4. Run:
   ```bash
   poetry run openpaw -c config.yaml -w my_agent
   ```

## Best Practices

1. **SOUL before AGENT** - Define personality first, then role
2. **Be specific** - Vague instructions produce vague behavior
3. **Use environment variables** - Never commit secrets
4. **Start with `collect` queue mode** - Prevents message fragmentation
5. **Enable heartbeat cautiously** - Start with long intervals
6. **Test with one user first** - Use `allowed_users` allowlist
