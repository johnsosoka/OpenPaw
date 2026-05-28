"""Browser tool input schemas."""
from pydantic import BaseModel, Field


class BrowserNavigateInput(BaseModel):
    """Input schema for browser navigation."""

    url: str = Field(description="URL to navigate to")


class BrowserClickInput(BaseModel):
    """Input schema for clicking elements."""

    ref: int = Field(description="Element reference number from browser_snapshot")
    keep_refs: bool = Field(
        default=False,
        description=(
            "When True, auto-refresh the snapshot after clicking and return "
            "updated element refs. Use this for multi-selection in custom "
            "dropdowns where the DOM re-renders after each click — you can "
            "click the next element immediately without calling browser_snapshot."
        ),
    )


class BrowserTypeInput(BaseModel):
    """Input schema for typing text."""

    ref: int = Field(description="Element reference number from browser_snapshot")
    text: str = Field(description="Text to type into the element")
    press_enter: bool = Field(
        default=False, description="Press Enter after typing (submits forms)"
    )


class BrowserSelectInput(BaseModel):
    """Input schema for selecting dropdown options."""

    ref: int = Field(description="Element reference number from browser_snapshot")
    value: str = Field(description="Option value or label to select")


class BrowserScrollInput(BaseModel):
    """Input schema for scrolling."""

    direction: str = Field(description="Scroll direction: 'up' or 'down'")
    amount: str = Field(
        default="page", description="Scroll amount: 'page' (full) or 'half'"
    )


class BrowserScreenshotInput(BaseModel):
    """Input schema for screenshots."""

    full_page: bool = Field(
        default=False,
        description="Capture entire scrollable page (default: viewport only)",
    )


class BrowserExecuteJsInput(BaseModel):
    """Input schema for executing JavaScript."""

    script: str = Field(
        description=(
            "JavaScript to evaluate in the page. Can be an expression "
            "(e.g. 'document.title') or an arrow function body "
            "(e.g. '...args => document.querySelectorAll(args[0])'). "
            "If `arg` is provided, the script receives it as a parameter."
        )
    )
    arg: str | None = Field(
        default=None,
        description=(
            "Optional JSON value passed into the script. "
            "Useful for parameterised queries like CSS selectors."
        ),
    )


class BrowserSwitchTabInput(BaseModel):
    """Input schema for switching tabs."""

    index: int = Field(description="Tab index from browser_tabs")
