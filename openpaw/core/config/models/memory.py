"""Configuration models for memory, vector search, and auto-compact."""

from pydantic import BaseModel, Field, field_validator


class EmbeddingConfig(BaseModel):
    """Configuration for the embedding provider."""

    provider: str = Field(default="openai", description="Embedding provider (openai)")
    model: str = Field(default="text-embedding-3-small", description="Embedding model name")
    api_key: str | None = Field(default=None, description="API key for embedding provider")


class VectorStoreConfig(BaseModel):
    """Configuration for the vector store backend."""

    provider: str = Field(
        default="sqlite_vec", description="Vector store provider (sqlite_vec)"
    )
    dimensions: int = Field(default=1536, description="Embedding dimensions")


class MemoryConfig(BaseModel):
    """Configuration for conversation memory and vector search."""

    enabled: bool = Field(default=False, description="Enable conversation vector search")
    vector_store: VectorStoreConfig = Field(
        default_factory=VectorStoreConfig, description="Vector store backend config"
    )
    embedding: EmbeddingConfig = Field(
        default_factory=EmbeddingConfig, description="Embedding provider config"
    )


class AutoCompactConfig(BaseModel):
    """Configuration for automatic context compaction."""

    enabled: bool = Field(default=False, description="Enable automatic compaction when context window fills")
    trigger: float = Field(default=0.8, description="Context utilization fraction to trigger compaction (0.0-1.0)")
    summary_model: str | None = Field(
        default=None, description="Model for summary generation (null = use workspace model)"
    )
    flush: bool = Field(
        default=True,
        description=(
            "Give the agent one turn to write durable working context to a "
            "workspace file before compaction summarizes the conversation"
        ),
    )

    @field_validator("trigger")
    @classmethod
    def validate_trigger(cls, v: float) -> float:
        """Validate trigger is a fraction between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("trigger must be between 0.0 and 1.0")
        return v
