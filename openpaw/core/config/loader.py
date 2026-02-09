"""Configuration loading and merging utilities.

This module handles YAML config file loading, environment variable expansion,
and deep merging of workspace-specific overrides.
"""

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

from openpaw.core.config.models import Config


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} patterns in a string with environment variable values.

    Args:
        value: String potentially containing ${VAR_NAME} patterns.

    Returns:
        String with all ${VAR_NAME} patterns replaced by their values from os.environ.
        If a variable is not found, the pattern is left unchanged.

    Examples:
        >>> os.environ['API_KEY'] = 'secret123'
        >>> expand_env_vars('Token: ${API_KEY}')
        'Token: secret123'
    """
    pattern = r'\$\{([^}]+)\}'

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(pattern, replacer, value)


def expand_env_vars_recursive(obj: Any) -> Any:
    """Recursively expand environment variables in nested dicts and lists.

    Args:
        obj: Any Python object (dict, list, str, or other).

    Returns:
        Object with all string values having ${VAR} patterns expanded.

    Examples:
        >>> expand_env_vars_recursive({'key': '${HOME}/path', 'nested': {'val': '${USER}'}})
        {'key': '/home/user/path', 'nested': {'val': 'username'}}
    """
    if isinstance(obj, dict):
        return {key: expand_env_vars_recursive(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars_recursive(item) for item in obj]
    elif isinstance(obj, str):
        return expand_env_vars(obj)
    else:
        return obj


def merge_configs(global_config: dict[str, Any], workspace_config: dict[str, Any]) -> dict[str, Any]:
    """Deep merge workspace config over global config.

    Args:
        global_config: Base configuration dictionary (defaults).
        workspace_config: Workspace-specific configuration (overrides).

    Returns:
        Merged configuration with workspace values taking precedence.
        Nested dicts are merged recursively.

    Examples:
        >>> global_cfg = {'agent': {'model': 'gpt-4', 'temp': 0.7}}
        >>> workspace_cfg = {'agent': {'model': 'claude-3'}}
        >>> merge_configs(global_cfg, workspace_cfg)
        {'agent': {'model': 'claude-3', 'temp': 0.7}}
    """
    result = copy.deepcopy(global_config)
    for key, value in workspace_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | str) -> Config:
    """Load configuration from a YAML file with environment variable expansion.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Parsed Config object with all ${VAR} patterns expanded.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    # Expand environment variables in all string values
    data = expand_env_vars_recursive(data)

    return Config(**data)
