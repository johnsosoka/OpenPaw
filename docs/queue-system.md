# Queue System

OpenPaw uses a lane-based FIFO queue system inspired by OpenClaw. The queue manages how messages are collected, prioritized, and processed by agents.

## Architecture

```
Channel → QueueManager → LaneQueue → AgentRunner
                ├─ main_lane (user messages)
                ├─ subagent_lane (delegated tasks)
                └─ cron_lane (scheduled jobs)
```

Each workspace has its own queue manager with three lanes. Lanes enable different concurrency limits and prioritization for different message types.

## Queue Modes

The `mode` setting controls how messages are queued and processed.

### collect (default)

Gather messages briefly before processing. Useful for handling rapid message bursts.

**Behavior:**
1. Messages arrive and enter the queue
2. System waits `debounce_ms` milliseconds
3. If more messages arrive during wait, timer resets
4. After debounce period, all collected messages are processed together

**Configuration:**

```yaml
queue:
  mode: collect
  debounce_ms: 1000  # Wait 1 second
```

**Use cases:**
- User sends multiple messages in quick succession
- Copy-pasted multi-line input split into separate messages
- Voice messages followed by text clarifications

**Example:**

```
00:00.000 - User: "Here's what I need"
00:00.200 - User: "First, update the docs"
00:00.400 - User: "Then run the tests"
00:01.000 - Agent processes all three messages together
```

### steer

Process immediately, cancel in-flight work on new message.

**Behavior:**
1. Message arrives, processing starts immediately
2. If new message arrives while agent is working, cancel current work
3. Start processing new message

**Configuration:**

```yaml
queue:
  mode: steer
  debounce_ms: 0  # Ignored in steer mode
```

**Use cases:**
- User changes their mind mid-request
- Real-time conversation where latest input matters most
- Rapid iteration on a task

**Example:**

```
00:00.000 - User: "Write a function to parse JSON"
00:00.500 - Agent starts working...
00:02.000 - User: "Actually, make it parse YAML instead"
00:02.001 - Agent cancels JSON work, starts YAML implementation
```

### followup

Process messages sequentially without cancellation.

**Behavior:**
1. Message arrives and queues
2. Agent processes messages in order
3. New messages wait until current work completes
4. No cancellation

**Configuration:**

```yaml
queue:
  mode: followup
  debounce_ms: 0  # Ignored in followup mode
```

**Use cases:**
- Step-by-step workflows
- Multi-stage tasks where order matters
- Support ticket processing

**Example:**

```
00:00.000 - User: "Deploy to staging"
00:00.500 - Agent starts deployment...
00:01.000 - User: "Then run smoke tests"
00:03.000 - Deployment completes, agent starts smoke tests
```

### interrupt

Cancel in-flight work on new message, process latest only.

**Behavior:**
1. Message arrives, processing starts immediately
2. If new message arrives, cancel current work and clear queue
3. Only process the most recent message

**Configuration:**

```yaml
queue:
  mode: interrupt
  debounce_ms: 0  # Ignored in interrupt mode
```

**Use cases:**
- User rapidly changing requests
- Real-time commands where only latest matters
- Emergency override scenarios

**Example:**

```
00:00.000 - User: "Show me sales data"
00:00.500 - Agent starts query...
00:01.000 - User: "Wait, show revenue instead"
00:01.500 - User: "Actually, show profit margins"
00:01.501 - Agent cancels everything, processes only "profit margins"
```

## Lanes

Lanes separate different message types and enable independent concurrency control.

### Lane Types

**main_lane** - User messages from channels (Telegram, etc.)

```yaml
lanes:
  main_concurrency: 4  # Process up to 4 user messages simultaneously
```

**subagent_lane** - Delegated tasks to subagents

```yaml
lanes:
  subagent_concurrency: 8  # Higher limit for parallel subagent work
```

**cron_lane** - Scheduled jobs

```yaml
lanes:
  cron_concurrency: 2  # Limit concurrent cron jobs
```

### Concurrency Limits

Each lane has a concurrency limit controlling how many tasks can run in parallel.

**Low concurrency (1-2):**
- Sequential processing
- Predictable resource usage
- Suitable for resource-intensive tasks

**Medium concurrency (4-8):**
- Balanced parallelism
- Good for typical agent workloads
- Default for main lane

**High concurrency (10+):**
- Maximum parallelism
- Higher resource usage
- Suitable for lightweight tasks or subagent coordination

**Example configuration:**

```yaml
lanes:
  main_concurrency: 4      # Moderate for user interactions
  subagent_concurrency: 12 # High for parallel research/analysis
  cron_concurrency: 1      # Sequential for scheduled reports
```

## Queue Capacity and Drop Policies

Prevent unbounded queue growth with capacity limits and drop policies.

### Configuration

```yaml
queue:
  cap: 20                # Max messages per session
  drop_policy: summarize # old, new, summarize
```

### Drop Policies

**old** - Drop oldest messages when cap is reached

```yaml
queue:
  cap: 20
  drop_policy: old
```

Behavior: New messages push out old ones (FIFO).

**new** - Drop newest messages when cap is reached

```yaml
queue:
  cap: 20
  drop_policy: new
```

Behavior: Reject new messages if queue is full.

**summarize** - Compress old messages into a summary

```yaml
queue:
  cap: 20
  drop_policy: summarize
```

Behavior: When cap is reached, compress oldest messages into a single summary message. Preserves context without unbounded growth.

## Per-Session Queuing

Each conversation session has its own queue. Sessions are identified by:

**Telegram:**
- Direct messages: `telegram_{user_id}`
- Group messages: `telegram_group_{group_id}`

**Multiple users:**
```
User A (session: telegram_123456)  → Queue A → Agent
User B (session: telegram_789012)  → Queue B → Agent
```

Both users can interact with the same workspace simultaneously, each with their own queue and conversation context.

## Queue Configuration Examples

### Responsive Support Bot

```yaml
queue:
  mode: steer           # Cancel old work for new requests
  debounce_ms: 0
  cap: 10
  drop_policy: old

lanes:
  main_concurrency: 8   # Handle many users simultaneously
```

### Sequential Task Processor

```yaml
queue:
  mode: followup        # Process in order
  debounce_ms: 0
  cap: 50
  drop_policy: summarize

lanes:
  main_concurrency: 1   # One task at a time
```

### Conversational Assistant

```yaml
queue:
  mode: collect         # Batch rapid messages
  debounce_ms: 1500     # Wait 1.5s for user to finish
  cap: 20
  drop_policy: summarize

lanes:
  main_concurrency: 4   # Handle multiple conversations
```

### High-Throughput Analyzer

```yaml
queue:
  mode: followup
  debounce_ms: 0
  cap: 100
  drop_policy: old

lanes:
  main_concurrency: 2
  subagent_concurrency: 20  # Lots of parallel analysis
```

## Queue Behavior per Mode

| Mode      | Debounce | Cancellation | Queue Clearing | Use Case                    |
|-----------|----------|--------------|----------------|-----------------------------|
| collect   | Yes      | No           | No             | Batch rapid messages        |
| steer     | No       | Yes          | No             | Responsive, cancellable     |
| followup  | No       | No           | No             | Sequential, ordered         |
| interrupt | No       | Yes          | Yes            | Only latest message matters |

## Monitoring Queue Activity

Enable verbose logging to monitor queue behavior:

```bash
poetry run openpaw -c config.yaml -w my-agent -v
```

Log output includes:
- Messages entering queue
- Debounce timer activity
- Lane concurrency status
- Message processing start/completion
- Queue overflow and drop policy actions

## Advanced: Per-Workspace Queue Configuration

Override global queue settings per workspace:

```yaml
# workspace1/agent.yaml
queue:
  mode: steer           # Fast, responsive
  cap: 10

# workspace2/agent.yaml
queue:
  mode: followup        # Sequential processing
  cap: 50
```

Each workspace can have different queue behavior based on its purpose.

## Best Practices

1. **Match mode to use case:**
   - `collect` for conversational agents
   - `steer` for responsive, interactive tasks
   - `followup` for ordered workflows
   - `interrupt` for real-time commands

2. **Set appropriate concurrency:**
   - Lower for resource-intensive tasks
   - Higher for lightweight operations
   - Consider available system resources

3. **Configure reasonable caps:**
   - Prevent memory issues from unbounded queues
   - Use `summarize` to preserve context
   - Monitor queue overflow in logs

4. **Test with realistic load:**
   - Send rapid messages to verify debounce behavior
   - Test cancellation with mode `steer` or `interrupt`
   - Verify concurrent session handling

5. **Tune debounce timing:**
   - Too short: Messages processed separately
   - Too long: Perceived lag for users
   - Sweet spot: 500-1500ms for most use cases

## Troubleshooting

**Messages not processing:**
- Check lane concurrency limits
- Verify queue mode is appropriate
- Enable verbose logging to inspect queue state

**Agent ignoring new messages:**
- May be at lane concurrency limit
- Check if `followup` mode is backing up
- Consider increasing concurrency or switching to `steer`

**Responses feel sluggish:**
- Reduce `debounce_ms` in `collect` mode
- Switch to `steer` mode for immediate processing
- Increase lane concurrency

**Queue overflow errors:**
- Increase `cap` limit
- Switch to `summarize` drop policy
- Optimize agent response time
