"""Heartbeat prompt templates and task summary formatting."""

from datetime import UTC, datetime
from typing import Any

from langchain_core.prompts import PromptTemplate

# Main heartbeat prompt with timestamp injection
HEARTBEAT_PROMPT = PromptTemplate(
    template="""[HEARTBEAT CHECK - {timestamp}]

## Step 1: Check Active Tasks
Use your task management tools to review active work:
1. Call list_tasks() to see all in-progress and pending tasks
2. For in-progress tasks past their expected duration, investigate and update status
3. For awaiting_check tasks, take the appropriate action
4. Update task status and notes as you work through each item

## Step 2: Review HEARTBEAT.md
Check your HEARTBEAT.md file for any non-task items requiring attention:
- Time-sensitive reminders or monitors
- Pending status checks (PRs, builds, deployments)
- User notifications that need to be sent

## Step 3: Take Action or Stand Down
If you found items needing attention:
- Take appropriate action (check APIs, read files, notify user)
- Update HEARTBEAT.md with completed items
- Update task statuses with progress notes

If nothing requires immediate attention, respond exactly: HEARTBEAT_OK

Do NOT repeat previously completed tasks or invent new ones.
""",
    input_variables=["timestamp"],
)

# Active tasks XML wrapper template
ACTIVE_TASKS_TEMPLATE = PromptTemplate(
    template="<active_tasks>\n{task_summary}\n</active_tasks>",
    input_variables=["task_summary"],
)


def build_task_summary(tasks: list[dict[str, Any]]) -> str | None:
    """Build a compact task summary from TASKS.yaml data.

    Args:
        tasks: List of task dictionaries (already filtered to active tasks).

    Returns:
        Formatted task summary string, or None if no tasks.
    """
    if not tasks:
        return None

    lines = [f"Active Tasks ({len(tasks)}):"]
    now = datetime.now(UTC)

    for task in tasks:
        task_id = task.get("id", "unknown")
        # Show first 8 chars of ID
        short_id = task_id[:8] if len(task_id) > 8 else task_id
        status = task.get("status", "unknown")
        title = task.get("description", "Untitled")

        # Calculate age based on created_at or started_at
        created_str = task.get("started_at") or task.get("created_at")
        age_str = "unknown age"
        if created_str:
            try:
                created_at = datetime.fromisoformat(created_str)
                # Ensure both datetimes are timezone-aware for comparison
                if created_at.tzinfo is None:
                    # Assume UTC if no timezone info
                    created_at = created_at.replace(tzinfo=UTC)
                delta = now - created_at

                # Format as "Xm ago", "Xh ago", "Xd ago"
                total_minutes = int(delta.total_seconds() / 60)
                if total_minutes < 60:
                    age_str = f"{total_minutes}m ago"
                elif total_minutes < 1440:  # Less than 24 hours
                    hours = total_minutes // 60
                    age_str = f"{hours}h ago"
                else:
                    days = total_minutes // 1440
                    age_str = f"{days}d ago"
            except (ValueError, TypeError):
                pass

        # Format: - [abc12345] in_progress | "Market analysis" (started 15m ago)
        status_verb = "running" if status == "in_progress" else "created"
        lines.append(f'- [{short_id}] {status} | "{title}" ({status_verb} {age_str})')

    return "\n".join(lines)
