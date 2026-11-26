"""Rule-based intent detection for the assistant. No LLM call, no I/O.

Decides, BEFORE the LLM is involved, whether a message is
  * LIGHT        - a clear "turn the light on/off" command         -> run the existing MQTT function
  * CLARIFY      - the user is clearly talking about controlling the light but did not say on or off
  * UNSUPPORTED  - a command for a device we cannot control (AC, fan, TV, ...)
  * CHAT         - anything else, including questions ABOUT lights -> normal LLM conversation

Design rule: precision over recall. A command is only recognised when the WHOLE sentence has the
shape  [politeness] + [verb phrase + light noun] + [politeness / place]  (all anchored with ^ and $).
So "How do I turn on the light?", "What happens if I turn off the light?" or "Explain smart
lighting" can never match, because their lead-in words are not allowed. When a message mixes a
command with something else ("Turn on the light and explain how LEDs work") the command is split off
and the rest is returned as `remainder` so it can still be answered.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class IntentKind(str, Enum):
    CHAT = "chat"
    LIGHT = "light"
    CLARIFY = "clarify"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    state: Optional[str] = None                   # "on" / "off" when kind == LIGHT
    remainder: str = ""                           # part of the message that is NOT the command
    unsupported_devices: Tuple[str, ...] = ()     # other devices named in the command (fan, ac, ...)


# --------------------------------------------------------------------------- normalisation
_CONTRACTIONS = (
    (r"\bcan't\b", "can not"), (r"\bcannot\b", "can not"), (r"\bwon't\b", "will not"),
    (r"\blet's\b", "let us"), (r"\bi'd\b", "i would"), (r"\bi'm\b", "i am"),
    (r"\bit's\b", "it is"), (r"\bthat's\b", "that is"), (r"\bwhat's\b", "what is"),
    (r"n't\b", " not"),
)
_GERUNDS = {"turning": "turn", "switching": "switch", "putting": "put", "shutting": "shut",
            "cutting": "cut", "killing": "kill", "flipping": "flip"}
_MIND_RE = re.compile(r"\b(?:would|do|could)\s+you\s+mind\s+(?:to\s+)?(" + "|".join(_GERUNDS) + r")\b")


def _normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"\ba\s*/\s*c\b", "ac", t)
    for pattern, replacement in _CONTRACTIONS:
        t = re.sub(pattern, replacement, t)
    t = _MIND_RE.sub(lambda m: "please " + _GERUNDS[m.group(1)], t)   # "would you mind turning on" -> "please turn on"
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# --------------------------------------------------------------------------- vocabulary
_FILLER = r"(?:hey|hi|hello|ok|okay|so|well|now|just|please|kindly|actually|alright|assistant|then|also|and)"
_LEAD = (
    rf"(?:{_FILLER}\s+){{0,5}}"
    r"(?:(?:(?:can|could|would|will)\s+(?:you|u)"
    r"|you\s+(?:can|could|should|may|must|will)"
    r"|i\s+(?:want|need|would\s+like|wish)\s+(?:you\s+)?to"
    r"|go\s+ahead\s+and|let\s+us"
    r"|i\s+would\s+appreciate\s+it\s+if\s+you)\s+)?"
    rf"(?:{_FILLER}\s+){{0,5}}"
)
_PLACE = (r"(?:room|lab|laboratory|office|hall|hallway|area|space|place|building|cabin|kitchen|lobby|"
          r"bedroom|workshop|classroom|cubicle|corridor|floor)")
_TAIL = (
    r"(?:\s+(?:please|kindly|now|right\s+now|for\s+me|for\s+us|thanks|thank\s+you|again|too|as\s+well|"
    r"immediately|quickly|asap|right\s+away|real\s+quick|ok|okay|there|here|in\s+here|in\s+there|over\s+here|"
    rf"(?:in|inside|at)\s+(?:this|that|the|my|our|your)\s+(?:[a-z]+\s+)?{_PLACE})){{0,6}}"
)
_END = rf"{_TAIL}\s*$"

_STOP = (r"(?:the|this|that|these|those|all|of|every|each|both|my|our|your|some|a|any|and|plus|or|as|well|"
         r"on|off|out|up|down|light|lights|tube|tubelight|tubelights|please|now)")
_DET = r"(?:(?:the|this|that|these|those|all|of|every|each|both|my|our|your|some|a|any)\s+){0,3}"
_MOD = rf"(?:(?!{_STOP}\b)[a-z]+\s+){{0,2}}"
_NOUN = r"(?:tube\s*lights?|tubelights?|lights?)\b"
_DEVICE = (r"(?:ac|a\s+c|aircon|air\s*conditioners?|air\s*conditioning|fans?|heaters?|geysers?|tv|television|"
           r"projectors?|doors?|windows?|curtains?|blinds?|shutters?|computers?|pcs?|monitors?|screens?|"
           r"printers?|speakers?|music|cameras?|sockets?|plugs?|ventilators?|exhausts?|coolers?|"
           r"refrigerators?|fridges?|ovens?|microwaves?|kettles?)\b")
_NP = rf"{_DET}{_MOD}(?:{_NOUN}|{_DEVICE})"
_NPS = rf"{_NP}(?:\s+(?:and|plus|as\s+well\s+as)\s+{_NP}){{0,3}}"
_NPS_DEV = rf"{_DET}{_MOD}{_DEVICE}(?:\s+(?:and|plus|as\s+well\s+as)\s+{_DET}{_MOD}{_DEVICE}){{0,3}}"

_NOUN_RE = re.compile(r"\b" + _NOUN)
_DEVICE_RE = re.compile(r"\b" + _DEVICE)


def _cmd(body: str) -> "re.Pattern[str]":
    return re.compile(rf"^{_LEAD}{body}{_END}")


_OFF_PARTICLE = r"(?:off|of|out)"   # "of" because speech recognition often hears "turn of the light"

# Explicit verb commands - allowed everywhere (also when splitting a compound message)
_EXPLICIT_ON = [
    _cmd(rf"(?:turn|switch|power|flip|put|set)\s+on\s+{_NPS}"),
    _cmd(rf"(?:turn|switch|flip|put|set)\s+{_NPS}\s+on"),
]
_EXPLICIT_OFF = [
    _cmd(rf"(?:turn|switch|power|flip|put|shut|set)\s+(?:off|of)\s+{_NPS}"),
    _cmd(rf"(?:turn|put|switch)\s+out\s+{_NPS}"),
    _cmd(rf"shut\s+down\s+{_NPS}"),
    _cmd(rf"(?:turn|switch|flip|put|shut|set)\s+{_NPS}\s+{_OFF_PARTICLE}"),
    _cmd(rf"(?:kill|cut|extinguish)\s+{_NPS}"),
]
# Looser phrasings - only for whole sentences, never for a fragment cut out of a longer message
_LOOSE_ON = [
    _cmd(rf"(?:i\s+)?(?:need|want|would\s+like|require)\s+(?:some|more|extra|a\s+(?:bit|little)(?:\s+of)?)\s+(?:more\s+)?{_NOUN}"),
    _cmd(rf"(?:i\s+)?(?:need|want|would\s+like)\s+{_NPS}\s+on"),
    _cmd(rf"(?:give|get|bring)\s+(?:me|us)\s+(?:(?:some|more|a\s+(?:bit|little)(?:\s+of)?)\s+)?{_NOUN}"),
    _cmd(rf"(?:can|could|may)\s+(?:i|we)\s+(?:please\s+)?have\s+(?:(?:some|more|the)\s+)?{_NOUN}(?:\s+on)?"),
    _cmd(rf"let\s+there\s+be\s+{_NOUN}"),
    _cmd(rf"{_DET}{_NOUN}\s+on"),
]
_LOOSE_OFF = [
    _cmd(rf"(?:i\s+)?(?:need|want|would\s+like)\s+{_NPS}\s+(?:off|out)"),
    _cmd(rf"{_DET}{_NOUN}\s+(?:off|out)"),
]
_PRONOUN = r"(?:it|them|that|those|this|these)"
_PRONOUN_ON = [
    _cmd(rf"(?:turn|switch|flip|put|power|set)\s+{_PRONOUN}\s+on"),
    _cmd(rf"(?:turn|switch|power|flip|put)\s+on\s+{_PRONOUN}"),
]
_PRONOUN_OFF = [
    _cmd(rf"(?:turn|switch|flip|put|shut|power|set)\s+{_PRONOUN}\s+{_OFF_PARTICLE}"),
    _cmd(rf"(?:turn|switch|power|flip|put|shut)\s+(?:off|of)\s+{_PRONOUN}"),
]
_ANSWER = re.compile(
    rf"^{_LEAD}(?:(?:turn|switch|put|set)\s+(?:(?:it|them|that|the\s+lights?)\s+)?)?(on|off|of)(?:\s+please)?{_END}")

_CLARIFY = [
    _cmd(rf"(?:do|try|make)\s+(?:something|anything|stuff|a\s+change)\s+(?:with|about|to|for|on)\s+{_DET}{_MOD}{_NOUN}"),
    _cmd(r"(?:handle|fix|control|change|adjust|toggle|operate|manage|fiddle\s+with|mess\s+with|play\s+with|"
         r"work\s+on|deal\s+with|take\s+care\s+of|help\s+me\s+with|sort\s+out|dim|brighten|lower|raise|"
         rf"increase|decrease|flick)\s+{_DET}{_MOD}{_NOUN}"),
    _cmd(rf"(?:turn|switch)\s+(?:up|down)\s+{_DET}{_MOD}{_NOUN}"),
    _cmd(rf"(?:turn|switch)\s+{_DET}{_MOD}{_NOUN}\s+(?:up|down)"),
    _cmd(rf"(?:turn|switch|flip)\s+{_DET}{_MOD}{_NOUN}"),
    _cmd(rf"{_DET}{_MOD}{_NOUN}"),
]
_DEVICE_VERB = _cmd(
    r"(?:open|close|lock|unlock|start|stop|run|activate|deactivate|enable|disable|play|pause|increase|"
    rf"decrease|lower|raise|adjust)\s+{_NPS_DEV}")

_MAX_COMMAND_CHARS = 160     # a command is a short utterance; anything longer is never matched (also bounds regex cost)
_MAX_SPLITS = 8              # conjunction positions tried per message
_NEGATION = re.compile(r"\b(?:not|never|no\s+need|without|nothing)\b")

# --------------------------------------------------------------------------- compound messages
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_CONJ = re.compile(
    r"(?:\s*,\s*(?:(?:and\s+then|and\s+also|and|then|also|plus|but|after\s+that)\b\s*)?"
    r"|\s+(?:and\s+then|and\s+also|and|then|also|plus|but|after\s+that)\b\s*)", re.IGNORECASE)
_REASON = re.compile(r"\s*,?\s*\b(?:because|since|cause|coz|as\s+it\s+is|as\s+its|so\s+that|so\s+i\s+can|so\s+we\s+can|so\s+i\s+could|so\s+it\s+is)\b.*$", re.IGNORECASE)
_FILLER_WORDS = {"please", "thanks", "thank", "you", "ok", "okay", "hello", "hi", "hey", "now", "then", "also",
                 "and", "so", "well", "kindly", "for", "me", "us", "right", "away", "assistant", "there", "here",
                 "too", "yes", "yeah", "sure", "alright", "just"}


@dataclass(frozen=True)
class _Seg:
    kind: str                       # "light" | "unsupported" | "clarify" | "other"
    state: Optional[str] = None
    devices: Tuple[str, ...] = ()


_OTHER = _Seg("other")


def _device_names(normalized: str) -> Tuple[str, ...]:
    names: List[str] = []
    for match in _DEVICE_RE.finditer(normalized):
        raw = re.sub(r"\s+", " ", match.group(0)).strip()
        name = "AC" if re.fullmatch(r"ac|a c|aircon|air ?conditioners?|air ?conditioning", raw) else raw
        if name not in names:
            names.append(name)
    return tuple(names)


def _first_match(patterns, n: str) -> bool:
    return any(p.match(n) for p in patterns)


def _classify(text: str, light_context: bool, awaiting_choice: bool, strict: bool) -> _Seg:
    n = _normalize(text)
    if not n or len(n) > _MAX_COMMAND_CHARS or _NEGATION.search(n):
        return _OTHER

    state: Optional[str] = None
    if _first_match(_EXPLICIT_ON, n):
        state = "on"
    elif _first_match(_EXPLICIT_OFF, n):
        state = "off"
    elif not strict:
        if _first_match(_LOOSE_ON, n):
            state = "on"
        elif _first_match(_LOOSE_OFF, n):
            state = "off"
    if state is None and light_context and not strict:
        if _first_match(_PRONOUN_ON, n):
            state = "on"
        elif _first_match(_PRONOUN_OFF, n):
            state = "off"
    if state is None and awaiting_choice and not strict:
        answer = _ANSWER.match(n)
        if answer:
            state = "on" if answer.group(1) == "on" else "off"
            return _Seg("light", state)

    if state is not None:
        devices = _device_names(n)
        if _NOUN_RE.search(n) or (light_context and re.search(rf"\b{_PRONOUN}\b", n)):
            return _Seg("light", state, devices)
        return _Seg("unsupported", None, devices) if devices else _OTHER

    if not strict:
        if _first_match(_CLARIFY, n):
            return _Seg("clarify")
    if _DEVICE_VERB.match(n) and not _NOUN_RE.search(n):
        devices = _device_names(n)
        if devices:
            return _Seg("unsupported", None, devices)
    return _OTHER


def _extract(text: str, light_context: bool, awaiting_choice: bool, depth: int = 0):
    """Return (actions, leftovers): command segments found in `text` and the text pieces that are not commands."""
    whole = _classify(text, light_context, awaiting_choice, strict=False)
    if whole.kind != "other":
        return [whole], []
    reason = _REASON.search(text)
    if reason:
        head = _classify(text[:reason.start()], light_context, awaiting_choice, strict=True)
        if head.kind in ("light", "unsupported"):
            return [head], []          # the reason clause only explains the command; nothing to answer
    if depth < 3:
        for count, match in enumerate(_CONJ.finditer(text)):
            if count >= _MAX_SPLITS:
                break
            left, right = text[:match.start()], text[match.end():]
            left_seg = _classify(left, light_context, awaiting_choice, strict=True)
            if left_seg.kind in ("light", "unsupported"):
                actions, rest = _extract(right, light_context, awaiting_choice, depth + 1)
                return [left_seg] + actions, rest
            right_seg = _classify(right, light_context, awaiting_choice, strict=True)
            if right_seg.kind in ("light", "unsupported"):
                actions, rest = _extract(left, light_context, awaiting_choice, depth + 1)
                return actions + [right_seg], rest
    return [], [text]


def _is_filler(piece: str) -> bool:
    words = _normalize(piece).split()
    return not words or all(w in _FILLER_WORDS for w in words)


def detect_intent(text: str, *, light_context: bool = False, awaiting_choice: bool = False) -> Intent:
    """
    light_context   - a light command was handled very recently in this session, so "turn it off" refers to the light
    awaiting_choice - the assistant just asked "on or off?", so a bare "on" / "off" is the answer
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    actions: List[_Seg] = []
    leftovers: List[str] = []
    for sentence in sentences:
        found, rest = _extract(sentence, light_context, awaiting_choice)
        actions.extend(found)
        leftovers.extend(rest)

    if not actions:
        return Intent(IntentKind.CHAT)

    remainder = " ".join(p.strip(" ,;") for p in leftovers if not _is_filler(p)).strip()
    states = {a.state for a in actions if a.kind == "light"}
    devices: List[str] = []
    for action in actions:
        for name in action.devices:
            if name not in devices:
                devices.append(name)

    if len(states) > 1:                                   # "turn on the light. turn off the light"
        return Intent(IntentKind.CLARIFY, remainder=remainder)
    if len(states) == 1:
        return Intent(IntentKind.LIGHT, state=next(iter(states)), remainder=remainder,
                      unsupported_devices=tuple(devices))
    if any(a.kind == "clarify" for a in actions):
        return Intent(IntentKind.CLARIFY, remainder=remainder)
    return Intent(IntentKind.UNSUPPORTED, remainder=remainder, unsupported_devices=tuple(devices))
