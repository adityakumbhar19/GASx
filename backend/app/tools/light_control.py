"""The `control_light` tool: wraps the EXISTING publish path (device_service.set_light ->
publish_light_state in app/router/voice.py -> MQTT topic relayCtr). No second publisher."""
import logging
import os
from typing import Any, Dict

from app.services import device_service
from app.tools.registry import Tool, ToolContext, ToolResult

logger = logging.getLogger("nfc-welcome.tools")

DESCRIPTION = (
    "Turns the office/lab light relay on or off. Call this ONLY when the person is clearly asking you, right now, "
    "to turn the light on or off (e.g. 'turn on the light', 'could you switch the lights off'). "
    "Do NOT call it for questions or discussion about lights ('how do LEDs work', 'why turn lights off when "
    "leaving'), for hypotheticals, or for future/conditional requests ('turn it on when I leave') - nothing here "
    "can schedule or react to events. If the person wants the light changed but did not say on or off, ask them "
    "which one instead of calling the tool. Never call it with a guessed state."
)

PARAMETERS = {
    "type": "object",
    "properties": {"state": {"type": "string", "enum": ["on", "off"], "description": "Desired light state."}},
    "required": ["state"],
    "additionalProperties": False,
}


def _authorized(ctx: ToolContext) -> bool:
    """Every NFC-authenticated employee may control the light, unless DEVICE_CONTROL_ALLOWED_EMPLOYEE_IDS
    (comma-separated employee ids / card ids) is set - then only those employees may."""
    allowed = {p.strip() for p in os.getenv("DEVICE_CONTROL_ALLOWED_EMPLOYEE_IDS", "").split(",") if p.strip()}
    return not allowed or ctx.employee_code in allowed


async def _handle(arguments: Dict[str, Any], ctx: ToolContext) -> ToolResult:
    state = arguments["state"]
    if await device_service.set_light(state):
        return ToolResult(
            success=True,
            # Deliberate wording: a published message is not proof the relay switched (no feedback channel).
            message=(f"The command to turn the light {state} was sent to the device broker. The light's actual "
                     "state is not confirmed. Say the command was sent; do not claim the light definitely changed."),
            user_message=f"I've sent the command to turn {state} the light.",
            data={"state": state},
        )
    return ToolResult(
        success=False,
        message="The command could NOT be sent (the device broker is unreachable or rejected it). Nothing was changed.",
        user_message="I couldn't send the light command. Please try again.",
        data={"state": state},
    )


def build_light_tool() -> Tool:
    return Tool(name="control_light", description=DESCRIPTION, parameters=PARAMETERS, handler=_handle,
                device="light", once_per_turn=True, authorize=_authorized)
