"""Tests for SSH tool builtin."""

import pytest

from openpaw.builtins.tools.ssh import SSHTool


class TestSSHTool:
    """Test SSH tool functionality."""

    def test_metadata(self):
        """Test SSH tool metadata is correct."""
        assert SSHTool.metadata.name == "ssh"
        assert SSHTool.metadata.display_name == "SSH Remote Execution"
        assert SSHTool.metadata.group == "system"
        assert SSHTool.metadata.prerequisites.env_vars == []

    def test_initialization_empty_config(self):
        """Test SSH tool initializes with empty config."""
        tool = SSHTool()
        assert tool.config == {}
        assert tool._allowed_hosts == []

    def test_initialization_with_config(self):
        """Test SSH tool initializes with config."""
        config = {
            "allowed_hosts": ["example.com", "192.168.1.1"],
            "default_user": "admin",
            "default_key_path": "~/.ssh/id_rsa",
            "timeout": 60,
        }
        tool = SSHTool(config)
        assert tool._allowed_hosts == ["example.com", "192.168.1.1"]
        assert tool.config["default_user"] == "admin"
        assert tool.config["default_key_path"] == "~/.ssh/id_rsa"
        assert tool.config["timeout"] == 60

    @pytest.mark.asyncio
    async def test_host_allowlist_enforcement(self):
        """Test that non-allowlisted hosts are rejected."""
        config = {
            "allowed_hosts": ["allowed.example.com"],
        }
        tool = SSHTool(config)
        langchain_tool = tool.get_langchain_tool()

        # Try to execute on non-allowlisted host
        result = await langchain_tool.ainvoke({
            "host": "malicious.example.com",
            "command": "whoami",
        })

        assert "[ERROR]" in result
        assert "not in allowed_hosts" in result
        assert "malicious.example.com" in result

    @pytest.mark.asyncio
    async def test_empty_allowlist_rejects_all(self):
        """Test that empty allowlist rejects all connections."""
        tool = SSHTool(config={})
        langchain_tool = tool.get_langchain_tool()

        result = await langchain_tool.ainvoke({
            "host": "any.example.com",
            "command": "ls",
        })

        assert "[ERROR]" in result
        assert "not in allowed_hosts" in result

    def test_langchain_tool_creation(self):
        """Test that get_langchain_tool returns a valid tool."""
        config = {"allowed_hosts": ["test.example.com"]}
        tool = SSHTool(config)
        langchain_tool = tool.get_langchain_tool()

        assert langchain_tool is not None
        assert langchain_tool.name == "ssh_execute"
        assert "remote hosts" in langchain_tool.description.lower()
