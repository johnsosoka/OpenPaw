# Queue System

OpenPaw implements a sophisticated lane-based queuing system that enables responsive, context-aware message handling for AI agents. The queue system supports multiple processing modes, per-session isolation, and middleware-driven responsiveness.

## Architecture

The queue system is implemented in two core components:

- **`openpaw/core/queue/lane.py`** - `LaneQueue` provides lane-based FIFO queuing with configurable concurrency
- **`openpaw/core/queue/manager.py`** - `QueueManager` coordinates message routing, debouncing, and queue mode behavior

Each workspace maintains its own isolated queue system with three lanes:

- **main** - User messages from the primary communication channel
- **subagent** - Sub-agent completion notifications and results
- **cron** - Scheduled tasks and heartbeat events

## Session Key Format

Session keys uniquely identify conversation participants using the format `"channel:id"`:

- Telegram user: `"telegram:123456"`
- Telegram group: `"telegram:-987654321"`

Session keys are used for:
- Queue isolation (each session has its own queue)
- Conversation thread tracking
- Channel message routing

## Queue Modes

OpenPaw supports four queue modes that control how messages are batched and how the agent responds to new messages during execution.

### collect (Default)

**Behavior**: Messages are gathered briefly before processing. The debounce timer (`debounce_ms`) allows rapid successive messages to be batched together.

**Middleware**: None. Messages queue normally and are processed after the current agent run completes.

**Use Case**: Batch rapid messages from users who send thoughts in multiple quick messages. Reduces redundant agent invocations.

**Configuration**:
```yaml
queue:
  mode: collect
  debounce_ms: 1000  # Wait 1 second for additional messages
```

**Example**:
```
00:00.000 - User: "Here's what I need"
00:00.200 - User: "First, update the docs"
00:00.400 - User: "Then run the tests"
00:01.000 - Agent processes all three messages together
```

### steer

**Behavior**: When pending messages are detected DURING tool execution, remaining tools are skipped and new messages are injected as the next agent input. The agent sees `[Skipped: user sent new message — redirecting]` for skipped tools and processes the new message context.

**Middleware**: `QueueAwareToolMiddleware` checks for pending messages before each tool execution. On first detection, calls `queue_manager.consume_pending()` and stores messages for post-run injection.

**Use Case**: Responsive conversations where users frequently change direction mid-task. The agent redirects at tool boundaries rather than completing the original workflow.

**Important**: This is NOT "cancel current work" — it redirects at tool boundaries. Already-executed tools complete normally. Only remaining tools are skipped.

**Configuration**:
```yaml
queue:
  mode: steer
```

**Runtime Command**: Users can switch modes at runtime:
```
/queue steer
```

**Example**:
```
00:00.000 - User: "Write a function to parse JSON"
00:00.500 - Agent starts working, calls file tools...
00:02.000 - User: "Actually, make it parse YAML instead"
00:02.001 - Agent skips remaining JSON tools, processes YAML request
```

### interrupt

**Behavior**: When pending messages are detected, the current tool raises `InterruptSignalError`, the agent's response is discarded, and the new message is processed immediately. More aggressive than steer — aborts mid-run rather than redirecting.

**Middleware**: `QueueAwareToolMiddleware` raises `InterruptSignalError` on first pending message detection.

**Use Case**: Only the latest message matters. Conversations where users rapidly iterate and previous agent work becomes obsolete.

**Configuration**:
```yaml
queue:
  mode: interrupt
```

**Runtime Command**:
```
/queue interrupt
```

**Example**:
```
00:00.000 - User: "Show me sales data"
00:00.500 - Agent starts query...
00:01.000 - User: "Wait, show revenue instead"
00:01.500 - User: "Actually, show profit margins"
00:01.501 - Agent aborts, processes only "profit margins"
```

### followup

**Behavior**: Sequential processing with no middleware behavior. Reserved for followup tool chaining (when agents use `request_followup` to continue multi-step workflows).

**Middleware**: None. Messages are processed in strict order.

**Use Case**: Multi-step autonomous workflows where the agent needs predictable sequential execution.

**Configuration**:
```yaml
queue:
  mode: followup
```

**Runtime Command**:
```
/queue followup
```

**Example**:
```
00:00.000 - User: "Deploy to staging"
00:00.500 - Agent starts deployment...
00:01.000 - User: "Then run smoke tests"
00:03.000 - Deployment completes, agent starts smoke tests
```

## Queue Mode Comparison

| Mode | Debounce | Middleware Behavior | Use Case |
|------|----------|-------------------|----------|
| collect | Yes | None | Batch rapid messages |
| steer | No | Redirects at tool boundary | Responsive conversations |
| followup | No | None | Sequential workflows |
| interrupt | No | Aborts mid-run | Only latest message matters |

## Queue-Aware Tool Middleware

The `QueueAwareToolMiddleware` (`openpaw/agent/middleware/queue_aware.py`) enables responsive agent behavior by checking for pending user messages during tool execution.

### How It Works

1. **Before Each Tool**: Middleware calls `queue_manager.peek_pending(session_key)` to check for new messages
2. **Check Scope**: `peek_pending()` checks BOTH the session's pre-debounce buffer AND the lane queue (steer-mode messages bypass the session buffer)
3. **Steer Mode**: On first detection, triggers `queue_manager.consume_pending()` and stores messages for post-run injection
4. **Interrupt Mode**: On detection, raises `InterruptSignalError` immediately

### Post-Run Detection

After the agent run completes, `_process_messages()` performs a final `peek_pending()` check to catch messages that arrived after the last tool call (or during tool-free runs). This ensures steer/interrupt responsiveness even when the middleware didn't fire.

### Middleware Composition

The middleware composes with approval middleware in agent creation:

```python
create_agent(middleware=[queue_middleware, approval_middleware])
```

### Integration Points

**WorkspaceRunner**:
- Captures steer state before middleware reset via local variables
- Catches `InterruptSignalError` in `_process_messages()`
- Re-enters processing loop with pending messages as new content

**AgentRunner**:
- Propagates `ApprovalRequiredError` and `InterruptSignalError` without catching
- Middleware has access to full agent execution context

## Per-Session Queuing

Each conversation session maintains its own isolated queue. This ensures:

- Messages from different users don't interfere with each other
- Each user experiences consistent queue mode behavior
- Debouncing is per-session (one user's rapid messages don't delay another's)

**Example**:
```
User A (session: telegram:123456)  → Queue A → Agent
User B (session: telegram:789012)  → Queue B → Agent
```

Both users can interact with the same workspace simultaneously, each with their own queue and conversation context.

## Lane Concurrency

Each lane has configurable concurrency limits:

```yaml
queue:
  lanes:
    main:
      concurrency: 1      # Process one user message at a time
    subagent:
      concurrency: 8      # Allow 8 concurrent sub-agent workers
    cron:
      concurrency: 3      # Allow 3 concurrent scheduled tasks
```

**Default Behavior**: Main lane uses strict serialization (concurrency: 1) to ensure conversation coherence. Sub-agent and cron lanes allow higher concurrency for parallel background work.

## Changing Queue Mode at Runtime

Users can change queue mode without restarting the workspace using the `/queue` command:

```
/queue collect
/queue steer
/queue interrupt
/queue followup
```

The change takes effect immediately for the next message. Current agent runs continue with their original mode.

## Configuration Examples

### Basic Configuration (Global)

```yaml
queue:
  mode: collect
  debounce_ms: 1000
  lanes:
    main:
      concurrency: 1
    subagent:
      concurrency: 8
    cron:
      concurrency: 3
```

### Workspace Override

```yaml
# agent_workspaces/assistant/agent.yaml
name: Assistant
description: Helpful assistant

queue:
  mode: steer  # Override to steer mode for this workspace
```

### Responsive Customer Service Agent

```yaml
# High responsiveness for customer service
queue:
  mode: steer
  debounce_ms: 0  # No debounce in steer mode
```

### Research Agent

```yaml
# Deep work mode, less interruption
queue:
  mode: collect
  debounce_ms: 3000  # Allow longer batching for multi-message research requests
```

### Sequential Task Processor

```yaml
queue:
  mode: followup  # Process in order
  lanes:
    main:
      concurrency: 1  # One task at a time
```

## Best Practices

### Choose the Right Mode

- **collect**: Default for most agents. Good balance of responsiveness and batching.
- **steer**: Use for conversational agents where users frequently change topics.
- **interrupt**: Use sparingly. Only for scenarios where agent work becomes immediately obsolete.
- **followup**: Framework-managed. Don't set manually unless you understand the implications.

### Debounce Timing

- **Short (500-1000ms)**: Responsive customer service, real-time assistance
- **Medium (1000-2000ms)**: General-purpose agents, balanced batching
- **Long (3000-5000ms)**: Research agents, long-form content, users who send many quick messages

### Lane Concurrency

- **Main lane**: Almost always keep at 1 for conversation coherence
- **Subagent lane**: Match your `builtins.spawn.config.max_concurrent` setting
- **Cron lane**: Based on number of scheduled tasks and desired parallelism

### Mode Switching

Users can experiment with modes using `/queue <mode>`. Monitor token usage (via `/status`) to see if batching is reducing redundant invocations.

## Integration with Other Systems

### Approval Gates

Approval gates work across all queue modes. When waiting for user approval:
- New messages queue normally
- On approval, agent resumes with original message
- On denial, agent receives system notification and can process queued messages

### Sub-Agent Notifications

Sub-agent completion notifications are injected using `QueueMode.COLLECT`:
- Notifications bypass the session pre-debounce buffer
- Always trigger a new agent turn
- Work consistently across all user-facing queue modes

### Conversation Resets

Commands like `/new` and `/compact` bypass the queue entirely to ensure immediate execution.

## Troubleshooting

### Agent Not Responding to New Messages

**Symptom**: User sends new message while agent is working, but agent ignores it.

**Check**:
1. Queue mode is set to `steer` or `interrupt` (not `collect`)
2. Middleware is properly initialized in agent factory
3. Post-run detection is active in message processor

### Messages Processing Out of Order

**Symptom**: Messages arrive in wrong order or get skipped.

**Check**:
1. Lane concurrency for main lane should be 1
2. Session keys are consistent (not changing mid-conversation)
3. Debounce timing is appropriate for use case

### Too Many Agent Invocations

**Symptom**: Agent triggers for every message in rapid succession.

**Check**:
1. Queue mode is `collect` (not `interrupt`)
2. `debounce_ms` is set appropriately (1000-3000ms)
3. Users understand batching behavior

## Technical Details

### Message Flow

```
Channel Message Arrival
    ↓
QueueManager.submit()
    ↓
Session Pre-Debounce Buffer (collect mode only)
    ↓
Debounce Timer Expires
    ↓
LaneQueue (main/subagent/cron)
    ↓
Lane Concurrency Semaphore
    ↓
WorkspaceRunner._process_messages()
    ↓
QueueAwareToolMiddleware (during agent run)
    ↓
peek_pending() → consume_pending() (steer mode)
    ↓
Post-Run Detection
    ↓
Message Processing Complete
```

### State Management

**Steer State Capture**: `WorkspaceRunner` uses local variables to capture steer state before middleware reset:

```python
# Before middleware reset (in finally block)
has_steered = self.queue_middleware.has_steered()
pending = self.queue_middleware.get_pending_messages()

# After middleware reset, state is restored from local vars
```

This ensures steer state survives the middleware cleanup that happens in the `finally` block.

### peek_pending() Behavior

`peek_pending()` checks two locations for pending messages:

1. **Session pre-debounce buffer**: Messages waiting for debounce timer (collect mode)
2. **Lane queue**: Messages already in the lane queue (steer messages bypass buffer)

This dual-check ensures responsiveness across all queue modes and timing scenarios.

## Future Enhancements

Potential improvements under consideration:

- **Priority lanes**: High-priority messages jump the queue
- **Context-aware mode switching**: Agent automatically adjusts mode based on task
- **Queue depth metrics**: Expose queue length and processing latency via `/status`
- **Backpressure handling**: Graceful degradation under high message volume
