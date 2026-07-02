"""Tests for the config-gated react-path tool selector (ADR-104 §5, T4.3)."""

import logging
from typing import Any
from unittest.mock import MagicMock

from langchain.agents.middleware import LLMToolSelectorMiddleware

from openpaw.core.config.models import Config, WorkspaceConfig
from openpaw.workspace.initializer import WorkspaceInitializer


def make_initializer(harness: dict[str, Any]) -> WorkspaceInitializer:
    workspace = MagicMock()
    workspace.config = WorkspaceConfig.model_validate({"harness": harness})
    return WorkspaceInitializer(
        config=Config(),
        workspace=workspace,
        merged_config={},
        logger=logging.getLogger("test-selector"),
    )


def test_disabled_by_default() -> None:
    init = make_initializer({"type": "react"})
    assert init._build_react_tool_selector([]) is None


def test_planner_type_never_gets_selector() -> None:
    init = make_initializer(
        {"type": "planner", "tool_equipping": {"react_selector": True}}
    )
    assert init._build_react_tool_selector([]) is None


def test_enabled_builds_middleware_with_floor() -> None:
    init = make_initializer(
        {
            "type": "react",
            "tool_equipping": {
                "react_selector": True,
                "max_tools": 7,
                "always_equip": ["send_message"],
            },
        }
    )
    mw = init._build_react_tool_selector([])
    assert isinstance(mw, LLMToolSelectorMiddleware)


def test_no_workspace_config_is_none() -> None:
    workspace = MagicMock()
    workspace.config = None
    init = WorkspaceInitializer(
        config=Config(),
        workspace=workspace,
        merged_config={},
        logger=logging.getLogger("test-selector"),
    )
    assert init._build_react_tool_selector([]) is None
