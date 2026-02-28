"""CLI interface for OpenPaw."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import yaml

from openpaw.core.config import load_config
from openpaw.core.logging import setup_logging
from openpaw.runtime.orchestrator import OpenPawOrchestrator

logger = logging.getLogger(__name__)


def parse_workspace_arg(value: str, workspaces_path: Path) -> list[str]:
    """Parse workspace argument into list of workspace names.

    Args:
        value: Workspace argument value (single name, comma-separated, or "*").
        workspaces_path: Path to workspaces directory.

    Returns:
        List of workspace names to load.
    """
    value = value.strip()

    if value in ("*", "all"):
        return OpenPawOrchestrator.discover_workspaces(workspaces_path)

    # Comma-separated list
    return [w.strip() for w in value.split(",") if w.strip()]


async def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="OpenPaw - AI Agent Framework")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to configuration file",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        type=str,
        help="Workspace(s) to load: single name, comma-separated, or '*' for all",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Load all available workspaces",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    config = load_config(args.config)

    # Initialize logging from config
    log_level = "DEBUG" if args.verbose else config.logging.level
    setup_logging(
        level=log_level,
        directory=config.logging.directory,
        max_size_mb=config.logging.max_size_mb,
        backup_count=config.logging.backup_count,
    )

    # Determine which workspaces to load
    if args.all:
        workspaces = OpenPawOrchestrator.discover_workspaces(config.workspaces_path)
    elif args.workspace:
        workspaces = parse_workspace_arg(args.workspace, config.workspaces_path)
    else:
        parser.error("Either --workspace or --all is required")

    if not workspaces:
        logger.error("No workspaces found to load")
        return

    orchestrator = OpenPawOrchestrator(config, workspaces)

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        stop_event.set()

    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    await orchestrator.start()
    await stop_event.wait()
    await orchestrator.stop()


def run() -> None:
    """Entry point for poetry scripts."""
    # Early dispatch for init/list commands — no async or heavy imports needed.
    if len(sys.argv) >= 2 and sys.argv[1] in ("init", "list"):
        from openpaw.cli_init import dispatch_command

        dispatch_command(sys.argv[1], sys.argv[2:])
        return

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Invalid YAML in config: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Startup failed: {e}\nUse -v for verbose logging.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
