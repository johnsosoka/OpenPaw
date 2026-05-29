"""Heartbeat execution logic for OpenPaw."""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpaw.agent.session_logger import SessionLogger
from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    set_channel_context,
    set_invocation_origin,
)
from openpaw.channels.base import ChannelAdapter
from openpaw.core.config import HeartbeatConfig
from openpaw.core.paths import HEARTBEAT_LOG_JSONL
from openpaw.core.prompts.system_events import (
    HEARTBEAT_RESULT_TEMPLATE,
    HEARTBEAT_RESULT_TRUNCATED_TEMPLATE,
    INJECTION_TRUNCATION_LIMIT,
)
from openpaw.core.timezone import workspace_now

logger = logging.getLogger(__name__)


class HeartbeatExecutor:
    """Executes heartbeat checks and records events."""

    def __init__(
        self,
        workspace_path: Path,
        workspace_name: str,
        config: HeartbeatConfig,
        token_logger: Any | None,
        result_callback: Callable[[str, str], Awaitable[None]] | None,
        session_logger: SessionLogger | None,
        ack_tool: Any | None,
    ):
        self.workspace_path = workspace_path
        self.workspace_name = workspace_name
        self.config = config
        self._token_logger = token_logger
        self._result_callback = result_callback
        self._session_logger = session_logger
        self._ack_tool = ack_tool

    async def run_heartbeat(
        self,
        preflight: Any,
        prompt_builder: Any,
        timezone: str,
        task_summary: str | None,
        task_count: int,
        agent_factory: Callable[..., Any],
        channels: Mapping[str, Any],
    ) -> None:
        """Execute a heartbeat check with full delivery and logging logic.

        Args:
            preflight: HeartbeatPreflight instance for pre-flight checks.
            prompt_builder: HeartbeatPromptBuilder instance for prompt construction.
            timezone: Workspace timezone string.
            task_summary: Optional task summary string.
            task_count: Number of active tasks.
            agent_factory: Factory function to create fresh agent instances.
            channels: Dictionary mapping channel types to channel instances.
        """
        import time as time_module

        logger.info(f"Running heartbeat check for workspace: {self.workspace_name}")
        set_invocation_origin(f"heartbeat:{self.workspace_name}")

        # Set up channel context so send_message/send_file work during heartbeat execution
        heartbeat_channel = channels.get(self.config.target_channel)
        heartbeat_session_key = (
            self._resolve_heartbeat_session_key(heartbeat_channel, self.config)
            if heartbeat_channel
            else None
        )
        if heartbeat_channel and heartbeat_session_key:
            set_channel_context(heartbeat_channel, heartbeat_session_key)

        start_time = time_module.monotonic()

        try:
            # Resolve max_output_tokens: heartbeat config takes precedence over
            # the workspace-level default already baked into the factory's
            # extra_model_kwargs. Passing it here as extra_overrides lets the
            # heartbeat-specific cap win.
            extra_overrides: dict[str, Any] = {}
            if self.config.max_output_tokens is not None:
                extra_overrides["max_tokens"] = self.config.max_output_tokens

            agent_runner = (
                agent_factory(extra_overrides=extra_overrides)
                if extra_overrides
                else agent_factory()
            )
            heartbeat_prompt = prompt_builder.build_heartbeat_prompt(
                workspace_now(timezone).isoformat(), task_summary
            )
            response = await agent_runner.run(message=heartbeat_prompt)
            duration_ms = (time_module.monotonic() - start_time) * 1000

            # Extract metrics and activity from agent runner
            metrics = agent_runner.last_metrics

            # Log a warning when the output cap was hit — response is likely truncated
            cap = agent_runner.max_output_tokens
            if isinstance(cap, int) and metrics and isinstance(metrics.output_tokens, int):
                if metrics.output_tokens >= cap:
                    logger.warning(
                        f"Heartbeat output token cap reached: "
                        f"{metrics.output_tokens}/{cap} tokens "
                        f"— response likely truncated (workspace: {self.workspace_name})"
                    )
            input_tokens = metrics.input_tokens if metrics else None
            output_tokens = metrics.output_tokens if metrics else None
            total_tokens = metrics.total_tokens if metrics else None
            llm_calls = metrics.llm_calls if metrics else None
            tools_used = agent_runner.last_tools_used or None

            # Write session log (for all outcomes - audit trail)
            session_path: str | None = None
            if self._session_logger:
                try:
                    session_path = self._session_logger.write_session(
                        name="heartbeat",
                        prompt=heartbeat_prompt,
                        response=response,
                        tools_used=agent_runner.last_tools_used or [],
                        metrics=agent_runner.last_metrics,
                        duration_ms=duration_ms,
                    )
                except Exception as e:
                    logger.warning(f"Failed to write heartbeat session log: {e}")

            # Check for acknowledge_event tool call (takes precedence over HEARTBEAT_OK)
            if self._ack_tool:
                ack = self._ack_tool.get_pending_ack()
                if ack:
                    logger.info(
                        f"Heartbeat acknowledged for '{self.workspace_name}': {ack.reason}"
                    )
                    self.record_heartbeat_event(
                        "acknowledged",
                        reason=ack.reason,
                        duration_ms=duration_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        llm_calls=llm_calls,
                        task_count=task_count,
                        response=response,
                        tools_used=tools_used,
                    )
                    if self._token_logger and metrics:
                        self._token_logger.log(
                            metrics=metrics,
                            workspace=self.workspace_name,
                            invocation_type="heartbeat",
                            session_key=None,
                        )
                    return

            if self.config.suppress_ok and preflight.is_heartbeat_ok(response):
                logger.debug(f"Heartbeat OK for workspace: {self.workspace_name} (suppressed)")
                self.record_heartbeat_event(
                    "heartbeat_ok",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                    response=response,
                    tools_used=tools_used,
                )

                # Log to token_usage.jsonl if available
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=None,
                    )
                return

            if not heartbeat_channel:
                logger.error(
                    f"Heartbeat channel not found: {self.config.target_channel} "
                    f"(workspace: {self.workspace_name})"
                )
                self.record_heartbeat_event(
                    "error",
                    error="channel not found",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                    response=response,
                    tools_used=tools_used,
                )

                # Log to token_usage.jsonl even on error
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=None,
                    )
                return

            if heartbeat_session_key:
                # Delivery routing
                delivery = self.config.delivery

                # Channel delivery ("channel" or "both")
                if delivery in ("channel", "both"):
                    await heartbeat_channel.send_message(session_key=heartbeat_session_key, content=response)
                    logger.info(f"Heartbeat notification sent to {self.config.target_channel}/{heartbeat_session_key}")

                # Agent queue injection ("agent" or "both")
                if delivery in ("agent", "both") and self._result_callback and session_path:
                    try:
                        # Build injection content with truncation
                        output = response
                        if len(output) > INJECTION_TRUNCATION_LIMIT:
                            output = output[:INJECTION_TRUNCATION_LIMIT]
                            injection_content = HEARTBEAT_RESULT_TRUNCATED_TEMPLATE.format(
                                output=output, session_path=session_path,
                            )
                        else:
                            injection_content = HEARTBEAT_RESULT_TEMPLATE.format(
                                output=output, session_path=session_path,
                            )
                        await self._result_callback(heartbeat_session_key, injection_content)
                        logger.info(f"Heartbeat result injected into agent queue for {heartbeat_session_key}")
                    except Exception as e:
                        logger.warning(f"Failed to inject heartbeat result: {e}")

                self.record_heartbeat_event(
                    "ran",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                    response=response,
                    tools_used=tools_used,
                )

                # Log to token_usage.jsonl
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=heartbeat_session_key,
                    )
            else:
                # No routing configured (no target ID or unsupported channel)
                delivery = self.config.delivery
                if delivery in ("agent", "both") and self._result_callback:
                    logger.warning(
                        f"Heartbeat delivery configured for agent injection but no session_key available "
                        f"(workspace: {self.workspace_name}, delivery: {delivery})"
                    )
                else:
                    logger.warning(
                        f"Heartbeat response generated but no routing configured "
                        f"(workspace: {self.workspace_name}, response length: {len(response)})"
                    )

                self.record_heartbeat_event(
                    "ran",
                    reason="no routing configured",
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    llm_calls=llm_calls,
                    task_count=task_count,
                    response=response,
                    tools_used=tools_used,
                )

                # Log to token_usage.jsonl
                if self._token_logger and metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self.workspace_name,
                        invocation_type="heartbeat",
                        session_key=None,
                    )

        except Exception as e:
            duration_ms = (time_module.monotonic() - start_time) * 1000
            logger.error(
                f"Heartbeat check failed for workspace '{self.workspace_name}': {e}",
                exc_info=True,
            )
            self.record_heartbeat_event(
                "error",
                error=str(e),
                duration_ms=duration_ms,
                task_count=task_count,
            )
        finally:
            clear_channel_context()
            # Clear any stale acknowledge state so a failed run cannot bleed
            # into the next heartbeat cycle.
            if self._ack_tool:
                self._ack_tool.reset()

    def record_heartbeat_event(
        self,
        outcome: str,
        reason: str | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_calls: int | None = None,
        task_count: int | None = None,
        response: str | None = None,
        tools_used: list[str] | None = None,
    ) -> None:
        """Append heartbeat event to workspace JSONL log.

        Args:
            outcome: Event outcome (ran, skipped, heartbeat_ok, error).
            reason: Reason for skip or additional context.
            duration_ms: Execution duration in milliseconds.
            error: Error message if applicable.
            input_tokens: Input token count from invocation.
            output_tokens: Output token count from invocation.
            total_tokens: Total token count from invocation.
            llm_calls: Number of LLM calls made.
            task_count: Number of active tasks when heartbeat ran.
            response: Full agent response text.
            tools_used: List of tool names invoked during the heartbeat.
        """
        log_path = self.workspace_path / str(HEARTBEAT_LOG_JSONL)
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "workspace": self.workspace_name,
            "outcome": outcome,
        }
        if reason:
            event["reason"] = reason
        if duration_ms is not None:
            event["duration_ms"] = round(duration_ms, 1)
        if error:
            event["error"] = error
        if input_tokens is not None:
            event["input_tokens"] = input_tokens
        if output_tokens is not None:
            event["output_tokens"] = output_tokens
        if total_tokens is not None:
            event["total_tokens"] = total_tokens
        if llm_calls is not None:
            event["llm_calls"] = llm_calls
        if task_count is not None:
            event["task_count"] = task_count
        if tools_used:
            event["tools_used"] = tools_used
        if response:
            event["response"] = response

        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write heartbeat log: {e}")

    @staticmethod
    def _resolve_heartbeat_session_key(channel: ChannelAdapter, config: HeartbeatConfig) -> str | None:
        """Resolve session key from heartbeat config.

        Uses ``target_id`` (preferred) with fallback to legacy ``target_chat_id``/``target_channel_id``.

        Args:
            channel: The channel adapter instance to build the session key against.
            config: The heartbeat configuration specifying channel name and target ID.

        Returns:
            A session key string, or None if no supported routing config is found.
        """
        target = next(
            (v for v in (config.target_id, config.target_chat_id, config.target_channel_id) if v is not None),
            None,
        )
        if target:
            return channel.build_session_key(target)
        return None
