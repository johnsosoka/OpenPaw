"""Configuration package for OpenPaw.

This package provides Pydantic configuration models and loading utilities.
All models and functions are re-exported at the package level for backward compatibility.
"""

# Import all models
# Import loading utilities
from openpaw.core.config.loader import (
    check_unexpanded_vars,
    expand_env_vars,
    expand_env_vars_recursive,
    load_config,
    merge_configs,
)
from openpaw.core.config.models.base import (
    AgentConfig,
    Config,
    LaneConfig,
    LoggingConfig,
    ProviderDefinition,
    QueueConfig,
)
from openpaw.core.config.models.builtin import (
    BuiltinItemConfig,
    BuiltinsConfig,
    CronBuiltinConfig,
    DoclingBuiltinConfig,
    SendFileBuiltinConfig,
)
from openpaw.core.config.models.channel import WorkspaceChannelConfig
from openpaw.core.config.models.cron import HeartbeatConfig
from openpaw.core.config.models.security import ApprovalGatesConfig, ToolApprovalConfig
from openpaw.core.config.models.workspace import (
    WorkspaceBuiltinsConfig,
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
    "ProviderDefinition",
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
    "check_unexpanded_vars",
    "expand_env_vars",
    "expand_env_vars_recursive",
    "load_config",
    "merge_configs",
]
