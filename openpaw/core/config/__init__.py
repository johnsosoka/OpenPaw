"""Configuration package for OpenPaw.

This package provides Pydantic configuration models and loading utilities.
All models and functions are re-exported at the package level for backward compatibility.
"""

# Import all models
# Import loading utilities
from openpaw.core.config.loader import (
    expand_env_vars,
    expand_env_vars_recursive,
    load_config,
    merge_configs,
)
from openpaw.core.config.models import (
    AgentConfig,
    ApprovalGatesConfig,
    BuiltinItemConfig,
    BuiltinsConfig,
    Config,
    CronBuiltinConfig,
    DoclingBuiltinConfig,
    HeartbeatConfig,
    LaneConfig,
    LoggingConfig,
    QueueConfig,
    SendFileBuiltinConfig,
    ToolApprovalConfig,
    WorkspaceBuiltinsConfig,
    WorkspaceChannelConfig,
    WorkspaceConfig,
    WorkspaceModelConfig,
    WorkspaceQueueConfig,
    WorkspaceToolsConfig,
)

__all__ = [
    # Models
    "AgentConfig",
    "ApprovalGatesConfig",
    "BuiltinItemConfig",
    "BuiltinsConfig",
    "Config",
    "CronBuiltinConfig",
    "DoclingBuiltinConfig",
    "HeartbeatConfig",
    "LaneConfig",
    "LoggingConfig",
    "QueueConfig",
    "SendFileBuiltinConfig",
    "ToolApprovalConfig",
    "WorkspaceBuiltinsConfig",
    "WorkspaceChannelConfig",
    "WorkspaceConfig",
    "WorkspaceModelConfig",
    "WorkspaceQueueConfig",
    "WorkspaceToolsConfig",
    # Loaders
    "expand_env_vars",
    "expand_env_vars_recursive",
    "load_config",
    "merge_configs",
]
