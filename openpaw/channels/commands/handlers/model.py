"""Model switching command handler."""

from typing import TYPE_CHECKING

from openpaw.channels.commands.base import CommandDefinition, CommandHandler, CommandResult

if TYPE_CHECKING:
    from openpaw.channels.base import Message
    from openpaw.channels.commands.base import CommandContext


class ModelCommand(CommandHandler):
    """Show or switch the active LLM model."""

    @property
    def definition(self) -> CommandDefinition:
        return CommandDefinition(
            name="model",
            description="Show or switch the active model",
            args_description="[provider:model | reset]",
        )

    async def handle(
        self,
        message: "Message",
        args: str,
        context: "CommandContext",
    ) -> CommandResult:
        args = args.strip()

        if not args:
            return self._show_current(context)

        if args.lower() == "reset":
            return self._reset_model(context)

        return self._switch_model(args, context)

    def _show_current(self, context: "CommandContext") -> CommandResult:
        if not context.agent_factory:
            return CommandResult(response=f"Model: {context.agent_runner.model_id}")

        factory = context.agent_factory
        active = factory.active_model
        configured = factory.configured_model

        lines = [f"Active model: {active}"]
        if active != configured:
            lines.append(f"Configured model: {configured}")
            lines.append("Use /model reset to revert.")

        return CommandResult(response="\n".join(lines))

    def _reset_model(self, context: "CommandContext") -> CommandResult:
        if not context.agent_factory:
            return CommandResult(response="Model switching not available.")

        factory = context.agent_factory
        if factory.active_model == factory.configured_model:
            return CommandResult(response=f"Already using configured model: {factory.configured_model}")

        factory.clear_runtime_override()
        context.agent_runner.update_model(
            model=factory.configured_model,
            api_key=factory._api_key,
        )
        return CommandResult(response=f"Reverted to configured model: {factory.configured_model}")

    def _switch_model(self, model_str: str, context: "CommandContext") -> CommandResult:
        if not context.agent_factory:
            return CommandResult(response="Model switching not available.")

        factory = context.agent_factory

        valid, message = factory.validate_model(model_str)
        if not valid:
            return CommandResult(response=f"Cannot switch: {message}")

        from openpaw.workspace.agent_factory import RuntimeModelOverride

        override = RuntimeModelOverride(model=model_str)
        factory.set_runtime_override(override)

        api_key = factory._resolve_api_key(model_str)
        context.agent_runner.update_model(
            model=model_str,
            api_key=api_key,
        )

        return CommandResult(response=f"Switched to: {model_str}")
