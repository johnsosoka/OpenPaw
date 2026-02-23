"""Runtime system event injection templates."""

from langchain_core.prompts import PromptTemplate

# Followup injection template
FOLLOWUP_TEMPLATE = PromptTemplate(
    template="[SYSTEM FOLLOWUP - depth {depth}]\n{prompt}",
    input_variables=["depth", "prompt"],
)

# Tool approval denial notification
TOOL_DENIED_TEMPLATE = PromptTemplate(
    template="[SYSTEM] The tool '{tool_name}' was denied by the user. Do not retry this action.",
    input_variables=["tool_name"],
)

# Steer mode skip message (static, no variables)
STEER_SKIP_MESSAGE = "[Skipped: user sent new message — redirecting]"

# Sub-agent timeout notification
SUBAGENT_TIMED_OUT_TEMPLATE = PromptTemplate(
    template="[SYSTEM] Sub-agent '{label}' timed out after {timeout_minutes} minutes.",
    input_variables=["label", "timeout_minutes"],
)

# Sub-agent failure notification
SUBAGENT_FAILED_TEMPLATE = PromptTemplate(
    template="[SYSTEM] Sub-agent '{label}' failed.\nError: {error}",
    input_variables=["label", "error"],
)

# Sub-agent completion (truncated with reference to full output)
SUBAGENT_COMPLETED_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] Sub-agent '{label}' completed.\n\n"
        "{output}\n\n"
        'Use get_subagent_result(id="{request_id}") to read the full output.'
    ),
    input_variables=["label", "output", "request_id"],
)

# Sub-agent completion (short output, no truncation)
SUBAGENT_COMPLETED_SHORT_TEMPLATE = PromptTemplate(
    template="[SYSTEM] Sub-agent '{label}' completed.\n\n{output}",
    input_variables=["label", "output"],
)

# Interrupt mode notification (static, no variables)
INTERRUPT_NOTIFICATION = "[Run interrupted — processing new message]"

# Timeout warning for graceful shutdown (Track 3B)
TIMEOUT_WARNING_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] You have used {elapsed_pct}% of your time budget "
        "({remaining}s remaining). Wrap up your current work, send a progress "
        "update to the user, or use request_followup to continue later."
    ),
    input_variables=["elapsed_pct", "remaining"],
)

# Timeout notification with tool context (Track 3C)
TIMEOUT_NOTIFICATION_TEMPLATE = PromptTemplate(
    template=(
        "I ran out of time after {timeout}s while running '{tool_name}'. "
        "The operation may still be completing in the background. "
        "Please try again or ask me to resume."
    ),
    input_variables=["timeout", "tool_name"],
)

# Timeout notification without tool context (fallback)
TIMEOUT_NOTIFICATION_GENERIC = PromptTemplate(
    template=(
        "I ran out of time processing your request (timeout: {timeout}s). "
        "Please try again with a simpler request."
    ),
    input_variables=["timeout"],
)

# --- Scheduled agent result injection templates ---

# Maximum characters of output to include in queue injection messages.
# Full output is always available via the session log file.
INJECTION_TRUNCATION_LIMIT = 2000

# Heartbeat result (fits within truncation limit)
HEARTBEAT_RESULT_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] Heartbeat completed.\n\n"
        "{output}\n\n"
        "Full session log: {session_path}\n"
        "Review and take action if needed."
    ),
    input_variables=["output", "session_path"],
)

# Heartbeat result (output was truncated)
HEARTBEAT_RESULT_TRUNCATED_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] Heartbeat completed (truncated).\n\n"
        "{output}\n\n"
        "Full session log: {session_path}\n"
        'Use read_file("{session_path}") for full context.'
    ),
    input_variables=["output", "session_path"],
)

# Cron result (fits within truncation limit)
CRON_RESULT_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] Scheduled task '{cron_name}' completed.\n\n"
        "{output}\n\n"
        "Full session log: {session_path}\n"
        "Review and take action if needed."
    ),
    input_variables=["cron_name", "output", "session_path"],
)

# Cron result (output was truncated)
CRON_RESULT_TRUNCATED_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] Scheduled task '{cron_name}' completed (truncated).\n\n"
        "{output}\n\n"
        "Full session log: {session_path}\n"
        'Use read_file("{session_path}") for full context.'
    ),
    input_variables=["cron_name", "output", "session_path"],
)
