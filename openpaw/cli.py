"""CLI interface for OpenPaw."""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from openpaw.api.app import attach_orchestrator, create_app
from openpaw.core.config import Config, load_config
from openpaw.db.database import init_db_manager
from openpaw.orchestrator import OpenPawOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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


async def run_migrate(args: argparse.Namespace) -> None:
    """Handle database migration commands."""
    if args.init:
        logger.info("Initializing database...")
        db_manager = init_db_manager(args.db_path)
        try:
            await db_manager.init_db()
            logger.info(f"Database initialized successfully at {args.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            sys.exit(1)
        finally:
            await db_manager.close()
    elif args.import_config or args.import_workspaces or args.verify:
        # Import migration service and dependencies
        from openpaw.api.services.encryption import EncryptionService
        from openpaw.api.services.migration_service import MigrationService
        from openpaw.db.database import get_async_session

        # Get database session and run migration
        encryption = EncryptionService()

        async for session in get_async_session():
            migration_service = MigrationService(session, encryption)

            try:
                # Handle import config
                if args.import_config:
                    config_path = Path(args.import_config)
                    logger.info(f"Importing global config from {config_path}...")
                    result = await migration_service.import_global_config(
                        config_path, overwrite=args.overwrite
                    )
                    logger.info(
                        f"Import complete: {result.imported} imported, "
                        f"{result.skipped} skipped, {len(result.errors)} errors"
                    )
                    if result.errors:
                        for error in result.errors:
                            logger.error(f"  - {error}")

                # Handle import workspaces
                if args.import_workspaces:
                    config = load_config(args.config or Path("config.yaml"))
                    workspaces_path = config.workspaces_path
                    logger.info(f"Importing all workspaces from {workspaces_path}...")
                    results = await migration_service.import_all_workspaces(
                        workspaces_path, overwrite=args.overwrite
                    )
                    total_imported = sum(r.imported for r in results.values())
                    total_skipped = sum(r.skipped for r in results.values())
                    total_errors = sum(len(r.errors) for r in results.values())
                    logger.info(
                        f"Import complete: {total_imported} imported, "
                        f"{total_skipped} skipped, {total_errors} errors"
                    )
                    for workspace_name, result in results.items():
                        if result.errors:
                            logger.error(f"Errors in {workspace_name}:")
                            for error in result.errors:
                                logger.error(f"  - {error}")

                # Handle verify
                if args.verify:
                    config = load_config(args.config or Path("config.yaml"))
                    config_path = args.config or Path("config.yaml")
                    workspaces_path = config.workspaces_path
                    logger.info("Verifying migration...")
                    result = await migration_service.verify_migration(
                        config_path, workspaces_path
                    )
                    if result.matches:
                        logger.info("Verification successful: Database matches YAML config")
                    else:
                        logger.warning("Verification failed: Differences found")
                        for diff in result.differences:
                            logger.warning(f"  - {diff}")

            except Exception as e:
                logger.error(f"Migration failed: {e}")
                sys.exit(1)

            # Only use first session
            break
    else:
        logger.error(
            "No migration action specified. Use --init, --import-config, "
            "--import-workspaces, or --verify"
        )
        sys.exit(1)


async def run_api_server(
    args: argparse.Namespace,
    config: Config,
    workspaces: list[str] | None = None,
) -> None:
    """Start the FastAPI server with optional orchestrator."""
    # Create the FastAPI app
    app_config = {
        "db_path": args.db_path,
        "workspaces_path": config.workspaces_path,
        "orchestrator": None,
    }
    app = create_app(app_config)

    # If workspaces are specified, start the orchestrator
    orchestrator = None
    if workspaces:
        logger.info(f"Starting orchestrator with workspaces: {workspaces}")
        orchestrator = OpenPawOrchestrator(config, workspaces)
        attach_orchestrator(app, orchestrator)

    # Configure uvicorn server
    uvicorn_config = uvicorn.Config(
        app,
        host=args.api_host,
        port=args.api_port,
        log_level="info" if not args.verbose else "debug",
    )
    server = uvicorn.Server(uvicorn_config)

    # Setup signal handlers for graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    # Start orchestrator if present
    if orchestrator:
        await orchestrator.start()

    # Run server in background task
    server_task = asyncio.create_task(server.serve())

    try:
        # Wait for shutdown signal
        await stop_event.wait()
        logger.info("Shutdown signal received, stopping...")
    finally:
        # Graceful shutdown
        if orchestrator:
            await orchestrator.stop()

        # Stop uvicorn server
        server.should_exit = True
        await server_task


async def run_orchestrator_only(
    config: Config,
    workspaces: list[str],
) -> None:
    """Run orchestrator without API server (original behavior)."""
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


async def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="OpenPaw - AI Agent Framework")

    # Add subparsers for commands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Migrate subcommand
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Database migration commands",
    )
    migrate_parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize the database (create tables)",
    )
    migrate_parser.add_argument(
        "--import-config",
        type=str,
        metavar="PATH",
        help="Import global config.yaml settings to database",
    )
    migrate_parser.add_argument(
        "--import-workspaces",
        action="store_true",
        help="Import all workspaces from agent_workspaces directory",
    )
    migrate_parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify database matches YAML configuration",
    )
    migrate_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing database records during import",
    )
    migrate_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to configuration file (for import-workspaces and verify)",
    )
    migrate_parser.add_argument(
        "--db-path",
        type=str,
        default="openpaw.db",
        help="Path to SQLite database (default: openpaw.db)",
    )

    # Main command arguments (when no subcommand)
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

    # API server flags
    parser.add_argument(
        "--api",
        action="store_true",
        help="Start FastAPI management server",
    )
    parser.add_argument(
        "--api-host",
        type=str,
        default="127.0.0.1",
        help="API server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8000,
        help="API server port (default: 8000)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="openpaw.db",
        help="Path to SQLite database (default: openpaw.db)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle migrate subcommand
    if args.command == "migrate":
        await run_migrate(args)
        return

    # For main command, load config
    config = load_config(args.config)

    # Determine which workspaces to load
    workspaces: list[str] | None = None
    if args.all:
        workspaces = OpenPawOrchestrator.discover_workspaces(config.workspaces_path)
    elif args.workspace:
        workspaces = parse_workspace_arg(args.workspace, config.workspaces_path)

    # Handle API server mode
    if args.api:
        # API mode allows running without workspaces (management only)
        # or with workspaces (management + agent orchestration)
        await run_api_server(args, config, workspaces)
        return

    # Original orchestrator-only mode
    if not workspaces:
        parser.error("Either --workspace, --all, or --api is required")

    if not workspaces:
        logger.error("No workspaces found to load")
        return

    await run_orchestrator_only(config, workspaces)


def run() -> None:
    """Entry point for poetry scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
