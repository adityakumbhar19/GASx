"""Tool registry: the ONLY place that defines what the LLM is allowed to ask the backend to do.

A tool is a name + description + JSON-schema for its arguments + an async handler. Adding a new
capability later means writing one module that builds a `Tool` and registering it in
app/tools/__init__.py - the assistant service, executor and router do not change.

Nothing the LLM returns is ever executed by name lookup outside this registry.
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


class ToolArgumentError(ValueError):
    """The LLM supplied arguments that do not match the tool's schema."""


@dataclass(frozen=True)
class ToolContext:
    """Who is asking. Built from the verified NFC session - never from anything the client or LLM says."""
    employee_pk: int
    employee_code: str
    employee_name: str
    department: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    success: bool
    message: str                  # what the LLM sees: factual, includes what is NOT guaranteed
    user_message: str             # safe sentence to speak if the LLM cannot produce the final answer
    data: Dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]                      # JSON schema, "type": "object"
    handler: Handler
    device: Optional[str] = None                    # reported to clients as `device` (e.g. "light")
    once_per_turn: bool = False                     # a second call in the same user turn is not executed
    authorize: Optional[Callable[[ToolContext], bool]] = None   # None = every authenticated employee

    def openai_schema(self) -> Dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


_TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float)}


def validate_arguments(schema: Dict[str, Any], arguments: Any) -> Dict[str, Any]:
    """Strict, dependency-free validation for the small schema subset tools use:
    object with typed properties, `required`, `enum`, and no unknown keys."""
    if not isinstance(arguments, dict):
        raise ToolArgumentError("arguments must be a JSON object")
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    if unknown:
        raise ToolArgumentError(f"unexpected argument(s): {', '.join(sorted(unknown))}")
    for name in schema.get("required", []):
        if name not in arguments:
            raise ToolArgumentError(f"missing required argument: {name}")
    for name, value in arguments.items():
        spec = properties[name]
        expected = _TYPES.get(spec.get("type", ""))
        if expected is None or isinstance(value, bool) != (spec.get("type") == "boolean") or not isinstance(value, expected):
            raise ToolArgumentError(f"argument '{name}' must be of type {spec.get('type')}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolArgumentError(f"argument '{name}' must be one of: {', '.join(map(str, spec['enum']))}")
    return dict(arguments)


class ToolRegistry:
    def __init__(self, tools: Optional[List[Tool]] = None):
        self._tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def openai_schemas(self) -> List[Dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
