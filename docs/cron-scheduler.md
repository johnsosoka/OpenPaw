# Cron Scheduler

OpenPaw supports both static and dynamic scheduled tasks per workspace. Static tasks are defined via YAML files in the `crons/` directory, while dynamic tasks can be scheduled by agents at runtime using the CronTool builtin.

## Architecture

The scheduling system consists of three core components:

- **`openpaw/runtime/scheduling/cron.py`** - `CronScheduler` executes scheduled tasks using APScheduler
- **`openpaw/runtime/scheduling/heartbeat.py`** - `HeartbeatScheduler` for proactive agent check-ins
- **`openpaw/runtime/scheduling/dynamic_cron.py`** - `DynamicCronStore` for agent-scheduled tasks

All cron schedules fire in the **workspace timezone** (IANA identifier from `agent.yaml`, default: UTC).

## Static Cron Jobs

Create YAML files in `agent_workspaces/<workspace>/crons/<job-name>.yaml`:

```yaml
name: daily-summary
schedule: "0 9 * * *"  # Standard cron format
enabled: true

prompt: |
  Generate a daily summary by reviewing workspace files.
  Include: active projects, completed tasks, blockers.

output:
  channel: telegram
  chat_id: 123456789  # Platform-specific routing
```

### Configuration Fields

**name** - Unique identifier for this cron job (must be unique within the workspace)

**schedule** - Standard cron expression: `"minute hour day-of-month month day-of-week"`

Cron Expression Format:
```
 ┌───────────── minute (0 - 59)
 │ ┌───────────── hour (0 - 23)
 │ │ ┌───────────── day of month (1 - 31)
 │ │ │ ┌───────────── month (1 - 12)
 │ │ │ │ ┌───────────── day of week (0 - 6) (Sunday to Saturday)
 │ │ │ │ │
 * * * * *
```

Common Schedules:
- `"*/15 * * * *"` - Every 15 minutes
- `"0 * * * *"` - Every hour
- `"0 9 * * *"` - Daily at 9:00 AM (workspace timezone)
- `"0 9 * * 1-5"` - Weekdays at 9:00 AM
- `"0 8 * * 1"` - Weekly on Monday at 8:00 AM
- `"0 0 1 * *"` - First day of month at midnight
- `"0 0 * * 0"` - Every Sunday at midnight

**enabled** - Enable or disable the cron job without deleting the file

**prompt** - The prompt to send to the agent when the cron job executes

**output** - Defines where the cron job's response is sent

```yaml
output:
  channel: telegram
  chat_id: 123456789  # Telegram user ID or group ID
```

To get a Telegram chat ID:
- User ID: Message [@userinfobot](https://t.me/userinfobot)
- Group ID: Add [@RawDataBot](https://t.me/RawDataBot) to group

### Timezone Behavior

**Critical**: Cron schedules fire in the **workspace timezone**, not the system timezone.

Configure workspace timezone in `agent.yaml`:

```yaml
timezone: America/Denver  # IANA timezone identifier

# Cron schedules interpret times in this timezone
# "0 9 * * *" = 9:00 AM Denver time
```

Default timezone is UTC if not specified.

## Dynamic Scheduling (CronTool)

Agents can schedule their own follow-up actions at runtime using the CronTool builtin. This enables autonomous workflows like "remind me in 20 minutes" or "check on this PR every hour".

### Available Tools

**schedule_at** - Schedule a one-time action at a specific timestamp

```python
# Agent usage example:
schedule_at(
    prompt="Check if the deploy has completed",
    fire_at="2026-02-17T14:30:00",  # ISO format
    label="deploy-check"
)
```

**schedule_every** - Schedule a recurring action at fixed intervals

```python
# Agent usage example:
schedule_every(
    prompt="Check PR status and notify if merged",
    interval_seconds=3600,  # Every hour
    label="pr-monitor"
)
```

**list_scheduled** - List all pending scheduled tasks

**cancel_scheduled** - Cancel a scheduled task by ID

### Storage and Lifecycle

- Tasks persist to `{workspace}/dynamic_crons.json` and survive restarts
- One-time tasks are automatically cleaned up after execution
- Expired one-time tasks are cleaned up on workspace startup
- Recurring tasks continue until explicitly cancelled

### Routing

Responses are sent back to the first allowed user in the workspace's channel config.

### Configuration

Optional configuration in `agent.yaml` or global config:

```yaml
builtins:
  cron:
    enabled: true
    config:
      min_interval_seconds: 300  # Minimum interval for recurring tasks (default: 5 min)
      max_tasks: 50              # Maximum pending tasks per workspace
```

### Example Usage

**User**: "Ping me in 10 minutes to check on the deploy"

**Agent**: Calls `schedule_at` with timestamp 10 minutes from now

**Result**: Task fires at scheduled time, agent sends reminder to user's chat

## Heartbeat System

The HeartbeatScheduler enables proactive agent check-ins on a configurable schedule. Agents can use this to monitor ongoing tasks, provide status updates, or maintain context without user prompts.

### Configuration

In `agent.yaml`:

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30           # How often to check in
  active_hours: "09:00-17:00"    # Only run during these hours (optional)
  suppress_ok: true              # Don't send message if agent responds "HEARTBEAT_OK"
  output:
    channel: telegram
    chat_id: 123456789
```

### HEARTBEAT_OK Protocol

If the agent determines there's nothing to report, it can respond with exactly `"HEARTBEAT_OK"` and no message will be sent (when `suppress_ok: true`). This prevents noisy "all clear" messages.

### Active Hours

Heartbeats only fire within the specified window (workspace timezone). Outside active hours, heartbeats are silently skipped.

**Important**: `active_hours` are interpreted in the workspace timezone. For example, `"09:00-17:00"` with `timezone: America/Denver` means 9:00 AM - 5:00 PM Denver time.

### Pre-flight Skip

Before invoking the LLM, the scheduler checks HEARTBEAT.md and TASKS.yaml:

- If HEARTBEAT.md is empty or trivial
- AND no active tasks exist
- THEN skip the heartbeat entirely (saves API costs for idle workspaces)

### Task Summary Injection

When active tasks exist, a compact summary is automatically injected into the heartbeat prompt as `<active_tasks>` XML tags. This avoids an extra LLM tool call to `list_tasks()`.

### Event Logging

Every heartbeat event is logged to `{workspace}/heartbeat_log.jsonl` with:
- Outcome (sent, suppressed, skipped)
- Duration
- Token metrics (input/output tokens)
- Active task count

### HEARTBEAT.md

The `HEARTBEAT.md` file serves as a scratchpad for agent-maintained notes on what to check during heartbeats. The agent can update this file with reminders, ongoing work, or things to monitor.

Example HEARTBEAT.md:

```markdown
# Current Focus

- Monitoring PR #123 for merge conflicts
- Waiting on deployment approval from ops team
- Need to follow up on database migration at 3 PM

# Recent Updates

2026-02-17: Started monitoring the staging deploy
2026-02-16: Completed code review for auth refactor
```

The heartbeat scheduler reads this file and includes it in the agent's context during each heartbeat execution.

## Cron Execution Model

### Fresh Agent Instance

Each cron execution (static, dynamic, or heartbeat) creates a fresh agent instance:

- **No conversation history** - Each run is independent
- **No checkpointer** - State is not persisted between runs
- **Clean context** - No accumulated conversation memory
- **Stateless by design** - Ensures consistent, predictable execution

This ensures cron jobs execute consistently without interference from previous runs or user conversations.

### Filesystem Access

Cron jobs have full filesystem access to the workspace directory:

```yaml
prompt: |
  Read notes/daily-logs.md to see recent activity.
  Append today's summary to the log file.
  Send the summary via chat.
```

The agent can:
- Read previous cron outputs
- Update shared state files
- Maintain persistent logs
- Organize workspace directories

### Builtin Access

Cron jobs have access to all enabled builtins (brave_search, task_tracker, send_message, etc.), configured in the workspace's `agent.yaml` or global `config.yaml`.

Example:

```yaml
prompt: |
  Use brave_search to check for news about our key technologies.
  Summarize any important updates and send via chat.
```

## Example Static Cron Jobs

### Daily Status Report

```yaml
name: daily-status
schedule: "0 9 * * 1-5"  # Weekdays at 9 AM (workspace timezone)
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

### Weekly Summary

```yaml
name: weekly-summary
schedule: "0 9 * * 1"  # Monday at 9 AM (workspace timezone)
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

### Hourly Health Check

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

### End-of-Day Cleanup

```yaml
name: end-of-day
schedule: "0 18 * * 1-5"  # Weekdays at 6 PM (workspace timezone)
enabled: true

prompt: |
  End-of-day cleanup:

  1. Review HEARTBEAT.md and update status
  2. Move completed tasks to an archive section
  3. Summarize remaining work for tomorrow
  4. Send summary

output:
  channel: telegram
  chat_id: 123456789
```

### Monthly Report

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

## Example Dynamic Scheduling Scenarios

### Time-Based Reminder

**User**: "Remind me to check the server logs in 30 minutes"

**Agent**: Calls `schedule_at(prompt="Reminder: check server logs", fire_at="2026-02-17T15:00:00", label="log-check")`

### Recurring Monitoring

**User**: "Check on PR #456 every hour until it's merged"

**Agent**: Calls `schedule_every(prompt="Check PR #456 status and notify if merged", interval_seconds=3600, label="pr-456-monitor")`

**Later**: User says "Stop monitoring the PR"

**Agent**: Calls `list_scheduled()` to find the task ID, then `cancel_scheduled(task_id="...")`

## Best Practices

### 1. Idempotent Prompts

Design prompts to work regardless of when they last ran:

```yaml
# Good: References HEARTBEAT.md state
prompt: |
  Review HEARTBEAT.md for active projects.
  Generate a status update.

# Avoid: Assumes state from previous run
prompt: |
  Continue from where we left off yesterday.
```

### 2. Conditional Output

Not every cron should send output:

```yaml
prompt: |
  Check for urgent items in workspace files.

  If urgent items exist, report them immediately.
  Otherwise, stay silent (no message needed).
```

Prevents notification spam for routine checks.

### 3. Use Filesystem for State

Share state across cron runs via files:

```yaml
prompt: |
  Read metrics/daily-stats.md for historical data.
  Append today's statistics.
  Generate a trend analysis if data shows anomalies.
```

### 4. Timezone Awareness

Always configure workspace timezone explicitly:

```yaml
# agent.yaml
timezone: America/New_York

# Cron schedules now interpret in Eastern Time
# "0 9 * * *" = 9:00 AM Eastern
```

Document the expected timezone in prompts for clarity:

```yaml
prompt: |
  Generate a report for the Eastern Time (ET) business day.
```

### 5. Error Handling

Cron jobs should handle missing files gracefully:

```yaml
prompt: |
  Try to read data/metrics.md.
  If the file doesn't exist, note this and create a placeholder.
  Otherwise, process the data normally.
```

### 6. Test Before Scheduling

Test cron prompts manually before scheduling:

```yaml
# Temporarily set to run in 2 minutes for testing
schedule: "*/2 * * * *"
enabled: true
```

Verify output, then adjust to production schedule.

### 7. Use Heartbeats for Monitoring

For ongoing task monitoring, prefer heartbeats over frequent crons:

```yaml
# Instead of:
# crons/check-tasks.yaml with schedule: "*/5 * * * *"

# Use:
heartbeat:
  enabled: true
  interval_minutes: 5
  active_hours: "09:00-17:00"
  suppress_ok: true
```

Heartbeats have pre-flight skipping and task summary injection, making them more efficient for monitoring workloads.

## Managing Cron Jobs

### Disable Without Deleting

```yaml
enabled: false  # Job is skipped but definition preserved
```

Useful for:
- Temporary maintenance periods
- Seasonal schedules (quarterly reports, etc.)
- Testing alternative approaches

### Multiple Jobs per Workspace

Create multiple YAML files in `crons/`:

```
agent_workspaces/my-agent/crons/
├── daily-summary.yaml
├── weekly-report.yaml
├── health-check.yaml
└── monthly-metrics.yaml
```

All enabled jobs run independently.

### Per-Workspace vs. Global Crons

Crons are workspace-scoped:

```
workspace1/crons/report.yaml  → Runs in workspace1 context
workspace2/crons/report.yaml  → Runs in workspace2 context (independent)
```

Each workspace's crons run in isolation with that workspace's agent configuration, timezone, and filesystem access.

## Monitoring Cron Jobs

Enable verbose logging to monitor cron execution:

```bash
poetry run openpaw -c config.yaml -w my-agent -v
```

Logs show:
- Cron job startup and schedule registration
- Job execution triggers
- Agent responses
- Message delivery status
- Errors or failures

For heartbeats, check `heartbeat_log.jsonl` for detailed event history:

```json
{"timestamp": "2026-02-17T14:30:00Z", "outcome": "sent", "duration_ms": 1234, "tokens_in": 500, "tokens_out": 150, "active_tasks": 3}
{"timestamp": "2026-02-17T15:00:00Z", "outcome": "suppressed_ok", "duration_ms": 800, "tokens_in": 450, "tokens_out": 15, "active_tasks": 0}
{"timestamp": "2026-02-17T15:30:00Z", "outcome": "skipped_preflight", "reason": "empty_heartbeat_no_tasks"}
```

## Advanced Usage

### Multi-Channel Output

Route different crons to different channels:

```yaml
# crons/team-update.yaml
output:
  channel: telegram
  chat_id: -1001234567890  # Team group

# crons/personal-reminder.yaml
output:
  channel: telegram
  chat_id: 123456789  # Personal DM
```

### Cron Chains

Use filesystem to coordinate multiple crons:

```yaml
# crons/collect-data.yaml
schedule: "0 8 * * *"  # 8 AM
prompt: |
  Collect daily metrics and save to data/latest.md

# crons/process-data.yaml
schedule: "0 9 * * *"  # 9 AM (1 hour later)
prompt: |
  Read data/latest.md and generate analysis report
```

### Dynamic Task Management

Agents can manage their own scheduled tasks:

**User**: "Schedule a daily standup reminder at 9 AM"

**Agent**: Calls `schedule_every(prompt="Reminder: daily standup at 9 AM", interval_seconds=86400, label="standup")`

**Later, User**: "Cancel the standup reminder"

**Agent**: Calls `list_scheduled()`, finds the task, calls `cancel_scheduled(task_id="...")`

## Troubleshooting

### Cron not executing

**Check**:
- Verify `enabled: true` in the YAML file
- Check cron expression syntax (use [crontab.guru](https://crontab.guru))
- Ensure workspace is running (`poetry run openpaw -w <workspace>`)
- Check logs for scheduler errors
- Verify timezone is configured correctly

### Cron executes but no output

**Check**:
- Verify `chat_id` is correct
- Check channel configuration
- Agent may have decided not to send a message (check prompt logic)
- Look for errors in verbose logs

### Cron output goes to wrong chat

**Check**:
- Verify `chat_id` in cron YAML
- Check for typos (positive vs. negative for groups)
- Ensure output.channel matches workspace channel type

### Timezone issues

**Check**:
- Workspace timezone is set in `agent.yaml`
- Cron schedules fire in workspace timezone, not system timezone
- Use `workspace_now()` utility for debugging (check logs)
- Verify IANA timezone identifier is valid

### Heartbeats not firing

**Check**:
- `heartbeat.enabled: true` in agent.yaml
- Current time is within `active_hours` window (workspace timezone)
- HEARTBEAT.md has content or active tasks exist (otherwise pre-flight skip)
- Check `heartbeat_log.jsonl` for skip reasons

### Filesystem errors

**Check**:
- Cron jobs have sandboxed access to workspace directory only
- Cannot access files outside workspace
- Check file paths are relative to workspace root (not absolute)
- `.openpaw/` directory is protected (framework internals)

### Dynamic tasks not persisting

**Check**:
- `builtins.cron.enabled: true` in configuration
- Tasks are saved to `dynamic_crons.json` in workspace root
- File permissions allow writing
- Check logs for persistence errors
