import requests

from Config.config import Config
from AI.prompts import SYSTEM_PROMPT


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
            return (
                "I can't reach Ollama right now. "
                "Please make sure Ollama is running on this machine."
            )
        except requests.exceptions.Timeout:
            return "Ollama took too long to respond. Please try again."
        except Exception as error:
            return f"I hit an error talking to the model: {error}"

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