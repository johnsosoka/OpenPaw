"""Test that workspace tools can import sibling modules."""

from pathlib import Path

from openpaw.workspace.tool_loader import _load_module_from_file


def test_load_module_from_file_sibling_import(tmp_path: Path) -> None:
    """Tools can import from sibling files in the same directory."""
    # Arrange
    helper = tmp_path / "helper.py"
    helper.write_text("def greet() -> str:\n    return 'hello'\n")

    tool_file = tmp_path / "my_tool.py"
    tool_file.write_text(
        "from langchain_core.tools import tool\n"
        "from helper import greet\n"
        "\n"
        "@tool\n"
        "def say_hello() -> str:\n"
        "    '''Say hello using the helper module.'''\n"
        "    return greet()\n"
    )

    # Act
    module = _load_module_from_file(tool_file)

    # Assert
    assert module is not None
    assert hasattr(module, "say_hello")
    assert module.say_hello.invoke({}) == "hello"
