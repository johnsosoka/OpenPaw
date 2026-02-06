"""Logging configuration and setup for OpenPaw."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    directory: str | Path = "logs",
    max_size_mb: int = 10,
    backup_count: int = 5,
) -> None:
    """Configure root logger with file and console handlers.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        directory: Directory for log files.
        max_size_mb: Maximum size in MB before rotation.
        backup_count: Number of backup files to keep.
    """
    log_dir = Path(directory)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Set root level
    root_logger.setLevel(getattr(logging, level.upper()))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper()))
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Main orchestrator file handler
    main_log_file = log_dir / "openpaw.log"
    file_handler = RotatingFileHandler(
        main_log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, level.upper()))
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    logging.info(f"Logging initialized: level={level}, directory={log_dir}")


def setup_workspace_logger(
    workspace_name: str,
    directory: str | Path = "logs",
    max_size_mb: int = 10,
    backup_count: int = 5,
) -> logging.Logger:
    """Create a workspace-specific logger with its own log file.

    Args:
        workspace_name: Name of the workspace.
        directory: Directory for log files.
        max_size_mb: Maximum size in MB before rotation.
        backup_count: Number of backup files to keep.

    Returns:
        Configured logger instance for the workspace.
    """
    log_dir = Path(directory)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create workspace-specific logger
    logger_name = f"openpaw.workspace.{workspace_name}"
    workspace_logger = logging.getLogger(logger_name)

    # Prevent duplicate handlers if logger already exists
    if workspace_logger.handlers:
        return workspace_logger

    # Don't propagate to root (we want separate files)
    workspace_logger.propagate = False

    # Set logger level to inherit from root
    workspace_logger.setLevel(logging.NOTSET)

    # Workspace-specific file handler
    workspace_log_file = log_dir / f"{workspace_name}.log"
    file_handler = RotatingFileHandler(
        workspace_log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.NOTSET)

    # Include workspace name in format
    file_formatter = logging.Formatter(
        f"%(asctime)s - [{workspace_name}] %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    workspace_logger.addHandler(file_handler)

    # Also add console handler for workspace logger
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.NOTSET)
    console_formatter = logging.Formatter(
        f"%(asctime)s - [{workspace_name}] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    workspace_logger.addHandler(console_handler)

    return workspace_logger


def get_workspace_logger(workspace_name: str) -> logging.Logger:
    """Get the logger for a specific workspace.

    Args:
        workspace_name: Name of the workspace.

    Returns:
        Logger instance for the workspace.
    """
    logger_name = f"openpaw.workspace.{workspace_name}"
    return logging.getLogger(logger_name)
