"""Registered assistant tools. To add a capability: build a Tool in its own module and add it below."""
from typing import Optional

from app.tools.light_control import build_light_tool
from app.tools.registry import ToolRegistry

_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry([build_light_tool()])
    return _registry
