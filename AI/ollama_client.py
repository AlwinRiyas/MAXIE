import json
import logging
import time

import requests

from AI.prompts import SYSTEM_PROMPT
from AI.llm_provider import LLMProvider
from Config.config import Config

logger = logging.getLogger(__name__)

CONNECTION_ERROR_MESSAGE = (
    "I can't reach Ollama right now. "
    "Please make sure Ollama is running on this machine."
)
TIMEOUT_MESSAGE = "Ollama took too long to respond. Please try again."
GENERIC_ERROR_MESSAGE = "I hit an error talking to the model. Try again in a moment."
GENERIC_ERROR_PREFIX = "I hit an error talking to the model"


def _default_int(cfg, key, default):
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


class OllamaClient(LLMProvider):
    """Ollama chat client (ROADMAP 9.1/9.2 provider adapter).

    Model/URL/temperature/size all come from Config -> ai section so
    the provider can be swapped without touching Brain or Conversation.
    Optional keyword overrides (``url``, ``retries``, ``retry_delay``,
    ``probe_timeout``) let tests and callers substitute values without
    touching on-disk config.

    Failure strings are the stable module-level constants above; replies
    never embed the provider URL (SEC-05 / ROADMAP 9.9).
    """

    def __init__(self, **overrides):
        cfg = Config.ai_config()

        base = (overrides.get("url") or cfg.get("url")
                or "http://127.0.0.1:11434").rstrip("/")
        self.chat_url = f"{base}/api/chat"
        self.generate_url = f"{base}/api/generate"
        self.tags_url = f"{base}/api/tags"

        self.model = overrides.get("model") or cfg.get("model") or "llama3.2:3b"
        self.temperature = float(overrides.get("temperature")
                                 or cfg.get("temperature", 0.2))
        self.max_tokens = _default_int(overrides, "max_tokens",
                                       _default_int(cfg, "max_tokens", 150))
        self.num_ctx = _default_int(overrides, "num_ctx",
                                    _default_int(cfg, "num_ctx", 2048))
        self.timeout = _default_int(overrides, "timeout",
                                    _default_int(cfg, "timeout", 45))
        self.retries = _default_int(overrides, "retries",
                                    _default_int(cfg, "retries", 2))
        self.retry_delay = float(overrides.get("retry_delay")
                                 or cfg.get("retry_delay_seconds", 1.0))
        self.probe_timeout = float(overrides.get("probe_timeout")
                                   or cfg.get("probe_timeout", 3.0))

    def is_available(self):
        try:
            response = requests.get(self.tags_url, timeout=self.probe_timeout)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def ask(self, prompt, history=None, system=None):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        for role, content in (history or []):
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.num_ctx,
            },
        }

        # ROADMAP 9.7: transient failures (connection reset, timeout,
        # HTTP 429/5xx) retry with linear backoff. Non-transport errors
        # (malformed JSON, coding bugs) fail immediately and collapse to
        # the generic message so a broken request cannot loop.
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(
                    self.chat_url, json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                answer = (
                    data.get("message", {}).get("content")
                    or data.get("response")
                    or ""
                )
                return answer.strip()
            except requests.exceptions.Timeout as error:
                last_error = error
            except requests.exceptions.ConnectionError as error:
                last_error = error
            except requests.exceptions.HTTPError as error:
                code = error.response.status_code if error.response else 0
                if code < 500 and code != 429:
                    logger.warning("Ollama HTTP error %s: %s", code, error)
                    return GENERIC_ERROR_MESSAGE
                last_error = error
            except Exception as error:  # noqa: BLE001 - surface as generic, log detail
                logger.warning("Ollama request error: %s", error)
                return GENERIC_ERROR_MESSAGE

            if attempt >= self.retries:
                return self._final_failure_message(last_error)
            time.sleep(self.retry_delay * (attempt + 1))

        return self._final_failure_message(last_error)

    @staticmethod
    def _final_failure_message(error):
        """Map the last transient failure to the stable user-facing
        string. Never includes the URL or a stack trace (SEC-05)."""
        if isinstance(error, requests.exceptions.Timeout):
            logger.warning("Ollama request timed out after %ss", "retries exhausted")
            return TIMEOUT_MESSAGE
        if isinstance(error, requests.exceptions.ConnectionError):
            logger.warning("Ollama connection failed (b1 classified offline)")
            return CONNECTION_ERROR_MESSAGE
        logger.warning("Ollama request failed after retries: %s", error)
        return GENERIC_ERROR_MESSAGE

    def ask_with_tools(self, prompt, tools, history=None, system=None):
        """Ask the model, offering tool definitions (ROADMAP 12.7).

        Returns ``(text, tool_call)`` where ``tool_call`` is ``None`` or a
        ``(name, arguments)`` pair. Failure strings are the same stable
        messages as :meth:`ask`, so the caller needs one offline filter,
        not two.

        Note the direction of trust: the model *proposes*, the caller
        validates. Nothing here executes anything.
        """
        if not tools:
            return self.ask(prompt, history=history, system=system), None

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        for role, content in (history or []):
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "tools": list(tools),
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.num_ctx,
            },
        }

        last_error = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(
                    self.chat_url, json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                message = response.json().get("message", {}) or {}
                text = (message.get("content") or "").strip()
                return text, self.parse_tool_call(message)
            except requests.exceptions.Timeout as error:
                last_error = error
            except requests.exceptions.ConnectionError as error:
                last_error = error
            except requests.exceptions.HTTPError as error:
                code = error.response.status_code if error.response else 0
                if code < 500 and code != 429:
                    logger.warning("Ollama HTTP error %s: %s", code, error)
                    return GENERIC_ERROR_MESSAGE, None
                last_error = error
            except Exception as error:  # noqa: BLE001 - generic, log detail
                logger.warning("Ollama tool request error: %s", error)
                return GENERIC_ERROR_MESSAGE, None

            if attempt >= self.retries:
                break
            time.sleep(self.retry_delay * (attempt + 1))

        return self._final_failure_message(last_error), None

    @staticmethod
    def parse_tool_call(message):
        """Extract the first tool call from an Ollama message.

        Returns ``(name, arguments)`` or ``None``. A malformed call is
        treated as no call at all: the caller then answers in prose,
        which is the safe direction. Arguments must be a JSON object;
        a bare string is parsed, because models emit both.
        """
        calls = (message or {}).get("tool_calls") or []
        if not calls:
            return None

        function = calls[0].get("function") or {}
        name = str(function.get("name") or "").strip()
        if not name:
            return None

        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                logger.warning("Ollama tool arguments were not valid JSON")
                return None
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            logger.warning("Ollama tool arguments were not an object")
            return None

        return name, arguments

    def ask_generate(self, prompt):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        try:
            response = requests.post(
                self.generate_url, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except requests.RequestException:
            return ""

    @staticmethod
    def system_prompt():
        """Base system prompt (before personality injection)."""
        return SYSTEM_PROMPT