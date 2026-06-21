"""Shared fixtures for channel tests.

The discord package is an optional dependency that may not be installed in
every test environment. This conftest stubs it into sys.modules before any
test module imports openpaw.channels.discord, so the entire test suite runs
without requiring the real discord.py wheel.
"""

import sys
import types


def _build_discord_stub() -> None:
    """Populate sys.modules with a minimal discord stub."""
    if "discord" in sys.modules:
        return

    discord = types.ModuleType("discord")

    # Simple type stubs for all names referenced at module / class-body level
    for name in (
        "Intents",
        "Client",
        "Message",
        "File",
        "Interaction",
        "NotFound",
        "Forbidden",
        "HTTPException",
        "TextChannel",
        "DMChannel",
        "Thread",
    ):
        setattr(discord, name, type(name, (), {}))

    # discord.Object is used in fetch_channel_history for pagination;
    # it must accept an `id` keyword argument.
    class _Object:
        def __init__(self, *, id: int) -> None:
            self.id = id

    discord.Object = _Object  # type: ignore[attr-defined]

    # Intents.default() must return an instance
    discord.Intents.default = classmethod(lambda cls: cls())  # type: ignore[attr-defined]

    # ButtonStyle is used as ButtonStyle.success / ButtonStyle.danger at class-body time
    class ButtonStyle:
        success = 1
        danger = 2

    discord.ButtonStyle = ButtonStyle  # type: ignore[attr-defined]

    # discord.ui sub-module
    ui = types.ModuleType("discord.ui")

    class _BaseView:
        """Minimal View base so _ApprovalView can subclass it safely."""

        def __init_subclass__(cls, **kwargs: object) -> None:  # noqa: D401
            pass

        def __init__(self, timeout: float | None = None) -> None:
            self.children: list = []

        def stop(self) -> None:
            pass

    ui.View = _BaseView  # type: ignore[attr-defined]
    ui.Button = type("Button", (), {"disabled": False})  # type: ignore[attr-defined]
    # @discord.ui.button(...) is used as a decorator — return identity function
    ui.button = lambda **kw: (lambda f: f)  # type: ignore[attr-defined]
    discord.ui = ui  # type: ignore[attr-defined]

    # discord.app_commands sub-module
    app_commands = types.ModuleType("discord.app_commands")
    app_commands.CommandTree = type("CommandTree", (), {})  # type: ignore[attr-defined]
    app_commands.Command = type("Command", (), {})  # type: ignore[attr-defined]
    discord.app_commands = app_commands  # type: ignore[attr-defined]

    sys.modules["discord"] = discord
    sys.modules["discord.app_commands"] = app_commands
    sys.modules["discord.ui"] = ui


# Apply the stub immediately when conftest is loaded (before any test imports)
_build_discord_stub()
