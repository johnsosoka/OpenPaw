"""Dynamic tool loader for workspace-defined LangChain tools."""

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

REQUIREMENTS_FILE = "requirements.txt"


def load_workspace_tools(tools_path: Path, auto_install: bool = True) -> list[BaseTool]:
    """Load LangChain tools from a workspace's tools/ directory.

    Dynamically imports Python files from the tools directory and collects
    any objects that are instances of LangChain's BaseTool (including @tool
    decorated functions which become StructuredTool instances).

    If a requirements.txt file exists in the tools directory, dependencies
    will be checked and optionally installed before loading tools.

    Args:
        tools_path: Path to the workspace's tools/ directory.
        auto_install: If True, automatically install missing dependencies
            from requirements.txt. If False, just warn about missing deps.

    Returns:
        List of BaseTool instances found in the tools directory.
        Empty list if directory doesn't exist or contains no tools.

    Example:
        A tools/calendar.py file containing:

            from langchain_core.tools import tool

            @tool
            def get_calendar_events(date: str) -> str:
                '''Get calendar events for a specific date.'''
                return fetch_events(date)

        Will be loaded and the get_calendar_events tool made available to the agent.
    """
    tools: list[BaseTool] = []

    if not tools_path.exists():
        logger.debug(f"Tools directory does not exist: {tools_path}")
        return tools

    if not tools_path.is_dir():
        logger.warning(f"Tools path is not a directory: {tools_path}")
        return tools

    # Check and install requirements if requirements.txt exists
    requirements_file = tools_path / REQUIREMENTS_FILE
    if requirements_file.exists():
        _handle_requirements(requirements_file, auto_install)

    for py_file in sorted(tools_path.glob("*.py")):
        # Skip private/internal modules
        if py_file.name.startswith("_"):
            continue

        try:
            module = _load_module_from_file(py_file)
            file_tools = _extract_tools_from_module(module)
            tools.extend(file_tools)

            if file_tools:
                tool_names = [t.name for t in file_tools]
                logger.info(f"Loaded {len(file_tools)} tools from {py_file.name}: {tool_names}")

        except Exception as e:
            logger.error(f"Failed to load tools from {py_file.name}: {e}")
            continue

    return tools


def _handle_requirements(requirements_file: Path, auto_install: bool) -> None:
    """Check and optionally install dependencies from requirements.txt.

    Args:
        requirements_file: Path to the requirements.txt file.
        auto_install: If True, install missing packages. If False, just warn.
    """
    missing = _check_requirements(requirements_file)

    if not missing:
        logger.debug(f"All requirements satisfied for {requirements_file.parent.name}")
        return

    if auto_install:
        logger.info(f"Installing {len(missing)} missing dependencies: {missing}")
        _install_requirements(requirements_file)
    else:
        logger.warning(
            f"Missing dependencies for workspace tools: {missing}. "
            f"Install with: pip install -r {requirements_file}"
        )


def _check_requirements(requirements_file: Path) -> list[str]:
    """Check which packages from requirements.txt are not installed.

    Args:
        requirements_file: Path to the requirements.txt file.

    Returns:
        List of package names that are not installed.
    """
    missing: list[str] = []

    try:
        content = requirements_file.read_text()
    except Exception as e:
        logger.error(f"Failed to read requirements file: {e}")
        return missing

    for line in content.strip().splitlines():
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Extract package name (handle version specifiers)
        # e.g., "icalendar>=5.0" -> "icalendar"
        package_name = _extract_package_name(line)

        if not _is_package_installed(package_name):
            missing.append(package_name)

    return missing


def _extract_package_name(requirement: str) -> str:
    """Extract package name from a requirement specifier.

    Args:
        requirement: Requirement line like "package>=1.0" or "package[extra]"

    Returns:
        The base package name.
    """
    # Remove extras like [extra1,extra2]
    name = requirement.split("[")[0]

    # Remove version specifiers
    for sep in [">=", "<=", "==", "!=", ">", "<", "~="]:
        name = name.split(sep)[0]

    return name.strip()


def _is_package_installed(package_name: str) -> bool:
    """Check if a package is installed.

    Args:
        package_name: Name of the package to check.

    Returns:
        True if installed, False otherwise.
    """
    try:
        __import__(package_name.replace("-", "_"))
        return True
    except ImportError:
        pass

    # Some packages have different import names, try importlib.metadata
    try:
        from importlib.metadata import distribution
        distribution(package_name)
        return True
    except Exception:
        return False


def _install_requirements(requirements_file: Path) -> bool:
    """Install packages from requirements.txt using pip.

    Args:
        requirements_file: Path to the requirements.txt file.

    Returns:
        True if installation succeeded, False otherwise.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file), "-q"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error(f"pip install failed: {result.stderr}")
            return False

        logger.info(f"Successfully installed dependencies from {requirements_file}")
        return True

    except subprocess.TimeoutExpired:
        logger.error("pip install timed out after 120 seconds")
        return False
    except Exception as e:
        logger.error(f"Failed to install requirements: {e}")
        return False


def _load_module_from_file(file_path: Path) -> ModuleType:
    """Dynamically import a Python module from a file path.

    Args:
        file_path: Path to the Python file.

    Returns:
        The loaded module.

    Raises:
        ImportError: If the module cannot be loaded.
    """
    # Create a unique module name to avoid collisions
    module_name = f"openpaw_workspace_tool_{file_path.stem}"

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {file_path}")

    module = importlib.util.module_from_spec(spec)

    # Add to sys.modules so imports within the module work
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Clean up on failure
        sys.modules.pop(module_name, None)
        raise ImportError(f"Failed to execute module {file_path}: {e}") from e

    return module


def _extract_tools_from_module(module: ModuleType) -> list[BaseTool]:
    """Extract all BaseTool instances from a loaded module.

    Finds both class instances and @tool decorated functions.

    Args:
        module: The loaded Python module.

    Returns:
        List of BaseTool instances found in the module.
    """
    tools: list[BaseTool] = []

    for name in dir(module):
        # Skip private attributes
        if name.startswith("_"):
            continue

        obj = getattr(module, name)

        # Check if it's a BaseTool instance (includes @tool decorated functions)
        if isinstance(obj, BaseTool):
            tools.append(obj)

    return tools
