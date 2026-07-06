"""Data models for the md2pdf builtin tool."""

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Md2pdfInput(BaseModel):
    """Input schema for the markdown_to_pdf tool."""

    source_path: str = Field(
        description="Path to the markdown file to convert (relative to workspace root)"
    )
    output_path: str | None = Field(
        default=None,
        description=(
            "Output PDF path (relative to workspace). "
            "Defaults to the same name as the source file with a .pdf extension."
        ),
    )
    theme: str | None = Field(
        default=None,
        description=(
            "CSS theme name. Valid values: "
            "'minimal' (clean serif font, light styling, academic feel), "
            "'professional' (indigo accents, sans-serif, business report look), "
            "'technical' (dark code blocks, monospace-heavy, engineering docs). "
            "Omit to use the workspace default."
        ),
    )


class _MermaidBlock:
    """Represents a single Mermaid code block extracted from markdown."""

    def __init__(self, source: str, start_pos: int, end_pos: int) -> None:
        self.source = source
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.svg: str | None = None
        self.error: str | None = None
        self.ai_repaired: bool = False
        self.repair_notes: str | None = None


class RepairState(TypedDict):
    original_source: str
    error_message: str
    context: str
    current_source: str
    iteration: int
    max_iterations: int
    fixed_source: str | None
    fixed_svg: str | None
    repair_notes: str
    success: bool
