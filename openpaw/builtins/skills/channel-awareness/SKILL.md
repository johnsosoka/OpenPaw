---
name: channel-awareness
description: Channel message history browsing, persistent JSONL log searching, and message lookup patterns
inject: summary
---

# Channel Awareness

## Channel History Browsing

Use `browse_channel_history` to fetch recent messages from channels. This tool
queries the platform API (Discord, Telegram) for real-time message history.

### Usage Patterns

- Browse recent messages: `browse_channel_history(channel_name="general")`
- Filter by user: `browse_channel_history(channel_name="general", user_filter="John")`
- Pagination: use `before_id` from results to fetch older messages

## Persistent Channel Logs

When channel logging is enabled, all visible channel messages are saved to
daily JSONL files. These logs are persistent and searchable via filesystem tools.

### Log Location

```
memory/logs/channel/{server}/{channel}/{YYYY-MM-DD}.jsonl
```

### JSONL Record Format

Each line contains: `ts` (UTC timestamp), `msg_id`, `user_id`, `display_name`,
`content`, `attachments` (list).

### Searching Logs

Search for keywords across all logs:
```
grep_files('search term', glob='memory/logs/channel/**/*.jsonl')
```

Read a specific day's messages:
```
read_file('memory/logs/channel/server-name/channel-name/2026-03-07.jsonl')
```

### History vs Logs

- **History** (`browse_channel_history`): Real-time platform API query for recent messages
- **Logs** (`memory/logs/channel/`): Persistent JSONL archive of all witnessed messages

Logs are read-only — the agent cannot modify them.
