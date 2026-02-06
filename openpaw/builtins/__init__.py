"""OpenPaw builtins - reusable capabilities for agent workspaces.

Builtins come in two types:
- Tools: LangChain-compatible tools the agent can invoke (Brave Search, ElevenLabs TTS)
- Processors: Channel-layer transformers for inbound/outbound messages (Whisper transcription)
"""

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.loader import BuiltinLoader
from openpaw.builtins.registry import BuiltinRegistry

__all__ = [
    "BaseBuiltinProcessor",
    "BaseBuiltinTool",
    "BuiltinLoader",
    "BuiltinMetadata",
    "BuiltinPrerequisite",
    "BuiltinRegistry",
    "BuiltinType",
]
