"""Async LLM client for any OpenAI-compatible Chat Completions API.

Default provider is OpenRouter. Hugging Face Inference Providers, OpenAI itself, or a local
Ollama / vLLM server work too - switching is a .env change only (LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL). The model name lives ONLY in the environment; nothing in the code names a model.

Errors are converted to LLMServiceError whose message is safe to show to clients. Details
(HTTP status, provider error text) go to the server log - never the API key, never the
conversation text.
"""
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import openai
from openai import AsyncOpenAI

logger = logging.getLogger("nfc-welcome.llm")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class LLMServiceError(Exception):
    """Raised for any LLM problem. `public_message` is sanitized and safe to return to clients."""

    def __init__(self, public_message: str, status_code: int = 503):
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s is not a number - using default %s", name, default)
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    max_retries: int
    max_tokens: int
    temperature: Optional[float]
    merge_system_prompt: bool
    site_url: str
    site_title: str

    @classmethod
    def from_env(cls) -> "LLMSettings":
        # Explicit LLM_* variables only. We deliberately do NOT fall back to OPENAI_API_KEY:
        # the OpenAI SDK would otherwise send an old OpenAI key to OpenRouter (a confusing 401).
        api_key = os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()
        if not api_key or not model:
            logger.error("LLM is not configured: set LLM_API_KEY and LLM_MODEL in backend/.env and restart")
            raise LLMServiceError("The assistant is not configured yet.")

        raw_temp = os.getenv("LLM_TEMPERATURE", "0.6").strip()
        temperature: Optional[float] = None
        if raw_temp:  # blank = do not send the parameter (some reasoning models reject it)
            try:
                temperature = float(raw_temp)
            except ValueError:
                logger.warning("LLM_TEMPERATURE is not a number - parameter will not be sent")

        return cls(
            api_key=api_key,
            model=model,
            base_url=os.getenv("LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL,
            timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 20.0),
            max_retries=max(0, _env_int("LLM_MAX_RETRIES", 2)),
            max_tokens=max(16, _env_int("LLM_MAX_TOKENS", 500)),
            temperature=temperature,
            merge_system_prompt=os.getenv("LLM_MERGE_SYSTEM_PROMPT", "").strip().lower() in ("1", "true", "yes"),
            site_url=os.getenv("LLM_SITE_URL", "").strip(),
            site_title=os.getenv("LLM_SITE_TITLE", "").strip(),
        )


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)


def clean_reply(text: str) -> str:
    """Make model output safe to speak: drop reasoning blocks, markdown and line breaks."""
    text = _THINK_BLOCK.sub("", text or "")
    text = _THINK_OPEN.sub("", text)                      # unterminated <think> (cut off by max_tokens)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)       # headings
    text = re.sub(r"^\s*[-\u2022*]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"[*`]+", "", text)                    # bold / italics / code
    text = re.sub(r"\s*\n+\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


class LLMService:
    def __init__(self, settings: LLMSettings, client: Optional[AsyncOpenAI] = None):
        self.settings = settings
        headers: Dict[str, str] = {}
        if settings.site_url:
            headers["HTTP-Referer"] = settings.site_url   # optional OpenRouter attribution
        if settings.site_title:
            headers["X-Title"] = settings.site_title
        self._client = client or AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            default_headers=headers or None,
        )

    def _build_messages(self, system_instruction: str, messages: Sequence[Dict[str, str]]):
        payload = [dict(m) for m in messages]
        if not self.settings.merge_system_prompt:
            return [{"role": "system", "content": system_instruction}] + payload
        # For models that reject the system role: fold the instruction into the first user message.
        for message in payload:
            if message["role"] == "user":
                message["content"] = f"{system_instruction}\n\n{message['content']}"
                return payload
        return [{"role": "user", "content": system_instruction}] + payload

    async def generate(self, system_instruction: str, messages: Sequence[Dict[str, str]]) -> str:
        kwargs = {
            "model": self.settings.model,
            "messages": self._build_messages(system_instruction, messages),
            "max_tokens": self.settings.max_tokens,
        }
        if self.settings.temperature is not None:
            kwargs["temperature"] = self.settings.temperature

        started = time.monotonic()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError:
            logger.warning("LLM request timed out after %.1fs", time.monotonic() - started)
            raise LLMServiceError("The assistant took too long to respond. Please try again.") from None
        except openai.APIConnectionError as exc:
            logger.warning("Cannot reach the LLM provider (%s)", type(exc).__name__)
            raise LLMServiceError("The assistant is temporarily unreachable.") from None
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            logger.error("LLM provider rejected the API key (HTTP %s) - check LLM_API_KEY / LLM_BASE_URL",
                         exc.status_code)
            raise LLMServiceError("The assistant is not configured correctly.") from None
        except openai.RateLimitError:
            logger.warning("LLM provider rate limit / quota reached")
            raise LLMServiceError("The assistant is busy. Please try again in a moment.") from None
        except openai.APIStatusError as exc:
            detail = str(getattr(exc, "message", ""))[:200]
            logger.error("LLM provider returned HTTP %s: %s", exc.status_code, detail)
            raise LLMServiceError("The assistant is temporarily unavailable.") from None
        except openai.OpenAIError as exc:
            logger.error("LLM client error: %s", type(exc).__name__)
            raise LLMServiceError("The assistant is temporarily unavailable.") from None

        choices = getattr(response, "choices", None) or []
        message = choices[0].message if choices else None
        reply = clean_reply((message.content if message else "") or "")
        if not reply:
            finish = choices[0].finish_reason if choices else "no-choices"
            logger.warning("LLM returned no usable text (finish_reason=%s)", finish)
            raise LLMServiceError("The assistant did not return an answer. Please try again.")

        usage = getattr(response, "usage", None)
        logger.info("LLM reply in %.2fs (prompt_tokens=%s completion_tokens=%s)",
                    time.monotonic() - started,
                    getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))
        return reply


_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Lazily build the shared client. Raises LLMServiceError while .env is incomplete,
    so the rest of the API keeps working without LLM settings."""
    global _service
    if _service is None:
        _service = LLMService(LLMSettings.from_env())
    return _service
