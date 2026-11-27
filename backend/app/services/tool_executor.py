"""Validates and executes the tool calls the LLM asks for. Only registered tools can run."""
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.tools.registry import ToolArgumentError, ToolContext, ToolRegistry, ToolResult, validate_arguments

logger = logging.getLogger("nfc-welcome.tools")


@dataclass(frozen=True)
class ExecutedCall:
    tool: str
    arguments: Dict[str, Any]
    success: bool
    content: str                      # JSON string given back to the LLM as the tool message
    user_message: str                 # safe fallback sentence for the client
    device: Optional[str] = None
    ran: bool = False                 # True only if the handler actually executed (not rejected/duplicate)


def _content(success: bool, message: str, **extra) -> str:
    return json.dumps({"success": success, "message": message, **extra})


class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def execute(self, name: str, raw_arguments: str, ctx: ToolContext,
                      turn_cache: Dict[Tuple[str, str], ExecutedCall]) -> ExecutedCall:
        """`turn_cache` lives for ONE user message: it stops a tool marked once_per_turn from running twice
        (identical repeat -> previous result reused; conflicting repeat -> refused)."""
        tool = self._registry.get(name)
        if tool is None:
            logger.warning("LLM requested an unregistered tool: %r", name[:60])
            return ExecutedCall(name[:60], {}, False, _content(False, f"Unknown tool '{name[:60]}'. It was not run."),
                                "I can't do that.")

        try:
            parsed = json.loads(raw_arguments) if (raw_arguments or "").strip() else {}
            arguments = validate_arguments(tool.parameters, parsed)
        except (json.JSONDecodeError, ToolArgumentError) as exc:
            reason = str(exc) if isinstance(exc, ToolArgumentError) else "arguments were not valid JSON"
            logger.warning("Rejected arguments for tool %s: %s", name, reason)
            return ExecutedCall(name, {}, False,
                                _content(False, f"Invalid arguments ({reason}). The tool was NOT run. Ask the person "
                                                "what they want if it is unclear."),
                                "I wasn't sure what you wanted me to do.", tool.device)

        if tool.authorize is not None and not tool.authorize(ctx):
            logger.warning("Tool %s denied for this employee", name)
            return ExecutedCall(name, arguments, False,
                                _content(False, "This employee is not permitted to use this tool. It was NOT run."),
                                "Sorry, you're not allowed to do that.", tool.device)

        if tool.once_per_turn:
            earlier = next((c for (n, _), c in turn_cache.items() if n == name), None)
            if earlier is not None:
                if earlier.arguments == arguments:
                    return ExecutedCall(name, arguments, earlier.success, earlier.content, earlier.user_message,
                                        tool.device, ran=False)
                return ExecutedCall(name, arguments, False,
                                    _content(False, f"Conflicting request: {name} was already run this turn with "
                                                    "different arguments. This call was NOT run. Ask the person "
                                                    "which they want."),
                                    "I got conflicting instructions, so please tell me which one you want.", tool.device)

        try:
            result: ToolResult = await tool.handler(arguments, ctx)
        except Exception:
            logger.exception("Tool %s raised", name)
            result = ToolResult(False, "The tool failed unexpectedly. Nothing was confirmed.",
                                "Something went wrong while doing that.")
        call = ExecutedCall(name, arguments, result.success,
                            _content(result.success, result.message, **result.data), result.user_message,
                            tool.device, ran=True)
        if tool.once_per_turn:
            turn_cache[(name, json.dumps(arguments, sort_keys=True))] = call
        logger.info("Tool %s executed (success=%s)", name, result.success)
        return call
