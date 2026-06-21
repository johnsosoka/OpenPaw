"""Tests for the session-scoped planning tool."""

import pytest

from openpaw.builtins.tools.plan import PlanToolBuiltin


@pytest.fixture
def plan_tool() -> PlanToolBuiltin:
    """Create a PlanToolBuiltin instance."""
    return PlanToolBuiltin(config={})


@pytest.fixture
def plan_tools(plan_tool: PlanToolBuiltin) -> dict:
    """Get the LangChain tools as a dict by name."""
    tools = plan_tool.get_langchain_tool()
    return {t.name: t for t in tools}


class TestPlanToolBuiltin:
    """Test PlanToolBuiltin metadata and initialization."""

    def test_metadata(self, plan_tool: PlanToolBuiltin) -> None:
        assert plan_tool.metadata.name == "plan"
        assert plan_tool.metadata.group == "automation"
        assert plan_tool.metadata.prerequisites.is_satisfied()

    def test_returns_two_tools(self, plan_tool: PlanToolBuiltin) -> None:
        tools = plan_tool.get_langchain_tool()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"write_plan", "read_plan"}


class TestWritePlan:
    """Test write_plan tool functionality."""

    def test_write_plan_stores_steps(self, plan_tools: dict) -> None:
        result = plan_tools["write_plan"].invoke({
            "steps": [
                {"step": "Diagnose the issue", "status": "pending"},
                {"step": "Apply the fix", "status": "pending"},
            ]
        })
        assert "Plan updated" in result
        assert "Diagnose the issue" in result
        assert "Apply the fix" in result

    def test_write_plan_overwrites_previous(self, plan_tools: dict) -> None:
        plan_tools["write_plan"].invoke({"steps": [{"step": "Old step", "status": "pending"}]})
        result = plan_tools["write_plan"].invoke({"steps": [{"step": "New step", "status": "pending"}]})
        assert "New step" in result
        # Read to confirm overwrite
        read_result = plan_tools["read_plan"].invoke({})
        assert "New step" in read_result
        assert "Old step" not in read_result

    def test_write_plan_with_statuses(self, plan_tools: dict) -> None:
        result = plan_tools["write_plan"].invoke(
            {
                "steps": [
                    {"step": "Step 1", "status": "completed"},
                    {"step": "Step 2", "status": "in_progress"},
                    {"step": "Step 3", "status": "pending"},
                ]
            }
        )
        assert "1/3 completed" in result
        assert "[x]" in result
        assert "[>]" in result
        assert "[ ]" in result

    def test_write_plan_invalid_status(self, plan_tools: dict) -> None:
        result = plan_tools["write_plan"].invoke({"steps": [{"step": "Bad step", "status": "invalid"}]})
        assert "Error" in result
        assert "invalid" in result

    def test_write_plan_default_status(self, plan_tools: dict) -> None:
        result = plan_tools["write_plan"].invoke({"steps": [{"step": "Default status step"}]})
        assert "0/1 completed" in result
        assert "[ ]" in result

    def test_write_plan_remaining_count(self, plan_tools: dict) -> None:
        result = plan_tools["write_plan"].invoke(
            {
                "steps": [
                    {"step": "Done", "status": "completed"},
                    {"step": "Todo 1", "status": "pending"},
                    {"step": "Todo 2", "status": "pending"},
                ]
            }
        )
        assert "2 step(s) remaining" in result


class TestReadPlan:
    """Test read_plan tool functionality."""

    def test_read_plan_empty(self, plan_tools: dict) -> None:
        result = plan_tools["read_plan"].invoke({})
        assert "No active plan" in result

    def test_read_plan_after_write(self, plan_tools: dict) -> None:
        plan_tools["write_plan"].invoke(
            {"steps": [{"step": "Step A", "status": "completed"}, {"step": "Step B", "status": "pending"}]}
        )
        result = plan_tools["read_plan"].invoke({})
        assert "Current plan" in result
        assert "1/2 completed" in result
        assert "Step A" in result
        assert "Step B" in result


class TestPlanReset:
    """Test plan reset functionality."""

    def test_reset_clears_plan(self, plan_tool: PlanToolBuiltin) -> None:
        tools = {t.name: t for t in plan_tool.get_langchain_tool()}
        tools["write_plan"].invoke({"steps": [{"step": "Some step", "status": "pending"}]})
        # Reset (simulates /new)
        plan_tool.reset()
        result = tools["read_plan"].invoke({})
        assert "No active plan" in result


class TestPlanToolDescriptions:
    """Test tool descriptions contain planning guidance."""

    def test_write_plan_description(self, plan_tools: dict) -> None:
        desc = plan_tools["write_plan"].description
        assert "multi-step" in desc.lower() or "plan" in desc.lower()

    def test_read_plan_description(self, plan_tools: dict) -> None:
        desc = plan_tools["read_plan"].description
        assert "plan" in desc.lower()
