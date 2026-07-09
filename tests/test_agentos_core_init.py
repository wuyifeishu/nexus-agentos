"""Tests for agentos.core.__init__ — public API surface."""



def test_core_init_imports():
    """Verify all exports from core.__init__ are importable."""
    from agentos.core import (
        Agent,
        ContextManager,
        RunContext,
        Session,
    )
    # Spot checks
    assert Agent is not None
    assert RunContext is not None
    assert Session is not None
    assert ContextManager is not None


def test_core___all___consistency():
    """Verify __all__ matches actual exports."""
    from agentos import core as mod
    assert isinstance(mod.__all__, list)
    for name in mod.__all__:
        assert hasattr(mod, name), f"__all__ includes {name} but not importable"


def test_streaming_in_core():
    """Streaming types are accessible via core."""
    from agentos.core import StreamEvent
    assert StreamEvent.TEXT is not None
