# Cron Scheduler

OpenPaw supports scheduled tasks (cron jobs) per workspace. Cron jobs execute prompts at specified intervals and route output to configured channels.

## Overview

Each workspace can define scheduled tasks via YAML files in the `crons/` directory. The scheduler uses [APScheduler](https://apscheduler.readthedocs.io/) to execute jobs based on standard cron expressions.

## Cron File Format

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

## Configuration Fields

### name

Unique identifier for this cron job.

```yaml
name: weekly-report
```

Used in logs and for job management. Must be unique within the workspace.

### schedule

Standard cron expression: `"minute hour day-of-month month day-of-week"`

```yaml
schedule: "0 9 * * *"  # Daily at 9:00 AM
```

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

#### Common Schedules

**Every 15 minutes:**
```yaml
schedule: "*/15 * * * *"
```

**Every hour:**
```yaml
schedule: "0 * * * *"
```

**Daily at 9 AM:**
```yaml
schedule: "0 9 * * *"
```

**Weekdays at 9 AM:**
```yaml
schedule: "0 9 * * 1-5"
```

**Weekly on Monday at 8 AM:**
```yaml
schedule: "0 8 * * 1"
```

**First day of month at midnight:**
```yaml
schedule: "0 0 1 * *"
```

**Every Sunday at midnight:**
```yaml
schedule: "0 0 * * 0"
```

### enabled

Enable or disable the cron job without deleting the file.

```yaml
enabled: true   # Job will run
enabled: false  # Job is skipped
```

Useful for temporarily disabling jobs during maintenance or testing.

### prompt

The prompt to send to the agent when the cron job executes.

```yaml
prompt: |
  Review the current state of all projects.
  Generate a status report including:
  - Active projects
  - Completed tasks this week
  - Pending items
  - Any blockers
```

The prompt is injected into a fresh agent instance. The agent has access to:
- All workspace markdown files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
- Workspace filesystem (can read/write files)
- All enabled builtins (search, TTS, etc.)

### output

Defines where the cron job's response is sent.

```yaml
output:
  channel: telegram
  chat_id: 123456789  # Send to specific user/group
```

**channel** - Channel type (`telegram`, etc.)

**chat_id** - Platform-specific identifier:
- Telegram user ID (positive integer)
- Telegram group ID (negative integer starting with -100)

To get a Telegram chat ID:
- User ID: Message [@userinfobot](https://t.me/userinfobot)
- Group ID: Add [@RawDataBot](https://t.me/RawDataBot) to group

## Example Cron Jobs

### Daily Status Report

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

### Weekly Summary

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
schedule: "0 18 * * 1-5"  # Weekdays at 6 PM
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

## Cron Execution Model

### Fresh Agent Instance

Each cron execution creates a fresh agent instance:
- **No conversation history** - Each run is independent
- **No checkpointer** - State is not persisted between runs
- **Clean context** - No accumulated conversation memory

This ensures cron jobs execute consistently without interference from previous runs.

### Filesystem Persistence

Cron jobs can read and write workspace files:

```yaml
prompt: |
  Read notes/daily-logs.md to see recent activity.
  Append today's summary to the log file.
  Send the summary via chat.
```

The agent has full filesystem access to its workspace directory, enabling:
- Reading previous cron outputs
- Updating shared state files
- Maintaining persistent logs

### Builtin Access

Cron jobs have access to all enabled builtins:

```yaml
prompt: |
  Use brave_search to check for news about our key technologies.
  Summarize any important updates and send via chat.
```

Builtins are configured in the workspace's `agent.yaml` or global `config.yaml`.

## Cron Job Best Practices

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

Cron schedules run in the system timezone. Document the expected timezone:

```yaml
name: daily-report
schedule: "0 9 * * *"  # 9 AM Pacific Time (server timezone)
enabled: true
```

Or specify timezone in the prompt:

```yaml
prompt: |
  Generate a report for the Pacific Time (PT) business day.
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

Each workspace's crons run in isolation with that workspace's agent configuration.

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

## Advanced Usage

### Dynamic Scheduling

Cron jobs can update their own schedules by modifying workspace files:

```yaml
prompt: |
  Review current workload in HEARTBEAT.md.

  If workload is high, note that daily reports should pause.
  Update crons/daily-report.yaml to set enabled: false.
```

Requires careful design to avoid unintended behavior.

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

## Troubleshooting

**Cron not executing:**
- Verify `enabled: true`
- Check cron expression syntax
- Ensure workspace is running (`poetry run openpaw -w <workspace>`)
- Check logs for scheduler errors

**Cron executes but no output:**
- Verify `chat_id` is correct
- Check channel configuration
- Agent may have decided not to send a message (check prompt logic)

**Cron output goes to wrong chat:**
- Verify `chat_id` in cron YAML
- Check for typos (positive vs. negative for groups)

**Timezone issues:**
- Cron runs in system timezone
- Check server timezone: `date` or `timedatectl`
- Adjust schedule accordingly or set system timezone

**Filesystem errors:**
- Cron jobs have sandboxed access to workspace directory only
- Cannot access files outside workspace
- Check file paths are relative to workspace root
