"""Agent runner integrating DeepAgents with OpenPaw workspace system."""

import logging
from typing import Any

from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from openpaw.workspace.loader import AgentWorkspace

logger = logging.getLogger(__name__)


class AgentRunner:
    """Runs DeepAgents with OpenPaw workspace configuration.

    Integrates:
    - Workspace-based system prompts (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
    - DeepAgents native skills from workspace skills/ directory
    - LangGraph checkpointing for multi-turn conversations
    """

    def __init__(
        self,
        workspace: AgentWorkspace,
        model: str = "anthropic:claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_turns: int = 50,
        temperature: float = 0.7,
        checkpointer: Any | None = None,
        tools: list[Any] | None = None,
    ):
        """Initialize the agent runner.

        Args:
            workspace: Loaded agent workspace.
            model: Model identifier (provider:model format).
            api_key: API key for the model provider.
            max_turns: Maximum agent turns per invocation.
            temperature: Model temperature setting.
            checkpointer: Optional LangGraph checkpointer for persistence.
            tools: Optional additional tools to provide to the agent.
        """
        self.workspace = workspace
        self.model_id = model
        self.api_key = api_key
        self.max_turns = max_turns
        self.temperature = temperature
        self.checkpointer = checkpointer
        self.tools = tools or []

        self._agent = self._build_agent()

    def _build_agent(self) -> Any:
        """Build the DeepAgent with workspace configuration."""
        model_kwargs: dict[str, Any] = {"temperature": self.temperature}
        if self.api_key:
            model_kwargs["api_key"] = self.api_key

        model = init_chat_model(self.model_id, **model_kwargs)
        system_prompt = self.workspace.build_system_prompt()

        skills_paths: list[str] = []
        if self.workspace.skills_path.exists():
            skills_paths.append(str(self.workspace.skills_path))

        agent = create_deep_agent(
            model=model,
            system_prompt=system_prompt,
            tools=self.tools if self.tools else None,
            skills=skills_paths if skills_paths else None,
            checkpointer=self.checkpointer,
        )

        return agent

    async def run(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Run the agent with a user message.

        Args:
            message: User input message.
            session_id: Session identifier for checkpointing.
            thread_id: Thread identifier for multi-turn conversations.

        Returns:
            Agent's response text.
        """
        config: dict[str, Any] = {}
        if session_id or thread_id:
            config["configurable"] = {}
            if thread_id:
                config["configurable"]["thread_id"] = thread_id
            if session_id:
                config["configurable"]["session_id"] = session_id

        result = await self._agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config if config else None,
        )

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "content"):
                return str(last_message.content)
            return str(last_message)

        return ""

    def run_sync(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Synchronous version of run for non-async contexts."""
        config: dict[str, Any] = {}
        if session_id or thread_id:
            config["configurable"] = {}
            if thread_id:
                config["configurable"]["thread_id"] = thread_id
            if session_id:
                config["configurable"]["session_id"] = session_id

        result = self._agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config if config else None,
        )

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "content"):
                return str(last_message.content)
            return str(last_message)

        return ""
