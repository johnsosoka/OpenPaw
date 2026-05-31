"""Configuration models for builtin capabilities."""

from typing import Any

from pydantic import BaseModel, Field

from openpaw.core.paths import DOWNLOADS_DIR, SCREENSHOTS_DIR


class BuiltinItemConfig(BaseModel):
    """Configuration for a single builtin capability."""

    enabled: bool = Field(default=True, description="Whether this builtin is active")
    config: dict[str, Any] = Field(default_factory=dict, description="Builtin-specific settings")

    model_config = {"extra": "allow"}


class CronBuiltinConfig(BuiltinItemConfig):
    """Configuration for the cron scheduling tool."""

    max_tasks: int = Field(default=50, description="Maximum scheduled tasks per workspace")
    min_interval_seconds: int = Field(
        default=300, description="Minimum interval between recurring tasks (5 min default, can be lowered)"
    )


class CronManagerBuiltinConfig(BuiltinItemConfig):
    """Configuration for the persistent cron management builtin."""


class AcknowledgeBuiltinConfig(BuiltinItemConfig):
    """Configuration for the acknowledge_event tool."""


class SendFileBuiltinConfig(BuiltinItemConfig):
    """Configuration for the send_file tool."""

    max_file_size: int = Field(
        default=(50 * 1024 * 1024),
        description="Maximum file size in bytes (default 50MB for Telegram)"
    )


class DoclingBuiltinConfig(BuiltinItemConfig):
    """Configuration for the Docling document processor."""

    max_file_size: int = Field(
        default=(50 * 1024 * 1024),
        description="Maximum file size in bytes (default 50MB)"
    )
    ocr_backend: str = Field(
        default="auto",
        description="OCR backend: 'auto', 'mac', 'easyocr', 'tesseract', 'rapidocr'"
    )
    ocr_languages: list[str] = Field(
        default_factory=lambda: ["en"],
        description="OCR languages as ISO 639-1 codes (auto-mapped per backend)"
    )
    force_full_page_ocr: bool = Field(
        default=True,
        description="Force full-page OCR (recommended for scanned docs)"
    )
    document_timeout: float | None = Field(
        default=None,
        description="Per-document timeout in seconds (None = no limit)"
    )
    do_ocr: bool = Field(default=True, description="Enable OCR processing")
    do_table_structure: bool = Field(default=True, description="Enable table structure detection")


class BrowserBuiltinConfig(BuiltinItemConfig):
    """Configuration for the browser automation tool."""

    headless: bool = Field(default=True, description="Run browser without GUI")
    allowed_domains: list[str] = Field(default_factory=list, description="Domain allowlist (empty = allow all)")
    blocked_domains: list[str] = Field(default_factory=list, description="Domain blocklist (takes precedence)")
    timeout_seconds: int = Field(default=30, description="Default timeout for browser operations")
    persist_cookies: bool = Field(default=False, description="Persist cookies across agent runs")
    downloads_dir: str = Field(default=str(DOWNLOADS_DIR), description="Directory for downloaded files")
    screenshots_dir: str = Field(default=str(SCREENSHOTS_DIR), description="Directory for screenshots")


class SpawnBuiltinConfig(BuiltinItemConfig):
    """Configuration for the sub-agent spawn tool."""

    max_concurrent: int = Field(default=8, description="Maximum simultaneous sub-agents")
    default_progress_interval: int = Field(
        default=0,
        ge=0,
        description="Default progress interval in minutes (0 = disabled)",
    )


class Md2pdfBuiltinConfig(BuiltinItemConfig):
    """Configuration for the md2pdf conversion tool."""

    theme: str = Field(default="minimal", description="CSS theme: minimal, professional, or technical")
    max_diagram_width: float = Field(default=6.5, description="Maximum Mermaid diagram width in inches")
    self_heal: bool = Field(default=True, description="Enable AI self-healing for broken Mermaid diagrams")
    self_heal_model: str = Field(default="gpt-4o-mini", description="Model for self-healing (e.g., gpt-4o-mini)")
    max_heal_iterations: int = Field(default=3, description="Maximum repair attempts per broken diagram")


class ChannelHistoryBuiltinConfig(BuiltinItemConfig):
    """Configuration for the channel history browsing tool."""

    max_messages_per_request: int = Field(
        default=100,
        description="Hard cap on messages returned per request (default: 100)",
    )
    content_truncation: int = Field(
        default=500,
        description="Per-message content character truncation limit (default: 500)",
    )


class GptResearcherBuiltinConfig(BuiltinItemConfig):
    """Configuration for the GPT-Researcher integration tool."""

    endpoint: str = Field(default="", description="WebSocket endpoint URL (e.g., wss://researcher.example.com/ws)")
    upload_endpoint: str = Field(default="", description="REST upload endpoint URL (e.g., https://researcher.example.com/upload/)")
    timeout_seconds: int = Field(default=300, description="Max seconds to wait for research completion")
    default_report_type: str = Field(
        default="research_report",
        description="Default report type: research_report, outline_report, detailed_report, resource_report",
    )
    default_report_source: str = Field(default="web", description="Default report source: web or local")
    default_tone: str = Field(default="Objective", description="Default writing tone for reports")


class EmailBuiltinConfig(BuiltinItemConfig):
    """Configuration for the email integration tool."""

    provider: str = Field(default="gmail", description="Email provider: gmail")
    service_account_file: str | None = Field(
        default=None,
        description="Path to Google service account JSON (absolute or relative to workspace)",
    )
    delegated_user: str | None = Field(
        default=None,
        description="Email address to impersonate via domain-wide delegation",
    )
    allowed_recipients: list[str] = Field(
        default_factory=list,
        description="Recipient allowlist patterns (e.g., '*@company.com'). Empty = block all sends.",
    )
    max_recipients: int = Field(
        default=10,
        description="Maximum recipients per email (to + cc + bcc combined)",
    )


class FilePersistenceBuiltinConfig(BuiltinItemConfig):
    """Configuration for the file persistence processor."""

    max_file_size: int = Field(
        default=(50 * 1024 * 1024),
        description="Maximum file size in bytes (default 50MB)",
    )
    clear_data_after_save: bool = Field(default=False, description="Free memory after saving")


class BuiltinsConfig(BaseModel):
    """Global builtins configuration.

    Supports OpenClaw-style allow/deny lists with group prefixes (e.g., "group:voice").
    Deny takes precedence over allow. Empty allow list means allow all available.
    """

    allow: list[str] = Field(
        default_factory=list,
        description="Allowed builtins/groups (empty = allow all available)",
    )
    deny: list[str] = Field(
        default_factory=list,
        description="Denied builtins/groups (takes precedence over allow)",
    )

    # Per-builtin configuration
    brave_search: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    whisper: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    elevenlabs: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    shell: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    cron: CronBuiltinConfig = Field(default_factory=CronBuiltinConfig)
    cron_manager: CronManagerBuiltinConfig = Field(default_factory=CronManagerBuiltinConfig)
    acknowledge: AcknowledgeBuiltinConfig = Field(default_factory=AcknowledgeBuiltinConfig)
    send_file: SendFileBuiltinConfig = Field(default_factory=SendFileBuiltinConfig)
    docling: DoclingBuiltinConfig = Field(default_factory=DoclingBuiltinConfig)
    browser: BrowserBuiltinConfig = Field(default_factory=BrowserBuiltinConfig)
    spawn: SpawnBuiltinConfig = Field(default_factory=SpawnBuiltinConfig)
    file_persistence: FilePersistenceBuiltinConfig = Field(default_factory=FilePersistenceBuiltinConfig)
    md2pdf: Md2pdfBuiltinConfig = Field(default_factory=Md2pdfBuiltinConfig)
    channel_history: ChannelHistoryBuiltinConfig = Field(default_factory=ChannelHistoryBuiltinConfig)
    gpt_researcher: GptResearcherBuiltinConfig = Field(default_factory=GptResearcherBuiltinConfig)
    email: EmailBuiltinConfig = Field(default_factory=EmailBuiltinConfig)

    model_config = {"extra": "allow"}


class WorkspaceBuiltinsConfig(BaseModel):
    """Per-workspace builtins configuration (overrides global)."""

    allow: list[str] = Field(
        default_factory=list,
        description="Additional allowed builtins for this workspace",
    )
    deny: list[str] = Field(
        default_factory=list,
        description="Builtins to disable for this workspace",
    )

    # Per-builtin overrides
    brave_search: BuiltinItemConfig | None = None
    whisper: BuiltinItemConfig | None = None
    elevenlabs: BuiltinItemConfig | None = None
    shell: BuiltinItemConfig | None = None
    cron: CronBuiltinConfig | None = None
    cron_manager: CronManagerBuiltinConfig | None = None
    acknowledge: AcknowledgeBuiltinConfig | None = None
    send_file: SendFileBuiltinConfig | None = None
    docling: DoclingBuiltinConfig | None = None
    browser: BrowserBuiltinConfig | None = None
    spawn: SpawnBuiltinConfig | None = None
    file_persistence: FilePersistenceBuiltinConfig | None = None
    md2pdf: Md2pdfBuiltinConfig | None = None
    channel_history: ChannelHistoryBuiltinConfig | None = None
    gpt_researcher: GptResearcherBuiltinConfig | None = None
    email: EmailBuiltinConfig | None = None

    model_config = {"extra": "allow"}
