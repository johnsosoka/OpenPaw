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
