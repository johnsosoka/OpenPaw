"""Sync __version__ in openpaw/__init__.py with pyproject.toml."""

import argparse
import pathlib
import re
import sys


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
INIT_PATH = PROJECT_ROOT / "openpaw" / "__init__.py"


def extract_version(pyproject_text: str) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
    if not match:
        print("ERROR: Could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def extract_init_version(init_text: str) -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not match:
        print("ERROR: Could not find __version__ in openpaw/__init__.py", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def write_version(version: str) -> None:
    INIT_PATH.write_text(
        f'"""OpenPaw - AI Agent Framework with DeepAgents and Multi-Channel Support."""\n\n'
        f'__version__ = "{version}"\n'
        f'__all__ = ["__version__"]\n',
        encoding="utf-8",
    )
    print(f"Updated {INIT_PATH} to version {version}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync version from pyproject.toml to openpaw/__init__.py")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if versions do not match")
    args = parser.parse_args()

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    toml_version = extract_version(pyproject_text)

    if args.check:
        init_text = INIT_PATH.read_text(encoding="utf-8")
        init_version = extract_init_version(init_text)
        if toml_version != init_version:
            print(
                f"ERROR: Version mismatch: pyproject.toml={toml_version}, "
                f"openpaw/__init__.py={init_version}",
                file=sys.stderr,
            )
            return 1
        print(f"Versions match: {toml_version}")
        return 0

    write_version(toml_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
