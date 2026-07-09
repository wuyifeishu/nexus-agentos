"""Tests for agentos.tools.__init__ — public API surface."""



def test_tools_init_imports():
    """Verify all exports from tools.__init__ are importable."""
    from agentos.tools import (
        BaseTool,
        PermissionLevel,
        ToolRiskLevel,
    )
    # Spot checks
    assert PermissionLevel.SAFE is not None
    assert ToolRiskLevel is not None
    assert BaseTool is not None


def test_tools___all___consistency():
    """Verify __all__ matches actual exports."""
    from agentos import tools as mod
    assert isinstance(mod.__all__, list)
    for name in mod.__all__:
        assert hasattr(mod, name), f"__all__ includes {name} but not importable"


def test_fusion_toolkit_import():
    from agentos.tools import FusionResult, FusionToolkit, ToolSpec
    assert FusionToolkit is not None
    assert FusionResult is not None
    assert ToolSpec is not None
