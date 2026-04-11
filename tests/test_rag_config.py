"""Tests for RAG-related configuration models."""

import pytest
from openpaw.core.config.models import (
    ConversationIndexingConfig,
    EmbeddingConfig,
    FileIndexingConfig,
    InjectionConfig,
    MemoryConfig,
    VectorStoreConfig,
)


class TestConversationIndexingConfig:
    """Tests for ConversationIndexingConfig model."""

    def test_defaults(self):
        """Default construction produces expected values."""
        config = ConversationIndexingConfig()
        assert config.enabled is True
        assert config.chunk_window == 3
        assert config.chunk_overlap == 1

    def test_custom_values(self):
        """Custom chunk_window and chunk_overlap are stored correctly."""
        config = ConversationIndexingConfig(chunk_window=5, chunk_overlap=2)
        assert config.chunk_window == 5
        assert config.chunk_overlap == 2

    def test_chunk_window_minimum_is_one(self):
        """chunk_window below 1 raises a validation error."""
        with pytest.raises(Exception):
            ConversationIndexingConfig(chunk_window=0)

    def test_chunk_window_maximum_is_ten(self):
        """chunk_window above 10 raises a validation error."""
        with pytest.raises(Exception):
            ConversationIndexingConfig(chunk_window=11)

    def test_chunk_overlap_minimum_is_zero(self):
        """chunk_overlap of 0 is valid (no overlap)."""
        config = ConversationIndexingConfig(chunk_overlap=0)
        assert config.chunk_overlap == 0

    def test_chunk_overlap_cannot_be_negative(self):
        """Negative chunk_overlap raises a validation error."""
        with pytest.raises(Exception):
            ConversationIndexingConfig(chunk_overlap=-1)

    def test_enabled_can_be_disabled(self):
        """Conversation indexing can be explicitly disabled."""
        config = ConversationIndexingConfig(enabled=False)
        assert config.enabled is False


class TestFileIndexingConfig:
    """Tests for FileIndexingConfig model."""

    def test_defaults(self):
        """Default construction produces expected values."""
        config = FileIndexingConfig()
        assert config.enabled is False
        assert len(config.include) > 0
        assert config.max_file_size_kb == 512
        assert config.chunk_size == 1000
        assert config.chunk_overlap == 200

    def test_default_include_patterns_are_meaningful(self):
        """Default include glob patterns cover common workspace file types."""
        config = FileIndexingConfig()
        include_str = " ".join(config.include)
        assert "*.md" in include_str

    def test_default_exclude_protects_openpaw_dir(self):
        """Default exclude list keeps .openpaw/ out of indexing."""
        config = FileIndexingConfig()
        exclude_str = " ".join(config.exclude)
        assert ".openpaw" in exclude_str

    def test_custom_include_patterns(self):
        """Custom include patterns are stored as-is."""
        config = FileIndexingConfig(include=["**/*.py"], exclude=["tests/**"])
        assert config.include == ["**/*.py"]
        assert config.exclude == ["tests/**"]

    def test_enabled_can_be_set_true(self):
        """File indexing can be explicitly enabled."""
        config = FileIndexingConfig(enabled=True)
        assert config.enabled is True

    def test_max_file_size_kb_minimum(self):
        """max_file_size_kb below 1 raises a validation error."""
        with pytest.raises(Exception):
            FileIndexingConfig(max_file_size_kb=0)

    def test_chunk_size_minimum(self):
        """chunk_size below 100 raises a validation error."""
        with pytest.raises(Exception):
            FileIndexingConfig(chunk_size=99)

    def test_chunk_size_maximum(self):
        """chunk_size above 10000 raises a validation error."""
        with pytest.raises(Exception):
            FileIndexingConfig(chunk_size=10001)

    def test_chunk_overlap_cannot_be_negative(self):
        """Negative chunk_overlap raises a validation error."""
        with pytest.raises(Exception):
            FileIndexingConfig(chunk_overlap=-1)


class TestInjectionConfig:
    """Tests for InjectionConfig model."""

    def test_defaults(self):
        """Default construction produces expected values."""
        config = InjectionConfig()
        assert config.enabled is False
        assert config.max_results == 3
        assert config.min_score == 0.3
        assert config.max_tokens == 500
        assert "conversations" in config.sources
        assert "files" in config.sources

    def test_min_score_upper_bound(self):
        """min_score above 1.0 raises a validation error."""
        with pytest.raises(Exception):
            InjectionConfig(min_score=1.5)

    def test_min_score_lower_bound(self):
        """min_score below 0.0 raises a validation error."""
        with pytest.raises(Exception):
            InjectionConfig(min_score=-0.1)

    def test_min_score_at_bounds_is_valid(self):
        """min_score of exactly 0.0 and 1.0 are both valid."""
        low = InjectionConfig(min_score=0.0)
        high = InjectionConfig(min_score=1.0)
        assert low.min_score == 0.0
        assert high.min_score == 1.0

    def test_max_results_minimum(self):
        """max_results below 1 raises a validation error."""
        with pytest.raises(Exception):
            InjectionConfig(max_results=0)

    def test_max_results_maximum(self):
        """max_results above 10 raises a validation error."""
        with pytest.raises(Exception):
            InjectionConfig(max_results=11)

    def test_max_tokens_minimum(self):
        """max_tokens below 100 raises a validation error."""
        with pytest.raises(Exception):
            InjectionConfig(max_tokens=99)

    def test_max_tokens_maximum(self):
        """max_tokens above 2000 raises a validation error."""
        with pytest.raises(Exception):
            InjectionConfig(max_tokens=2001)

    def test_custom_sources(self):
        """Custom sources list is stored as provided."""
        config = InjectionConfig(sources=["conversations"])
        assert config.sources == ["conversations"]

    def test_enabled_can_be_set_true(self):
        """Injection can be explicitly enabled."""
        config = InjectionConfig(enabled=True)
        assert config.enabled is True


class TestMemoryConfig:
    """Tests for the expanded MemoryConfig model."""

    def test_defaults_backward_compatible(self):
        """Default MemoryConfig has expected values and all sub-configs present."""
        config = MemoryConfig()
        assert config.enabled is False
        assert config.vector_store.provider == "sqlite_vec"
        assert config.embedding.provider == "openai"
        # New sub-configs exist with their own defaults
        assert config.conversations.enabled is True
        assert config.files.enabled is False
        assert config.injection.enabled is False

    def test_minimal_enable(self):
        """Setting enabled=True preserves all sub-config defaults."""
        config = MemoryConfig(enabled=True)
        assert config.enabled is True
        assert config.conversations.enabled is True
        assert config.files.enabled is False

    def test_full_config(self):
        """All fields can be set explicitly via nested config objects."""
        config = MemoryConfig(
            enabled=True,
            embedding=EmbeddingConfig(provider="local", model="all-MiniLM-L6-v2"),
            vector_store=VectorStoreConfig(dimensions=384),
            files=FileIndexingConfig(enabled=True),
            injection=InjectionConfig(enabled=True, max_results=5),
        )
        assert config.embedding.provider == "local"
        assert config.vector_store.dimensions == 384
        assert config.files.enabled is True
        assert config.injection.max_results == 5

    def test_conversations_sub_config_can_be_overridden(self):
        """Conversation indexing sub-config can be customized."""
        config = MemoryConfig(
            enabled=True,
            conversations=ConversationIndexingConfig(chunk_window=5, chunk_overlap=2),
        )
        assert config.conversations.chunk_window == 5
        assert config.conversations.chunk_overlap == 2

    def test_injection_sub_config_can_be_overridden(self):
        """Injection sub-config can be customized independently."""
        config = MemoryConfig(
            enabled=True,
            injection=InjectionConfig(enabled=True, min_score=0.5, max_results=7),
        )
        assert config.injection.enabled is True
        assert config.injection.min_score == 0.5
        assert config.injection.max_results == 7

    def test_sub_configs_are_independent_instances(self):
        """Multiple MemoryConfig instances do not share sub-config objects."""
        config_a = MemoryConfig()
        config_b = MemoryConfig()
        assert config_a.conversations is not config_b.conversations
        assert config_a.files is not config_b.files
        assert config_a.injection is not config_b.injection
