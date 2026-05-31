"""Cron execution logic for OpenPaw."""

import json
import logging
import time as time_module
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.session_logger import SessionLogger
from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    set_channel_context,
    set_invocation_origin,
)
from openpaw.channels.base import ChannelAdapter
from openpaw.core.config.models import CronDefinition, CronOutputConfig
from openpaw.core.paths import CRON_LOG_JSONL
from openpaw.core.prompts.system_events import (
    CRON_RESULT_TEMPLATE,
    CRON_RESULT_TRUNCATED_TEMPLATE,
    DYNAMIC_TASK_RESULT_TEMPLATE,
    DYNAMIC_TASK_RESULT_TRUNCATED_TEMPLATE,
    INJECTION_TRUNCATION_LIMIT,
)
from openpaw.model.cron import DynamicCronTask
from openpaw.stores.cron import DynamicCronStore

logger = logging.getLogger(__name__)


class CronExecutor:
    """Executes cron jobs and dynamic tasks, handling logging and delivery."""

    def __init__(
        self,
        workspace_path: Path,
        agent_factory: Callable[..., Any],
        channels: Mapping[str, ChannelAdapter],
        workspace_name: str,
        token_logger: TokenUsageLogger | None,
        session_logger: SessionLogger | None,
        result_callback: Callable[[str, str], Awaitable[None]] | None,
        dynamic_store: DynamicCronStore,
        dynamic_jobs: dict[str, Any],
    ):
        self.workspace_path = Path(workspace_path)
        self.agent_factory = agent_factory
        self.channels = channels
        self._workspace_name = workspace_name
        self._token_logger = token_logger
        self._session_logger = session_logger
        self._result_callback = result_callback
        self._dynamic_store = dynamic_store
        self._dynamic_jobs = dynamic_jobs
        self._running_jobs: set[str] = set()

    async def execute_cron(self, cron: CronDefinition) -> None:
        """Execute a cron job.

        Args:
            cron: The cron definition to execute.
        """
        job_id = cron.name
        if job_id in self._running_jobs:
            logger.warning(f"Skipping cron job {cron.name}: previous execution still running")
            return

        self._running_jobs.add(job_id)
        logger.info(f"Executing cron job: {cron.name}")
        set_invocation_origin(f"cron:{cron.name}")

        # Set up channel context so send_message/send_file work during cron execution
        cron_channel = self.channels.get(cron.output.channel)
        cron_session_key = self._resolve_session_key(cron_channel, cron.output) if cron_channel else None
        if cron_channel and cron_session_key:
            set_channel_context(cron_channel, cron_session_key)

        try:
            # Resolve max_output_tokens: per-cron definition takes precedence over
            # the workspace-level default already baked into the factory's
            # extra_model_kwargs. Passing it as extra_overrides lets the
            # cron-specific cap win without mutating factory state.
            extra_overrides: dict[str, Any] = {}
            if cron.max_output_tokens is not None:
                extra_overrides["max_tokens"] = cron.max_output_tokens

            agent_runner = (
                self.agent_factory(extra_overrides=extra_overrides)
                if extra_overrides
                else self.agent_factory()
            )

            start_time = time_module.monotonic()
            response = await agent_runner.run(message=cron.prompt)
            duration_ms = (time_module.monotonic() - start_time) * 1000

            # Log a warning when the output cap was hit — response is likely truncated
            cron_metrics_check = agent_runner.last_metrics
            cron_cap = agent_runner.max_output_tokens
            if (
                isinstance(cron_cap, int)
                and cron_metrics_check
                and isinstance(cron_metrics_check.output_tokens, int)
                and cron_metrics_check.output_tokens >= cron_cap
            ):
                logger.warning(
                    f"Cron '{cron.name}' output token cap reached: "
                    f"{cron_metrics_check.output_tokens}/{cron_cap} tokens "
                    f"— response likely truncated (workspace: {self._workspace_name})"
                )

            # Write session log
            session_path: str | None = None
            if self._session_logger:
                try:
                    session_path = self._session_logger.write_session(
                        name=cron.name,
                        prompt=cron.prompt,
                        response=response,
                        tools_used=agent_runner.last_tools_used or [],
                        metrics=agent_runner.last_metrics,
                        duration_ms=duration_ms,
                    )
                except Exception as e:
                    logger.warning(f"Failed to write cron session log for {cron.name}: {e}")

            delivery = cron.output.delivery

            # Channel delivery ("channel" or "both")
            if delivery in ("channel", "both"):
                channel = self.channels.get(cron.output.channel)
                if not channel:
                    logger.error(f"Channel not found for cron {cron.name}: {cron.output.channel}")
                else:
                    session_key = self._resolve_session_key(channel, cron.output)
                    if session_key:
                        await channel.send_message(session_key=session_key, content=response)
                    else:
                        logger.warning(f"Unsupported output config for cron {cron.name}: {cron.output}")

            # Agent queue injection ("agent" or "both")
            if delivery in ("agent", "both") and self._result_callback and session_path:
                try:
                    channel = self.channels.get(cron.output.channel)
                    session_key = self._resolve_session_key(channel, cron.output) if channel else None
                    if channel and session_key:
                        output = response
                        if len(output) > INJECTION_TRUNCATION_LIMIT:
                            output = output[:INJECTION_TRUNCATION_LIMIT]
                            injection_content = CRON_RESULT_TRUNCATED_TEMPLATE.format(
                                cron_name=cron.name, output=output, session_path=session_path,
                            )
                        else:
                            injection_content = CRON_RESULT_TEMPLATE.format(
                                cron_name=cron.name, output=output, session_path=session_path,
                            )
                        await self._result_callback(session_key, injection_content)
                        logger.info(f"Cron {cron.name} result injected into agent queue")
                except Exception as e:
                    logger.warning(f"Failed to inject cron result for {cron.name}: {e}")

            # Log token usage for cron invocation
            metrics = agent_runner.last_metrics
            if self._token_logger and self._workspace_name and metrics:
                self._token_logger.log(
                    metrics=metrics,
                    workspace=self._workspace_name,
                    invocation_type="cron",
                    session_key=None,
                )

            self.log_cron_event(
                cron_name=cron.name,
                outcome="completed",
                duration_ms=duration_ms,
                input_tokens=metrics.input_tokens if metrics else None,
                output_tokens=metrics.output_tokens if metrics else None,
                total_tokens=metrics.total_tokens if metrics else None,
                llm_calls=metrics.llm_calls if metrics else None,
                session_path=session_path,
                delivery=delivery,
                tools_used=agent_runner.last_tools_used or None,
            )

            logger.info(f"Cron job {cron.name} completed successfully")

        except Exception as e:
            logger.error(f"Failed to execute cron job {cron.name}: {e}", exc_info=True)
            self.log_cron_event(
                cron_name=cron.name,
                outcome="error",
                error=str(e),
            )
        finally:
            self._running_jobs.discard(job_id)
            clear_channel_context()

    @staticmethod
    def _resolve_session_key(channel: ChannelAdapter, output: CronOutputConfig) -> str | None:
        """Resolve session key from cron output config.

        Uses ``target_id`` (preferred) with fallback to legacy ``chat_id``/``channel_id``.

        Args:
            channel: The channel adapter instance to build the session key against.
            output: The cron output config specifying channel name and target ID.

        Returns:
            A session key string, or None if no supported routing config is found.
        """
        target = next(
            (v for v in (output.target_id, output.chat_id, output.channel_id) if v is not None),
            None,
        )
        if target:
            return channel.build_session_key(target)
        return None

    def log_cron_event(
        self,
        cron_name: str,
        outcome: str,
        duration_ms: float | None = None,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_calls: int | None = None,
        session_path: str | None = None,
        delivery: str | None = None,
        tools_used: list[str] | None = None,
    ) -> None:
        """Append cron execution event to workspace JSONL log.

        Args:
            cron_name: Name of the cron job (or "dynamic_<id[:8]>" for dynamic tasks).
            outcome: Execution outcome: "completed", "error", or "skipped".
            duration_ms: Execution duration in milliseconds.
            error: Error message if outcome is "error".
            input_tokens: Input token count from the agent invocation.
            output_tokens: Output token count from the agent invocation.
            total_tokens: Total token count from the agent invocation.
            llm_calls: Number of LLM calls made during execution.
            session_path: Relative path to the session log file, if written.
            delivery: Delivery mode used ("channel" or "agent").
            tools_used: List of tool names invoked during execution.
        """
        log_path = self.workspace_path / str(CRON_LOG_JSONL)
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "workspace": self._workspace_name,
            "cron_name": cron_name,
            "outcome": outcome,
        }
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
        if session_path:
            event["session_path"] = session_path
        if delivery:
            event["delivery"] = delivery
        if tools_used:
            event["tools_used"] = tools_used

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write cron log: {e}")

    async def execute_dynamic_task(self, task: DynamicCronTask) -> None:
        """Execute a dynamic task.

        For one-shot tasks: remove after execution.
        For interval tasks: continue recurring.

        Args:
            task: DynamicCronTask to execute.
        """
        job_id = f"dynamic_{task.id}"
        if job_id in self._running_jobs:
            logger.warning(f"Skipping dynamic task {task.id}: previous execution still running")
            return

        self._running_jobs.add(job_id)

        # Remove one-shot tasks from store before execution.
        # APScheduler DateTrigger guarantees single fire, so this is safe.
        # Prevents list_scheduled() from showing ghost entries during execution.
        if task.task_type == "once":
            self._dynamic_store.remove_task(task.id)
            if task.id in self._dynamic_jobs:
                del self._dynamic_jobs[task.id]

        logger.info(f"Executing dynamic task: {task.id}")
        set_invocation_origin(f"dynamic_cron:{task.id[:8]}")

        # Set up channel context so send_message/send_file work during execution
        if task.channel and task.chat_id:
            dyn_channel = self.channels.get(task.channel)
            if dyn_channel:
                set_channel_context(dyn_channel, dyn_channel.build_session_key(task.chat_id))

        try:
            agent_runner = self.agent_factory()
            start_time = time_module.monotonic()
            response = await agent_runner.run(message=task.prompt)
            duration_ms = (time_module.monotonic() - start_time) * 1000

            # Write session log
            session_path: str | None = None
            if self._session_logger:
                try:
                    session_path = self._session_logger.write_session(
                        name=f"dynamic_{task.id}",
                        prompt=task.prompt,
                        response=response,
                        tools_used=agent_runner.last_tools_used or [],
                        metrics=agent_runner.last_metrics,
                        duration_ms=duration_ms,
                    )
                except Exception as e:
                    logger.warning(f"Failed to write session log for dynamic task {task.id}: {e}")

            # Log token usage for dynamic cron invocation
            dyn_metrics = agent_runner.last_metrics
            if self._token_logger and self._workspace_name and dyn_metrics:
                self._token_logger.log(
                    metrics=dyn_metrics,
                    workspace=self._workspace_name,
                    invocation_type="cron",
                    session_key=None,
                )

            # Route response using task's stored routing info
            if task.channel and task.chat_id:
                channel = self.channels.get(task.channel)
                if channel:
                    # Guard against empty responses
                    if response and response.strip():
                        session_key = channel.build_session_key(task.chat_id)
                        await channel.send_message(
                            session_key=session_key,
                            content=response,
                        )
                        logger.info(f"Dynamic task {task.id} response sent to {task.channel}:{task.chat_id}")
                    else:
                        logger.warning(f"Dynamic task {task.id} produced empty response, not sending")
                else:
                    logger.warning(f"Channel '{task.channel}' not found for dynamic task {task.id}")
            else:
                logger.warning(
                    f"Dynamic task {task.id} has no routing config. "
                    f"Response ({len(response) if response else 0} chars) not sent."
                )

            # Inject result into agent queue (dynamic tasks always notify the main agent)
            if self._result_callback and session_path and task.channel and task.chat_id:
                try:
                    channel = self.channels.get(task.channel)
                    if channel:
                        session_key = channel.build_session_key(task.chat_id)
                        output = response
                        if len(output) > INJECTION_TRUNCATION_LIMIT:
                            output = output[:INJECTION_TRUNCATION_LIMIT]
                            injection_content = DYNAMIC_TASK_RESULT_TRUNCATED_TEMPLATE.format(
                                task_id=task.id[:8],
                                prompt_preview=task.prompt[:80],
                                output=output,
                                session_path=session_path,
                            )
                        else:
                            injection_content = DYNAMIC_TASK_RESULT_TEMPLATE.format(
                                task_id=task.id[:8],
                                prompt_preview=task.prompt[:80],
                                output=output,
                                session_path=session_path,
                            )
                        await self._result_callback(session_key, injection_content)
                        logger.info(f"Dynamic task {task.id} result injected into agent queue")
                except Exception as e:
                    logger.warning(f"Failed to inject dynamic task result for {task.id}: {e}")

            self.log_cron_event(
                cron_name=f"dynamic_{task.id[:8]}",
                outcome="completed",
                duration_ms=duration_ms,
                input_tokens=dyn_metrics.input_tokens if dyn_metrics else None,
                output_tokens=dyn_metrics.output_tokens if dyn_metrics else None,
                total_tokens=dyn_metrics.total_tokens if dyn_metrics else None,
                llm_calls=dyn_metrics.llm_calls if dyn_metrics else None,
                session_path=session_path,
                tools_used=agent_runner.last_tools_used or None,
            )

            logger.info(f"Dynamic task {task.id} completed successfully")

        except Exception as e:
            logger.error(f"Dynamic task {task.id} failed: {e}", exc_info=True)
            self.log_cron_event(
                cron_name=f"dynamic_{task.id[:8]}",
                outcome="error",
                error=str(e),
            )
        finally:
            self._running_jobs.discard(job_id)
            clear_channel_context()
