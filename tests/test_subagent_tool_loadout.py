"""Tests for per-spawn tool loadout customization."""

import logging
from datetime import UTC, datetime

import pytest

from openpaw.domain.subagent import SubAgentRequest, SubAgentStatus
from openpaw.subagent.runner import filter_subagent_tools


# Mock tool class for testing
class MockTool:
    """Mock tool with a name attribute."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"MockTool({self.name})"


@pytest.fixture
def mock_tools():
    """Create a set of mock tools for testing."""
    return [
        MockTool("read_file"),
        MockTool("write_file"),
        MockTool("browser_navigate"),
        MockTool("browser_click"),
        MockTool("brave_search"),
        MockTool("spawn_agent"),  # Should always be excluded
        MockTool("send_message"),  # Should always be excluded
        MockTool("request_followup"),  # Should always be excluded
    ]


@pytest.fixture
def mock_group_resolver():
    """Mock group resolver for testing."""
    def resolver(group_name: str) -> list[str]:
        if group_name == "web":
            return ["browser_navigate", "browser_click", "brave_search"]
        elif group_name == "filesystem":
            return ["read_file", "write_file"]
        elif group_name == "unknown":
            raise ValueError("Unknown group")
        return []
    return resolver


class TestFilterSubagentTools:
    """Test suite for filter_subagent_tools function."""

    def test_default_filtering_unchanged(self, mock_tools):
        """Default filtering (no allowed/denied) only removes SUBAGENT_EXCLUDED_TOOLS."""
        filtered = filter_subagent_tools(mock_tools)

        # Should have removed spawn_agent, send_message, request_followup
        tool_names = [t.name for t in filtered]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "browser_navigate" in tool_names
        assert "browser_click" in tool_names
        assert "brave_search" in tool_names
        assert "spawn_agent" not in tool_names
        assert "send_message" not in tool_names
        assert "request_followup" not in tool_names
        assert len(filtered) == 5

    def test_allowed_whitelist_filters_correctly(self, mock_tools):
        """Allowed whitelist filters tools correctly."""
        allowed = ["read_file", "write_file"]
        filtered = filter_subagent_tools(mock_tools, allowed_tools=allowed)

        tool_names = [t.name for t in filtered]
        assert tool_names == ["read_file", "write_file"]
        assert len(filtered) == 2

    def test_denied_adds_additional_removals(self, mock_tools):
        """Denied adds additional removals beyond SUBAGENT_EXCLUDED_TOOLS."""
        denied = ["browser_navigate", "brave_search"]
        filtered = filter_subagent_tools(mock_tools, denied_tools=denied)

        tool_names = [t.name for t in filtered]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "browser_click" in tool_names
        assert "browser_navigate" not in tool_names
        assert "brave_search" not in tool_names
        # Excluded tools still removed
        assert "spawn_agent" not in tool_names
        assert "send_message" not in tool_names
        assert len(filtered) == 3

    def test_allowed_and_denied_compose(self, mock_tools):
        """Allowed + denied compose correctly (allowed first, then denied)."""
        allowed = ["read_file", "write_file", "browser_navigate", "browser_click"]
        denied = ["write_file", "browser_click"]
        filtered = filter_subagent_tools(
            mock_tools, allowed_tools=allowed, denied_tools=denied
        )

        tool_names = [t.name for t in filtered]
        assert tool_names == ["read_file", "browser_navigate"]
        assert len(filtered) == 2

    def test_excluded_tools_always_removed(self, mock_tools):
        """SUBAGENT_EXCLUDED_TOOLS always removed even if in allowed list."""
        # Try to allow spawn_agent explicitly
        allowed = ["read_file", "spawn_agent", "send_message"]
        filtered = filter_subagent_tools(mock_tools, allowed_tools=allowed)

        tool_names = [t.name for t in filtered]
        # spawn_agent and send_message should be blocked despite being in allowed
        assert "read_file" in tool_names
        assert "spawn_agent" not in tool_names
        assert "send_message" not in tool_names
        assert len(filtered) == 1

    def test_group_prefix_resolves_correctly(self, mock_tools, mock_group_resolver):
        """Group: prefix resolves correctly via group_resolver."""
        allowed = ["group:web"]
        filtered = filter_subagent_tools(
            mock_tools, allowed_tools=allowed, group_resolver=mock_group_resolver
        )

        tool_names = [t.name for t in filtered]
        assert "browser_navigate" in tool_names
        assert "browser_click" in tool_names
        assert "brave_search" in tool_names
        assert "read_file" not in tool_names
        assert "write_file" not in tool_names
        assert len(filtered) == 3

    def test_group_prefix_in_denied(self, mock_tools, mock_group_resolver):
        """Group: prefix works in denied_tools."""
        denied = ["group:web"]
        filtered = filter_subagent_tools(
            mock_tools, denied_tools=denied, group_resolver=mock_group_resolver
        )

        tool_names = [t.name for t in filtered]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "browser_navigate" not in tool_names
        assert "browser_click" not in tool_names
        assert "brave_search" not in tool_names
        assert len(filtered) == 2

    def test_multiple_groups_in_allowed(self, mock_tools, mock_group_resolver):
        """Multiple groups can be specified in allowed_tools."""
        allowed = ["group:web", "group:filesystem"]
        filtered = filter_subagent_tools(
            mock_tools, allowed_tools=allowed, group_resolver=mock_group_resolver
        )

        tool_names = [t.name for t in filtered]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "browser_navigate" in tool_names
        assert "browser_click" in tool_names
        assert "brave_search" in tool_names
        # Excluded tools still removed
        assert "spawn_agent" not in tool_names
        assert len(filtered) == 5

    def test_mixed_group_and_individual_tools(self, mock_tools, mock_group_resolver):
        """Can mix group: prefix and individual tool names."""
        allowed = ["group:filesystem", "browser_navigate"]
        filtered = filter_subagent_tools(
            mock_tools, allowed_tools=allowed, group_resolver=mock_group_resolver
        )

        tool_names = [t.name for t in filtered]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "browser_navigate" in tool_names
        assert "browser_click" not in tool_names
        assert len(filtered) == 3

    def test_unknown_tool_names_warn_not_error(self, mock_tools, caplog):
        """Unknown tool names in allowed/denied produce warning, not error."""
        with caplog.at_level(logging.WARNING):
            allowed = ["read_file", "unknown_tool_1", "unknown_tool_2"]
            filtered = filter_subagent_tools(mock_tools, allowed_tools=allowed)

            # Should not raise, just warn
            assert len(filtered) == 1
            assert filtered[0].name == "read_file"

            # Check warning was logged
            assert "Unknown tools in allowed_tools list" in caplog.text
            assert "unknown_tool_1" in caplog.text
            assert "unknown_tool_2" in caplog.text

    def test_unknown_tool_names_in_denied_warn(self, mock_tools, caplog):
        """Unknown tool names in denied_tools produce warning."""
        with caplog.at_level(logging.WARNING):
            denied = ["unknown_tool"]
            filtered = filter_subagent_tools(mock_tools, denied_tools=denied)

            # Should filter normally, just with warning
            assert len(filtered) == 5

            # Check warning was logged
            assert "Unknown tools in denied_tools list" in caplog.text
            assert "unknown_tool" in caplog.text

    def test_unknown_group_warns(self, mock_tools, mock_group_resolver, caplog):
        """Unknown group in allowed/denied produces warning."""
        with caplog.at_level(logging.WARNING):
            allowed = ["group:unknown"]
            filtered = filter_subagent_tools(
                mock_tools, allowed_tools=allowed, group_resolver=mock_group_resolver
            )

            # Group resolution fails, no tools match
            assert len(filtered) == 0

            # Check warning was logged about group resolution failure
            assert "Failed to resolve group 'unknown'" in caplog.text

    def test_empty_allowed_tools_list(self, mock_tools):
        """Empty allowed_tools list results in no tools (except none match empty set)."""
        filtered = filter_subagent_tools(mock_tools, allowed_tools=[])

        # Empty whitelist means nothing is allowed
        assert len(filtered) == 0

    def test_empty_denied_tools_list(self, mock_tools):
        """Empty denied_tools list has no effect."""
        filtered = filter_subagent_tools(mock_tools, denied_tools=[])

        # Should behave same as default filtering
        tool_names = [t.name for t in filtered]
        assert len(filtered) == 5
        assert "spawn_agent" not in tool_names


class TestSubAgentRequestDomainModel:
    """Test suite for SubAgentRequest domain model serialization."""

    def test_to_dict_omits_none_fields(self):
        """to_dict omits allowed_tools and denied_tools if None."""
        request = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
        )

        data = request.to_dict()

        assert "allowed_tools" not in data
        assert "denied_tools" not in data
        assert data["id"] == "test-id"
        assert data["task"] == "test task"

    def test_to_dict_includes_non_none_fields(self):
        """to_dict includes allowed_tools and denied_tools if not None."""
        request = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            allowed_tools=["read_file", "write_file"],
            denied_tools=["browser_navigate"],
        )

        data = request.to_dict()

        assert data["allowed_tools"] == ["read_file", "write_file"]
        assert data["denied_tools"] == ["browser_navigate"]

    def test_from_dict_with_new_fields(self):
        """from_dict correctly deserializes new fields."""
        data = {
            "id": "test-id",
            "task": "test task",
            "label": "test",
            "status": "pending",
            "session_key": "telegram:123",
            "created_at": datetime.now(UTC).isoformat(),
            "allowed_tools": ["read_file"],
            "denied_tools": ["browser_navigate"],
        }

        request = SubAgentRequest.from_dict(data)

        assert request.allowed_tools == ["read_file"]
        assert request.denied_tools == ["browser_navigate"]

    def test_from_dict_backward_compat(self):
        """from_dict handles old data without new fields (backward compat)."""
        data = {
            "id": "test-id",
            "task": "test task",
            "label": "test",
            "status": "pending",
            "session_key": "telegram:123",
            "created_at": datetime.now(UTC).isoformat(),
        }

        request = SubAgentRequest.from_dict(data)

        # Should default to None
        assert request.allowed_tools is None
        assert request.denied_tools is None

    def test_roundtrip_serialization_with_tools(self):
        """Roundtrip serialization preserves allowed/denied tools."""
        original = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            allowed_tools=["group:web", "read_file"],
            denied_tools=["browser_click"],
        )

        # Serialize and deserialize
        data = original.to_dict()
        restored = SubAgentRequest.from_dict(data)

        assert restored.allowed_tools == original.allowed_tools
        assert restored.denied_tools == original.denied_tools

    def test_roundtrip_serialization_without_tools(self):
        """Roundtrip serialization works when tools are None."""
        original = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
        )

        # Serialize and deserialize
        data = original.to_dict()
        restored = SubAgentRequest.from_dict(data)

        assert restored.allowed_tools is None
        assert restored.denied_tools is None


class TestSubAgentRequestCreation:
    """Test suite for SubAgentRequest creation with tool filters."""

    def test_create_request_with_allowed_tools(self):
        """Can create request with allowed_tools."""
        request = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            allowed_tools=["read_file", "write_file"],
        )

        assert request.allowed_tools == ["read_file", "write_file"]
        assert request.denied_tools is None

    def test_create_request_with_denied_tools(self):
        """Can create request with denied_tools."""
        request = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            denied_tools=["browser_navigate"],
        )

        assert request.allowed_tools is None
        assert request.denied_tools == ["browser_navigate"]

    def test_create_request_with_both_tool_filters(self):
        """Can create request with both allowed and denied tools."""
        request = SubAgentRequest(
            id="test-id",
            task="test task",
            label="test",
            status=SubAgentStatus.PENDING,
            session_key="telegram:123",
            allowed_tools=["group:web"],
            denied_tools=["browser_click"],
        )

        assert request.allowed_tools == ["group:web"]
        assert request.denied_tools == ["browser_click"]
