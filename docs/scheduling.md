# Scheduling

<div align="center">
  <img src="../assets/images/openpaw-bear-2.png" alt="OpenPaw Scheduling" width="500">
</div>

OpenPaw supports two types of scheduling — **cron jobs** for periodic tasks and **heartbeats** for proactive agent check-ins. Both run in the workspace timezone and create fresh agent instances with full access to workspace files and enabled builtins.

---

## Cron Jobs

Cron jobs let you define tasks that run on a schedule, independently of any user conversation. Each job sends a prompt to the agent, and the agent can read workspace files, call builtins, and route its response to a channel.

### Static Cron Jobs

Static cron jobs are defined as YAML files in the `crons/` directory of your workspace. Each file defines one job.

```
agent_workspaces/my-agent/crons/
├── daily-summary.yaml
├── weekly-report.yaml
└── health-check.yaml
```

A complete cron job definition:

```yaml
name: daily-summary
schedule: "0 9 * * 1-5"  # Weekdays at 9 AM (workspace timezone)
enabled: true

prompt: |
  Generate a daily status report.

  Include:
  - Active projects and current status
  - Tasks completed yesterday
  - Planned work for today
  - Any blockers or issues

output:
  channel: telegram
  chat_id: 123456789
  delivery: channel  # channel (default), agent, or both
```

#### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier for the job within this workspace |
| `schedule` | Yes | Cron expression (see format below) |
| `enabled` | Yes | Set to `false` to pause the job without deleting it |
| `prompt` | Yes | The prompt sent to the agent at execution time |
| `output.channel` | Yes | Channel type to deliver output to |
| `output.chat_id` | Yes | Channel-specific destination (e.g., Telegram user or group ID) |
| `output.delivery` | No | Where to send results: `channel` (default), `agent`, or `both` |

Both `.yaml` and `.yml` file extensions are supported.

#### Cron Expression Format

```
 ┌───────────── minute (0 - 59)
 │ ┌───────────── hour (0 - 23)
 │ │ ┌───────────── day of month (1 - 31)
 │ │ │ ┌───────────── month (1 - 12)
 │ │ │ │ ┌───────────── day of week (0 - 6) (Sunday to Saturday)
 │ │ │ │ │
 * * * * *
```

Common schedule expressions:

| Expression | When it fires |
|------------|---------------|
| `"*/15 * * * *"` | Every 15 minutes |
| `"0 * * * *"` | Every hour on the hour |
| `"0 9 * * *"` | Daily at 9:00 AM |
| `"0 9 * * 1-5"` | Weekdays at 9:00 AM |
| `"0 8 * * 1"` | Weekly on Monday at 8:00 AM |
| `"0 0 1 * *"` | First day of each month at midnight |
| `"0 0 * * 0"` | Every Sunday at midnight |

Use [crontab.guru](https://crontab.guru) to validate expressions before deploying.

#### Delivery Modes

The `delivery` field controls where cron results go:

- **`channel`** (default) — Sends the agent's response directly to the configured channel
- **`agent`** — Injects the cron output into the main agent's message queue as a `[SYSTEM]` event. The main agent receives a notification with the session log path so it can read the full output.
- **`both`** — Sends to channel AND injects into the agent queue

```yaml
# Route output to the main agent instead of the channel
output:
  channel: telegram
  chat_id: 123456789
  delivery: agent
```

### Static Cron Job Examples

#### Daily Status Report

```yaml
name: daily-status
schedule: "0 9 * * 1-5"  # Weekdays at 9 AM
enabled: true

prompt: |
  Review HEARTBEAT.md and generate a daily status report.

  Include:
  - Active projects and current status
  - Tasks completed yesterday
  - Planned work for today
  - Any blockers or issues

output:
  channel: telegram
  chat_id: 123456789
```

#### Weekly Summary

```yaml
name: weekly-summary
schedule: "0 9 * * 1"  # Monday at 9 AM
enabled: true

prompt: |
  Generate a weekly summary for the past 7 days.

  Review workspace files and summarize:
  - Major accomplishments
  - Lessons learned
  - Upcoming priorities

output:
  channel: telegram
  chat_id: 123456789
```

#### Hourly Health Check

```yaml
name: health-check
schedule: "0 * * * *"  # Every hour
enabled: true

prompt: |
  Perform a health check:
  - Check for any urgent updates in HEARTBEAT.md
  - Review pending tasks
  - If urgent items exist, report them. Otherwise, remain silent.

output:
  channel: telegram
  chat_id: 123456789
```

#### End-of-Day Cleanup

```yaml
name: end-of-day
schedule: "0 18 * * 1-5"  # Weekdays at 6 PM
enabled: true

prompt: |
  End-of-day cleanup:

  1. Review HEARTBEAT.md and update status
  2. Move completed tasks to an archive section
  3. Summarize remaining work for tomorrow
  4. Send the summary

output:
  channel: telegram
  chat_id: 123456789
```

#### Monthly Report

```yaml
name: monthly-report
schedule: "0 9 1 * *"  # First day of month at 9 AM
enabled: true

prompt: |
  Generate a monthly report covering:
  - Projects completed this month
  - Key metrics or milestones
  - Upcoming priorities for next month

  Review all workspace files for comprehensive context.

output:
  channel: telegram
  chat_id: 123456789
```

### Managing Cron Jobs

**Disable without deleting** — Set `enabled: false` to pause a job while preserving its definition:

```yaml
enabled: false  # Job is skipped but definition is preserved
```

This is useful for maintenance periods, seasonal schedules, or testing alternative approaches.

**Route to different recipients** — Each cron can specify its own output destination:

```yaml
# crons/team-update.yaml
output:
  channel: telegram
  chat_id: -1001234567890  # Team group chat

# crons/personal-reminder.yaml
output:
  channel: telegram
  chat_id: 123456789  # Personal DM
```

**Coordinate multiple jobs via filesystem** — Use workspace files to pass data between jobs:

```yaml
# crons/collect-data.yaml
schedule: "0 8 * * *"  # 8 AM
prompt: |
  Collect daily metrics and save to metrics/latest.md

# crons/process-data.yaml
schedule: "0 9 * * *"  # 9 AM (1 hour later)
prompt: |
  Read metrics/latest.md and generate an analysis report
```

**Crons are workspace-scoped** — Each workspace runs its own independent set of cron jobs with its own timezone, agent configuration, and filesystem:

```
workspace1/crons/report.yaml  → Runs in workspace1 context
workspace2/crons/report.yaml  → Runs in workspace2 context (independent)
```

---

### Dynamic Scheduling

Agents can schedule their own follow-up actions at runtime. This enables autonomous workflows like "remind me in 20 minutes" or "check on this PR every hour" — driven by conversation rather than static configuration.

#### Available Tools

**`schedule_at`** — Schedule a one-time action at a specific timestamp:

```python
schedule_at(
    prompt="Check if the deploy has completed",
    fire_at="2026-02-17T14:30:00",  # ISO 8601 format, workspace timezone
    label="deploy-check"
)
```

**`schedule_every`** — Schedule a recurring action at a fixed interval:

```python
schedule_every(
    prompt="Check PR status and notify if merged",
    interval_seconds=3600,  # Every hour
    label="pr-monitor"
)
```

**`list_scheduled`** — List all pending scheduled tasks.

**`cancel_scheduled`** — Cancel a scheduled task by ID.

#### Example Scenarios

**Time-based reminder**

> User: "Remind me to check the server logs in 30 minutes"
>
> Agent calls `schedule_at` with a timestamp 30 minutes from now.
> At that time, the agent sends the reminder to the user's chat.

**Recurring monitoring**

> User: "Check on PR #456 every hour until it's merged"
>
> Agent calls `schedule_every` with `interval_seconds=3600`.
> Later, user says "Stop monitoring the PR."
> Agent calls `list_scheduled()` to find the task ID, then `cancel_scheduled`.

**Daily standup reminder**

> User: "Schedule a daily standup reminder at 9 AM"
>
> Agent calls `schedule_every` with `interval_seconds=86400` and a label.
> The task persists across restarts.

#### Storage and Lifecycle

Dynamic tasks persist to a JSON file in the workspace and survive restarts. One-time tasks clean up automatically after firing. Expired one-time tasks are removed on workspace startup. Recurring tasks continue until explicitly cancelled.

Responses route back to the first allowed user in the workspace's channel configuration.

#### Configuration

```yaml
builtins:
  cron:
    enabled: true
    config:
      min_interval_seconds: 300  # Minimum interval for recurring tasks (default: 5 min)
      max_tasks: 50              # Maximum pending tasks per workspace
```

---

### Cron Execution Model

Every cron execution — static or dynamic — runs on these principles:

**Fresh agent instance** — Each job gets a new agent with no conversation history and no accumulated memory. This ensures consistent, predictable execution regardless of what user conversations are happening in parallel.

**Full workspace access** — The agent can read and write files, call all enabled builtins, maintain persistent logs, and organize workspace directories.

**Stateless by design** — No state bleeds between runs. Design prompts to be idempotent: reference current file state rather than assuming what happened last time.

```yaml
# Good: references current state
prompt: |
  Review HEARTBEAT.md for active projects and generate a status update.

# Avoid: assumes state from a previous run
prompt: |
  Continue from where we left off yesterday.
```

---

## Heartbeats

The heartbeat system enables proactive agent check-ins on a configurable schedule — without any user message triggering them. Use heartbeats to monitor ongoing tasks, surface status updates, or maintain situational awareness between conversations.

[![Heartbeat Decision Flow](../assets/diagrams/heartbeat-decision.png)](../assets/diagrams/heartbeat-decision.png)

### Configuration

Configure heartbeats in `agent.yaml`:

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30           # How often to check in
  active_hours: "09:00-17:00"    # Only fire during these hours (workspace timezone)
  suppress_ok: true              # Suppress output when nothing to report
  delivery: channel              # channel (default), agent, or both
  output:
    channel: telegram
    chat_id: 123456789
```

#### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `enabled` | Yes | Set to `true` to activate heartbeats |
| `interval_minutes` | Yes | How often to fire (in minutes) |
| `active_hours` | No | Time window to fire within, e.g. `"09:00-17:00"` (workspace timezone) |
| `suppress_ok` | No | When `true`, suppress output if the agent responds `HEARTBEAT_OK` |
| `delivery` | No | Where to send results: `channel` (default), `agent`, or `both` |
| `output.channel` | Yes | Channel type to deliver output to |
| `output.chat_id` | Yes | Channel-specific destination |

### HEARTBEAT_OK Protocol

When the agent determines there is nothing to report, it responds with exactly `HEARTBEAT_OK`. When `suppress_ok: true`, the heartbeat system discards this response and sends nothing to the channel. This prevents noisy "all clear" messages from flooding your chat.

The `HEARTBEAT_OK` response is always suppressed from both channel delivery and agent injection, regardless of the `delivery` mode.

### Active Hours

Heartbeats only fire within the `active_hours` window. Outside that window, the heartbeat is silently skipped — no agent invocation, no API cost, no output.

Active hours use the workspace timezone:

```yaml
timezone: America/Denver
heartbeat:
  active_hours: "09:00-17:00"  # 9 AM - 5 PM Denver time
```

If `active_hours` is omitted, heartbeats fire at every interval around the clock.

### Pre-flight Skip

Before invoking the LLM, the heartbeat system checks two conditions:

1. Is `HEARTBEAT.md` empty or trivial?
2. Are there no active tasks?

If both are true, the heartbeat is skipped entirely — no API call is made. This keeps costs low for idle workspaces that don't need proactive monitoring.

When either condition is false (HEARTBEAT.md has content, or tasks are active), the heartbeat proceeds normally.

!!! tip "Cost efficiency"
    Combine `active_hours`, `suppress_ok: true`, and the pre-flight skip to make heartbeats essentially free during quiet periods — they only incur API costs when there's something worth checking.

### Task-Aware Heartbeats

When active tasks exist, the heartbeat system automatically injects a compact summary into the agent's prompt before invoking the LLM:

```xml
<active_tasks>
  - "Investigate memory leak in worker process" (in_progress, started 2026-02-17T08:00:00)
  - "Update API documentation" (pending)
</active_tasks>
```

The agent receives this summary without needing to call `list_tasks()` — saving a tool call and keeping the heartbeat response focused.

### HEARTBEAT.md Scratchpad

`HEARTBEAT.md` is an agent-maintained notes file that persists across all heartbeat runs. The agent reads it at the start of each heartbeat to orient itself on what to check.

The agent can update `HEARTBEAT.md` during normal conversations to leave notes for future heartbeats:

```markdown
# Current Focus

- Monitoring PR #123 for merge conflicts
- Waiting on deployment approval from ops team
- Need to follow up on database migration at 3 PM

# Recent Updates

2026-02-17: Started monitoring the staging deploy
2026-02-16: Completed code review for auth refactor
```

When `HEARTBEAT.md` is empty, the pre-flight skip may prevent heartbeats from firing at all (unless active tasks exist). Populate it whenever there is ongoing work that warrants monitoring.

### Delivery Modes

The `delivery` field controls where heartbeat results go:

- **`channel`** (default) — Sends the agent's response directly to the configured channel
- **`agent`** — Injects the heartbeat output into the main agent's message queue as a `[SYSTEM]` event, with a reference to the full session log file
- **`both`** — Sends to channel AND injects into the agent queue

```yaml
# Deliver heartbeat output to the main agent's queue
heartbeat:
  delivery: agent
  output:
    channel: telegram
    chat_id: 123456789
```

When using `agent` or `both` delivery, the injected message includes the session log path so the main agent can call `read_file()` to access the full heartbeat output.

### Heartbeat Execution Model

Like cron jobs, each heartbeat runs on a fresh agent instance with no conversation history. The heartbeat system builds the prompt from `HEARTBEAT.md` content, the injected task summary (if tasks are active), and any framework instructions.

The agent responds, and the heartbeat system routes the response according to the `delivery` configuration — discarding `HEARTBEAT_OK` responses when `suppress_ok` is enabled.

---

## Timezone Handling

All scheduled tasks — static cron jobs, dynamic tasks, and heartbeats — fire in the workspace timezone.

Configure the workspace timezone in `agent.yaml` using any IANA timezone identifier:

```yaml
timezone: America/New_York  # IANA timezone identifier

heartbeat:
  active_hours: "09:00-17:00"  # 9 AM - 5 PM Eastern
```

```yaml
timezone: America/Denver

# "0 9 * * *" fires at 9:00 AM Mountain time
```

The default timezone is `UTC` if not specified. Invalid IANA identifiers are rejected at startup with a clear error message.

Common timezone identifiers:

| Region | Identifier |
|--------|-----------|
| Eastern US | `America/New_York` |
| Central US | `America/Chicago` |
| Mountain US | `America/Denver` |
| Pacific US | `America/Los_Angeles` |
| UTC | `UTC` |
| London | `Europe/London` |
| Berlin | `Europe/Berlin` |
| Tokyo | `Asia/Tokyo` |
| Sydney | `Australia/Sydney` |

!!! note "System vs. workspace timezone"
    Cron schedules fire in the **workspace timezone**, not the system timezone. A cron expression `"0 9 * * *"` with `timezone: America/Denver` fires at 9:00 AM Denver time regardless of where the server is located.

---

## Session Logging

Every scheduled run — cron job or heartbeat — writes a JSONL session log to the workspace `memory/sessions/` directory. The main agent can read these logs via `read_file()` to review what happened during past scheduled runs.

**Locations:**

```
memory/sessions/cron/        # Static and dynamic cron job logs
memory/sessions/heartbeat/   # Heartbeat logs
```

**File naming:** `{job-name}_{ISO-timestamp}.jsonl`

**Format** — Each log file contains three records:

```jsonl
{"type": "prompt", "content": "Review HEARTBEAT.md and generate a status update...", "timestamp": "2026-02-22T09:00:00+00:00"}
{"type": "response", "content": "Here is today's status...", "timestamp": "2026-02-22T09:00:45+00:00"}
{"type": "metadata", "tools_used": ["read_file", "send_message"], "metrics": {"input_tokens": 1234, "output_tokens": 567, "total_tokens": 1801, "llm_calls": 3}, "duration_ms": 4500.0, "timestamp": "2026-02-22T09:00:45+00:00"}
```

The heartbeat system also maintains a summary log at `heartbeat_log.jsonl` in the workspace root with one record per heartbeat event:

```json
{"timestamp": "2026-02-17T14:30:00Z", "outcome": "sent", "duration_ms": 1234, "tokens_in": 500, "tokens_out": 150, "active_tasks": 3}
{"timestamp": "2026-02-17T15:00:00Z", "outcome": "suppressed_ok", "duration_ms": 800, "tokens_in": 450, "tokens_out": 15, "active_tasks": 0}
{"timestamp": "2026-02-17T15:30:00Z", "outcome": "skipped_preflight", "reason": "empty_heartbeat_no_tasks"}
```

---

## Best Practices

### Design idempotent prompts

Cron jobs and heartbeats run independently each time. Design prompts that work correctly regardless of when they last ran:

```yaml
# Good: reads current state from a file
prompt: |
  Review HEARTBEAT.md for active projects.
  Generate a status update based on current state.

# Avoid: assumes continuity from last run
prompt: |
  Continue from where we left off yesterday.
```

### Use conditional output to reduce noise

Not every scheduled run needs to send a message. Instruct the agent to stay silent when there is nothing worth reporting:

```yaml
prompt: |
  Check for urgent items in workspace files.

  If urgent items exist, report them.
  If everything is normal, do not send a message.
```

For heartbeats, the `HEARTBEAT_OK` protocol handles this automatically when `suppress_ok: true`.

### Use filesystem for shared state

Cron jobs can pass data to each other or to the main agent via workspace files:

```yaml
prompt: |
  Read metrics/daily-stats.md for historical data.
  Append today's statistics.
  Generate a trend analysis if the data shows anomalies.
```

### Prefer heartbeats for ongoing monitoring

For continuous task monitoring, heartbeats are more efficient than high-frequency crons. Heartbeats have pre-flight skipping, task summary injection, and `HEARTBEAT_OK` suppression built in:

```yaml
# Instead of a cron running every 5 minutes:
# crons/check-tasks.yaml with schedule: "*/5 * * * *"

# Use a heartbeat:
heartbeat:
  enabled: true
  interval_minutes: 5
  active_hours: "09:00-17:00"
  suppress_ok: true
```

### Test before scheduling

Set the schedule to run in 2 minutes while developing, verify the output, then switch to the production schedule:

```yaml
schedule: "*/2 * * * *"  # Temporary: every 2 minutes for testing
enabled: true
```

---

## Troubleshooting

### Cron job not executing

- Verify `enabled: true` in the YAML file
- Check the cron expression syntax at [crontab.guru](https://crontab.guru)
- Confirm the workspace is running: `poetry run openpaw -c config.yaml -w my-agent`
- Run with verbose logging to see scheduler output: `poetry run openpaw -c config.yaml -w my-agent -v`
- Confirm the workspace timezone is set correctly in `agent.yaml`

### Cron executes but produces no output

- Verify `chat_id` is correct in the cron YAML file
- Check channel configuration in `config.yaml`
- The agent may have decided not to send a message based on the prompt logic — review the session log in `memory/sessions/cron/`
- Check verbose logs for delivery errors

### Output goes to the wrong chat

- Verify `output.chat_id` in the cron YAML file
- Telegram group IDs are negative numbers (e.g., `-1001234567890`); user IDs are positive
- Confirm `output.channel` matches the workspace channel type

### Heartbeats not firing

- Confirm `heartbeat.enabled: true` in `agent.yaml`
- Check that the current time (in workspace timezone) falls within the `active_hours` window
- Check `heartbeat_log.jsonl` for skip reasons — `skipped_preflight` means HEARTBEAT.md is empty and no active tasks exist
- Add content to `HEARTBEAT.md` or create an active task to trigger heartbeat execution

### Timezone issues

- Confirm `timezone` is set in `agent.yaml` using a valid IANA identifier
- Schedules fire in the workspace timezone, not the server's system timezone
- Check `heartbeat_log.jsonl` timestamps to verify when heartbeats are actually firing

### Dynamic tasks not persisting after restart

- Confirm `builtins.cron.enabled: true` in configuration
- Tasks persist to a JSON file in the workspace — check file system permissions
- Run with verbose logging and look for persistence errors at startup
