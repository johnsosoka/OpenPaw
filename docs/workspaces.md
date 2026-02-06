# Workspaces

Workspaces are isolated agent instances with their own personality, configuration, and capabilities. Each workspace represents a distinct AI agent with specific behavior patterns and access permissions.

## Directory Structure

```
agent_workspaces/<workspace-name>/
├── AGENT.md      # Capabilities, behavior guidelines
├── USER.md       # User context/preferences
├── SOUL.md       # Core personality, values
├── HEARTBEAT.md  # Current state, session notes
├── agent.yaml    # Optional workspace-specific configuration
├── crons/        # Scheduled task definitions
│   └── *.yaml
└── skills/       # DeepAgents native skills
    └── SKILL.md
```

## Required Files

Every workspace must contain four markdown files that define the agent's identity and behavior.

### AGENT.md - Capabilities and Behavior

Defines what the agent can do and how it should behave.

**Example:**

```markdown
# Agent Profile

You are Gilfoyle, a senior systems architect and DevOps engineer.

## Capabilities

- AWS infrastructure management (Lambda, S3, DynamoDB)
- Python development (FastAPI, SQLAlchemy, Pydantic)
- Terraform infrastructure-as-code
- CI/CD pipeline design
- System architecture and design patterns

## Communication Style

- Be direct and technically precise
- Avoid unnecessary pleasantries
- Use sarcasm sparingly but effectively
- Cite specific technologies and patterns when relevant

## Constraints

- Do not make AWS changes without confirmation
- Always explain architectural decisions
- Prioritize security and scalability
```

### USER.md - User Context

Information about the user(s) this agent serves.

**Example:**

```markdown
# User Profile

## Name
John Sosoka

## Role
Engineering Lead

## Preferences
- Prefers concise technical explanations
- Works in Pacific Time (PT)
- Uses AWS us-west-2 region by default

## Context
- Manages multiple client projects
- Values clean, maintainable code
- Follows Clean Code and Clean Architecture principles
```

### SOUL.md - Core Personality

The agent's fundamental values and personality traits.

**Example:**

```markdown
# Core Values

## Technical Excellence
Always prioritize correctness, clarity, and maintainability over cleverness.

## Honesty
If you don't know something, say so. Don't speculate or guess about critical systems.

## Efficiency
Value the user's time. Be concise but complete.

## Professionalism
Maintain professional communication standards. You represent the engineering team.
```

### HEARTBEAT.md - Current State

Session state and notes. The agent can read and modify this file to persist information across conversations.

**Example:**

```markdown
# Current State

## Session Started
2026-02-05

## Active Projects
- OpenPaw: Multi-channel agent framework
- ClientX: AWS Lambda migration

## Pending Tasks
- Review OpenPaw documentation
- Update Terraform modules for ClientX

## Recent Learnings
- DeepAgents FilesystemBackend for workspace isolation
- APScheduler for cron implementation
```

The agent can update HEARTBEAT.md during conversations to track ongoing work, decisions, and context.

## Optional Configuration

### agent.yaml - Workspace Configuration

Override global configuration for this specific workspace.

**Example:**

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
  allowed_users: [123456789]
  allowed_groups: []

queue:
  mode: steer
  debounce_ms: 500

builtins:
  allow:
    - brave_search
  deny:
    - elevenlabs
```

See [configuration.md](configuration.md) for detailed options.

## Skills

Skills are reusable capabilities that agents can invoke during conversations. OpenPaw uses DeepAgents' native skill system.

### Creating a Skill

1. Create a directory in `agent_workspaces/<workspace-name>/skills/<skill-name>/`
2. Add a `SKILL.md` file defining the skill

**Example: Email skill**

```
agent_workspaces/gilfoyle/skills/send-email/SKILL.md
```

```markdown
# Send Email Skill

Send an email to a recipient.

## Usage

Use this skill when the user asks to send an email or notification.

## Parameters

- recipient: Email address (string, required)
- subject: Email subject line (string, required)
- body: Email content (string, required)

## Example

User: "Email John about the deployment"
Assistant: I'll send an email to john@example.com

[Uses send-email skill with parameters...]
```

DeepAgents will parse this skill definition and make it available to the agent.

### Skill Best Practices

1. **Clear documentation** - Explain when and how to use the skill
2. **Explicit parameters** - Define all required and optional parameters
3. **Examples** - Show typical usage patterns
4. **Error handling** - Document what happens if the skill fails

## Scheduled Tasks (Crons)

Define scheduled tasks in the `crons/` directory.

**Example: crons/daily-summary.yaml**

```yaml
name: daily-summary
schedule: "0 9 * * *"  # 9 AM daily
enabled: true

prompt: |
  Generate a daily summary by reviewing:
  - Active projects in HEARTBEAT.md
  - Pending tasks
  - Recent conversations

  Provide a concise status update.

output:
  channel: telegram
  chat_id: 123456789
```

See [cron-scheduler.md](cron-scheduler.md) for detailed configuration.

## Workspace Isolation

Each workspace is fully isolated:

- **Separate channels** - Own Telegram bot or dedicated channel
- **Independent queue** - Own queue manager and concurrency limits
- **Isolated filesystem** - Can only read/write within workspace directory
- **Dedicated agent instance** - Own LangGraph agent with separate memory
- **Per-workspace crons** - Scheduled tasks scoped to workspace

This enables running multiple agents simultaneously without interference:

```bash
poetry run openpaw -c config.yaml -w gilfoyle,assistant,scheduler
```

Each agent operates independently with its own configuration and personality.

## Filesystem Access

Agents have sandboxed filesystem access to their workspace directory via DeepAgents' `FilesystemBackend`.

### Available Operations

- **Read files** - Access workspace markdown files, skill definitions
- **Write files** - Update HEARTBEAT.md, create notes, persist data
- **Create directories** - Organize workspace-specific data
- **List contents** - Browse workspace structure

### Restrictions

- **Workspace-scoped** - Cannot access files outside workspace directory
- **No system access** - Cannot modify OpenPaw core files or other workspaces
- **Safe by default** - All operations are sandboxed

### Example Use Cases

**Persistent notes:**
```
Agent reads HEARTBEAT.md → Updates pending tasks → Writes back to file
```

**Data organization:**
```
Agent creates notes/ directory → Saves meeting summaries → Retrieves on demand
```

**Skill data:**
```
Agent saves API responses → Cron job processes data → Summarizes results
```

## Creating a New Workspace

1. **Create directory structure:**

```bash
mkdir -p agent_workspaces/my-agent/skills agent_workspaces/my-agent/crons
```

2. **Create required markdown files:**

```bash
cd agent_workspaces/my-agent
touch AGENT.md USER.md SOUL.md HEARTBEAT.md
```

3. **Define personality:**

Edit each markdown file to define the agent's capabilities, user context, values, and initial state.

4. **Add configuration (optional):**

Create `agent.yaml` if you need to override global settings.

5. **Add skills (optional):**

Create skill directories under `skills/` with `SKILL.md` definitions.

6. **Add cron jobs (optional):**

Create YAML files under `crons/` for scheduled tasks.

7. **Run the workspace:**

```bash
poetry run openpaw -c config.yaml -w my-agent
```

## Example Workspaces

### Technical Support Agent

```markdown
# AGENT.md
You are a technical support specialist for SaaS products.

## Capabilities
- Troubleshooting common issues
- API debugging assistance
- Documentation lookup
- Issue escalation when needed
```

```yaml
# agent.yaml
queue:
  mode: followup  # Process support requests sequentially

builtins:
  allow:
    - brave_search  # Enable documentation search
```

### Scheduled Reporter

```markdown
# AGENT.md
You generate daily reports by analyzing system state and recent activity.

## Capabilities
- Reading workspace files
- Summarizing project status
- Identifying pending tasks
```

```yaml
# crons/daily-report.yaml
name: daily-report
schedule: "0 9 * * 1-5"  # Weekdays at 9 AM
enabled: true

prompt: |
  Review all workspace files and generate a status report.
  Include: active projects, completed tasks, blockers.
```

### Multi-User Assistant

```markdown
# AGENT.md
You are a team assistant supporting multiple engineers.

## Capabilities
- Task tracking
- Calendar management
- Documentation lookup
```

```yaml
# agent.yaml
channel:
  type: telegram
  allowed_groups: [group-id-here]  # Team group chat
```

## Best Practices

1. **Clear identity** - Give each workspace a distinct personality and purpose
2. **Focused capabilities** - Don't try to make one agent do everything
3. **Consistent voice** - Maintain personality across all markdown files
4. **Appropriate permissions** - Use `allowed_users` to restrict access
5. **Regular updates** - Keep HEARTBEAT.md current with ongoing work
6. **Skill organization** - Group related skills in subdirectories
7. **Cron hygiene** - Disable unused cron jobs rather than deleting them
