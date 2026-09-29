import logging
import requests

from Config.config import Config
from AI.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

CONNECTION_ERROR_MESSAGE = (
    "I can't reach Ollama right now. "
    "Please make sure Ollama is running on this machine."
)
TIMEOUT_MESSAGE = "Ollama took too long to respond. Please try again."
GENERIC_ERROR_MESSAGE = "I hit an error talking to the model. Try again in a moment."
GENERIC_ERROR_PREFIX = "I hit an error talking to the model"


class OllamaClient:
    """Ollama chat client (provider abstraction).

    Model/URL/temperature/size all come from Config -> ai section so
    the provider can be swapped without touching Brain or Conversation.
    """

    def __init__(self):
        cfg = Config.ai_config()

        base = (cfg.get("url") or "http://127.0.0.1:11434").rstrip("/")
        self.chat_url = f"{base}/api/chat"
        self.generate_url = f"{base}/api/generate"
        self.tags_url = f"{base}/api/tags"

        self.model = cfg.get("model") or "llama3.2:3b"
        self.temperature = float(cfg.get("temperature", 0.2))
        self.max_tokens = int(cfg.get("max_tokens", 150))
        self.num_ctx = int(cfg.get("num_ctx", 2048))
        self.timeout = int(cfg.get("timeout", 45))

    def is_available(self):
        try:
            response = requests.get(self.tags_url, timeout=3)
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
        except requests.exceptions.ConnectionError:
            logger.warning("Ollama connection failed (b1 classified offline)")
            return CONNECTION_ERROR_MESSAGE
        except requests.exceptions.Timeout:
            logger.warning("Ollama request timed out after %ss", self.timeout)
            return TIMEOUT_MESSAGE
        except Exception as error:  # noqa: BLE001 - surface as generic, log detail
            logger.warning("Ollama request error: %s", error)
            return GENERIC_ERROR_MESSAGE

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