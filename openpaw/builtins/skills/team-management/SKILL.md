---
name: team-management
description: Sub-agent spawning patterns, lifecycle communication, and team profile building for concurrent work delegation
inject: summary
---

# Team Management

## Sub-Agent Spawning

You can spawn background sub-agents to work on tasks concurrently while
you continue interacting with the user. Sub-agents are independent workers
that share your workspace filesystem but run in isolated contexts.

### Proactive Delegation

Consider spawning sub-agents on your own initiative when:
- The user's request has multiple independent components that can be
  researched or processed in parallel
- A task would take significant time and you can work on something else concurrently
- You need to gather information from multiple sources before synthesizing a response

When you spawn sub-agents proactively, always tell the user what you are
delegating and why. Do not silently spawn background work.

### Sub-Agent Lifecycle Communication

1. Tell the user when you spawn a sub-agent and what it will do
2. When a sub-agent completes, retrieve its result and summarize findings
   to the user — do not let completions pass silently
3. If a sub-agent fails or times out, inform the user and explain next steps

When a sub-agent completion notification arrives, always retrieve the result
with `get_subagent_result`, take follow-up action if needed, and inform the user.

### Team Profiles

Your workspace may define spawn profiles — named configurations for specialized
sub-agents. Use `list_team_profiles` to see available profiles and
`spawn_agent(profile='name')` to use one. Profiles provide focused system prompts,
tool restrictions, and model overrides for cost or capability optimization.
When a profile fits the task, prefer it over manual tool filtering.
