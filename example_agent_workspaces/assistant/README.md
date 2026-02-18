# Assistant — Example Workspace

A minimal OpenPaw workspace demonstrating the basic structure. Copy this to `agent_workspaces/` and customize.

## Quick Start

1. Copy to your workspaces directory:
   ```bash
   cp -r example_agent_workspaces/assistant agent_workspaces/my-assistant
   ```

2. Edit `agent.yaml`:
   - Set your model provider and API key
   - Set your Telegram bot token and user ID

3. Customize the personality files:
   - `SOUL.md` — Who the agent *is* (personality, values, tone)
   - `AGENT.md` — What the agent *does* (role, responsibilities)
   - `USER.md` — Who it serves (your context and preferences)

4. Run:
   ```bash
   poetry run openpaw -c config.yaml -w my-assistant
   ```

## Structure

| File | Purpose |
|------|---------|
| `SOUL.md` | Core personality and values |
| `AGENT.md` | Role, mission, responsibilities |
| `USER.md` | User context and preferences |
| `HEARTBEAT.md` | Scratchpad for proactive check-ins |
| `agent.yaml` | Model, channel, queue, builtin config |
| `crons/` | Scheduled task definitions |

See the [Workspaces documentation](../../docs/workspaces.md) for the full reference.
