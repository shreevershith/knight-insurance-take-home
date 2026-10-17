"""LLM provider client: one OpenAI-compatible JSON call with timeout, one retry and typed errors.

Works with Groq (default) or a local Ollama server by changing env only:
  LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS
The API key is never logged or returned to the UI.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TIMEOUT = 30.0

# Error kinds worth one more attempt.
TRANSIENT = {"timeout", "rate_limit", "connection", "server", "bad_json", "schema"}


class LLMError(Exception):
    """kind: config | auth | timeout | rate_limit | connection | server | bad_json | schema | other."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


class LLMClient(Protocol):
    provider: str
    model: str

    def chat_json(self, system: str, user: str, *,
                  validate: Optional[Callable[[dict], Any]] = None) -> Any:
        """Return validate(parsed_json) (or the dict). Raises LLMError."""
        ...


@dataclass
class LLMConfig:
    base_url: str
    api_key: Optional[str]
    model: str
    timeout: float

    @classmethod
    def from_env(cls) -> "LLMConfig":
        try:
            timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT)
        except ValueError:
            timeout = DEFAULT_TIMEOUT
        return cls(
            base_url=(os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            api_key=os.environ.get("LLM_API_KEY") or None,
            model=os.environ.get("LLM_MODEL") or DEFAULT_MODEL,
            timeout=timeout,
        )

    @property
    def is_local(self) -> bool:
        host = urlparse(self.base_url).hostname or ""
        return host in ("localhost", "127.0.0.1", "::1")

    @property
    def provider(self) -> str:
        host = urlparse(self.base_url).hostname or self.base_url
        if "groq.com" in host:
            return "Groq"
        if self.is_local and urlparse(self.base_url).port == 11434:
            return "Ollama (local)"
        return host


class OpenAICompatibleClient:
    """Chat-completions client in JSON mode, temperature 0."""

    def __init__(self, config: LLMConfig, retry_delay: float = 2.0):
        self.config = config
        self.provider = config.provider
        self.model = config.model
        self.retry_delay = retry_delay
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            key = self.config.api_key
            if not key:
                if not self.config.is_local:
                    raise LLMError("config", "LLM_API_KEY is not set (see .env.example).")
                key = "ollama"  # local servers ignore the key, but the SDK requires one
            self._client = OpenAI(base_url=self.config.base_url, api_key=key,
                                  timeout=self.config.timeout, max_retries=0)
        return self._client

    def _call_once(self, system: str, user: str) -> str:
        import openai

        client = self._get_client()
        try:
            resp = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
        except openai.APITimeoutError:
            raise LLMError("timeout", f"No response within {self.config.timeout:g} s.")
        except openai.RateLimitError:
            raise LLMError("rate_limit", "Provider rate limit reached (HTTP 429).")
        except openai.AuthenticationError:
            raise LLMError("auth", "Provider rejected the API key (HTTP 401).")
        except openai.APIConnectionError:
            raise LLMError("connection", f"Could not connect to {self.config.base_url}.")
        except openai.APIStatusError as exc:
            kind = "server" if exc.status_code >= 500 else "other"
            raise LLMError(kind, f"Provider returned HTTP {exc.status_code}.")
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        if not content.strip():
            raise LLMError("bad_json", "Model returned an empty response.")
        return content

    def chat_json(self, system: str, user: str, *,
                  validate: Optional[Callable[[dict], Any]] = None) -> Any:
        return run_with_retry(lambda: self._call_once(system, user), validate,
                              retry_delay=self.retry_delay)


def parse_json_object(content: str) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError("bad_json", f"Model output is not valid JSON ({exc.msg}).")
    if not isinstance(data, dict):
        raise LLMError("bad_json", "Model output is not a JSON object.")
    return data


def run_with_retry(call: Callable[[], str], validate: Optional[Callable[[dict], Any]] = None,
                   attempts: int = 2, retry_delay: float = 0.0) -> Any:
    """Call, parse, validate; retry once on transient errors. Shared by real and fake clients."""
    last: Optional[LLMError] = None
    for i in range(attempts):
        try:
            data = parse_json_object(call())
            if validate is None:
                return data
            try:
                return validate(data)
            except (ValueError, TypeError) as exc:  # pydantic ValidationError is a ValueError
                raise LLMError("schema", f"Model output does not match the expected schema: {str(exc)[:300]}")
        except LLMError as exc:
            last = exc
            log.warning("LLM attempt %d failed: %s", i + 1, exc.kind)
            if exc.kind not in TRANSIENT or i == attempts - 1:
                break
            if retry_delay:
                time.sleep(retry_delay)
    assert last is not None
    raise last


def client_from_env() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(LLMConfig.from_env())
