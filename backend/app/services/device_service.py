"""Device control for the assistant. Thin wrapper around the EXISTING MQTT function.

There is deliberately no MQTT client here: publish_light_state() in app/router/voice.py already
connects with credentials from the backend environment and publishes the unchanged payload
({"NM": <device>, "state": "1"|"0"} to topic relayCtr). This module only calls it safely from async code.
"""
import asyncio
import logging

from fastapi.concurrency import run_in_threadpool

from app.router.voice import publish_light_state

logger = logging.getLogger("nfc-welcome.device")

MQTT_TIMEOUT_SECONDS = 12.0          # paho's own connect timeout is 5 s; this is the overall cap


async def set_light(state: str) -> bool:
    """state is "on" or "off". Returns True if the command was published to the broker.

    True means "the broker accepted the command", NOT "the relay changed" - there is no relay feedback
    channel, so callers must word their replies accordingly ("I've sent the command ...").
    Never raises: any failure (missing credentials, broker down, timeout) returns False.
    """
    if state not in ("on", "off"):
        raise ValueError("state must be 'on' or 'off'")
    value = "1" if state == "on" else "0"
    try:
        await asyncio.wait_for(run_in_threadpool(publish_light_state, value), timeout=MQTT_TIMEOUT_SECONDS)
        logger.info("Light command '%s' published", state)
        return True
    except asyncio.TimeoutError:
        logger.error("Publishing the light command timed out after %.0fs", MQTT_TIMEOUT_SECONDS)
    except Exception:
        # The exception text never contains credentials (they are not part of any message we build).
        logger.exception("Could not publish the light command to MQTT")
    return False
