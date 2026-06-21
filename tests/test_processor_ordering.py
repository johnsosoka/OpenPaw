"""Tests for processor pipeline ordering by priority."""

import pytest

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.loader import BuiltinLoader
from openpaw.builtins.registry import BuiltinRegistry


class MockProcessorA(BaseBuiltinProcessor):
    """Mock processor with high priority (runs first)."""
    metadata = BuiltinMetadata(
        name="mock_a",
        display_name="Mock A",
        description="First processor",
        builtin_type=BuiltinType.PROCESSOR,
        prerequisites=BuiltinPrerequisite(),
        priority=10,
    )


class MockProcessorB(BaseBuiltinProcessor):
    """Mock processor with low priority (runs last)."""
    metadata = BuiltinMetadata(
        name="mock_b",
        display_name="Mock B",
        description="Last processor",
        builtin_type=BuiltinType.PROCESSOR,
        prerequisites=BuiltinPrerequisite(),
        priority=30,
    )


class MockProcessorC(BaseBuiltinProcessor):
    """Mock processor with medium priority."""
    metadata = BuiltinMetadata(
        name="mock_c",
        display_name="Mock C",
        description="Middle processor",
        builtin_type=BuiltinType.PROCESSOR,
        prerequisites=BuiltinPrerequisite(),
        priority=20,
    )


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before and after each test."""
    BuiltinRegistry.reset()
    yield
    BuiltinRegistry.reset()


def test_processors_sorted_by_priority():
    """Processors should be returned sorted by priority (lowest first)."""
    # Reset to clear any previously registered defaults
    BuiltinRegistry.reset()

    # Create a fresh registry - this will call _register_defaults()
    # We'll work with what gets registered and add our mocks
    registry = BuiltinRegistry.get_instance()

    # Clear the processors that were auto-registered
    registry._processors.clear()

    # Register ONLY our mock processors in wrong order (B=30, A=10, C=20)
    registry.register_processor(MockProcessorB)
    registry.register_processor(MockProcessorA)
    registry.register_processor(MockProcessorC)

    loader = BuiltinLoader()
    processors = loader.load_processors()

    names = [p.metadata.name for p in processors]
    assert names == ["mock_a", "mock_c", "mock_b"]


def test_default_priority_is_100():
    """Metadata without explicit priority defaults to 100."""
    meta = BuiltinMetadata(
        name="test",
        display_name="Test",
        description="test",
        builtin_type=BuiltinType.TOOL,
    )
    assert meta.priority == 100


def test_real_processor_priorities():
    """Verify real processor priority values are correctly set."""
    from openpaw.builtins.processors.file_persistence import FilePersistenceProcessor
    from openpaw.builtins.processors.timestamp import TimestampProcessor

    assert FilePersistenceProcessor.metadata.priority == 10
    assert TimestampProcessor.metadata.priority == 30

    # These may not be importable without optional deps, so wrap in try
    try:
        from openpaw.builtins.processors.whisper import WhisperProcessor
        assert WhisperProcessor.metadata.priority == 20
    except ImportError:
        pass

    try:
        from openpaw.builtins.processors.docling import DoclingProcessor
        assert DoclingProcessor.metadata.priority == 40
    except ImportError:
        pass
