"""Command prompt templates for conversation management."""

from langchain_core.prompts import PromptTemplate

# Summarization prompt for /compact command (static, no variables)
SUMMARIZE_PROMPT = (
    "Summarize the conversation so far in a concise paragraph (3-5 sentences).\n"
    "Focus on:\n"
    "- The main topics discussed\n"
    "- Key decisions or conclusions reached\n"
    "- Any ongoing tasks or commitments\n"
    "- Important context that should be preserved\n\n"
    "Write the summary as a factual overview, not as a message to the user.\n"
    "Do NOT include greetings, sign-offs, or meta-commentary about the summary itself."
)

# Summary injection template for new conversation after compaction
COMPACTED_TEMPLATE = PromptTemplate(
    template=(
        "[CONVERSATION COMPACTED]\n\n"
        "Previous conversation summary:\n"
        "{summary}\n\n"
        "The full conversation has been archived. Continue from this context."
    ),
    input_variables=["summary"],
)

# Marker the agent replies with when nothing needs saving in a pre-compact flush
FLUSH_NOOP_MARKER = "NOTHING_TO_FLUSH"

# Pre-compact flush prompt: one turn to persist working context before summarization
FLUSH_PROMPT_TEMPLATE = PromptTemplate(
    template=(
        "[PRE-COMPACT FLUSH]\n\n"
        "This conversation is about to be compacted into a short summary. "
        "Anything not in the summary will be lost from context.\n"
        "If there is working context you must not lose — task state, decisions made, "
        "gathered facts, open threads — write it now to the file '{flush_path}' "
        "using your filesystem tools.\n"
        "If nothing needs saving, do not write any file and reply with exactly: "
        "NOTHING_TO_FLUSH"
    ),
    input_variables=["flush_path"],
)

# Appended to the summary injection when a pre-compact flush file was written
FLUSH_NOTE_TEMPLATE = PromptTemplate(
    template=(
        "\n\nDurable working context from before compaction was saved to "
        "'{flush_path}'. Read it if you need details beyond this summary."
    ),
    input_variables=["flush_path"],
)

# Auto-compact injection template for automatic context rotation
AUTO_COMPACT_TEMPLATE = PromptTemplate(
    template=(
        "[AUTO-COMPACTED]\n\n"
        "The conversation was automatically compacted because context utilization "
        "reached the configured threshold.\n\n"
        "Previous conversation summary:\n"
        "{summary}\n\n"
        "The full conversation has been archived. Continue from this context."
    ),
    input_variables=["summary"],
)
