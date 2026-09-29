import re
import time

from AI.ollama_client import (
    CONNECTION_ERROR_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    GENERIC_ERROR_PREFIX,
    OllamaClient,
    TIMEOUT_MESSAGE,
)
from Config.config import Config
from Memory.memory_engine import MemoryEngine

_UNAVAILABLE_RESPONSE = "I couldn't come up with an answer right now."

_OFFLINE_RESPONSES = frozenset({
    CONNECTION_ERROR_MESSAGE,
    TIMEOUT_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    _UNAVAILABLE_RESPONSE,
} | {m.lower() for m in (
    CONNECTION_ERROR_MESSAGE,
    TIMEOUT_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    _UNAVAILABLE_RESPONSE,
)})


class AIEngine:
    """Conversational AI with bounded context and memory injection.

    Holds a short-term context so follow-up questions ("Who created
    it?") resolve correctly. Relevant stored memories are added to the
    system prompt so MAXIE can answer from personal memory.

    Talks to any :class:`AI.llm_provider.LLMProvider`; probes
    availability up-front (cached for a short TTL) so a downed backend
    fails fast instead of burning the full request timeout, and bounds
    the history payload before it reaches the model (ROADMAP 9.3/9.6).
    """

    def __init__(self, client=None, memory=None, availability_ttl=None,
                 max_context_chars=None, max_row_chars=None):
        self.client = client if client is not None else OllamaClient()
        self.memory = memory if memory is not None else MemoryEngine()

        cfg = Config.ai_config()
        if availability_ttl is None:
            availability_ttl = float(cfg.get("availability_ttl_seconds", 10.0))
        self.availability_ttl = availability_ttl
        self.max_context_chars = (
            max_context_chars
            if max_context_chars is not None
            else int(cfg.get("max_context_chars", 6000))
        )
        self.max_row_chars = (
            max_row_chars
            if max_row_chars is not None
            else int(cfg.get("max_context_row_chars", 2000))
        )

        self._probe_at = 0.0
        self._probe_available = True

    def is_available(self):
        """Fail-fast health check (ROADMAP 9.3) — TD-34 fix.

        ``BrainRouter`` / the GUI can call this to tell the user the LLM
        is down before any request is attempted.
        """
        return self.client.is_available()

    def ask(self, question):
        if not question.strip():
            return "I didn't catch that."

        if not self._probe_available or time.monotonic() >= self._probe_at:
            self._probe_available = self.client.is_available()
            self._probe_at = time.monotonic() + self.availability_ttl
            if not self._probe_available:
                return CONNECTION_ERROR_MESSAGE

        history = self._apply_budget(self.memory.get_context())
        system = self._build_system_prompt()

        raw = self.client.ask(question, history=history, system=system)

        answer = self.clean_response(raw) or _UNAVAILABLE_RESPONSE

        if not self._is_offline_message(answer):
            self.memory.add_context("user", question)
            self.memory.add_context("assistant", answer)

        return answer

    def _apply_budget(self, history):
        """Bound the context payload (ROADMAP 9.6).

        ``history`` is ``[(role, content), ...]`` newest-last. Drop the
        oldest rows first until the total fits ``max_context_chars``;
        truncate any single oversized row to ``max_row_chars``. This is
        the client-side guard that keeps num_ctx from being blown by a
        giant stored memory line, independent of server-side limits.
        """
        budget = list(history or [])
        clips = 0
        total = sum(len(content) for _, content in budget)
        while total > self.max_context_chars and len(budget) > 1:
            role, content = budget.pop(0)
            total -= len(content)
            clips += 1

        rows = []
        for idx, (role, content) in enumerate(budget):
            if len(content) > self.max_row_chars:
                content = content[: self.max_row_chars].rstrip() + " ..."
            rows.append((role, content))

        if clips:
            self.logger.info(
                f"AI: context budget dropped {clips} oldest rows")

        return rows

    @property
    def logger(self):
        from Logs.logger import Logger

        return Logger.instance()

    def _build_system_prompt(self):
        base = OllamaClient.system_prompt()
        person = Config.personality()

        name = Config.ASSISTANT_NAME
        user = Config.USER_NAME

        parts = [
            base,
            f"You are {name}, {user}'s personal assistant.",
        ]

        style = (person.get("style") or "").upper()
        if style:
            parts.append(
                f"Follow a {style}-inspired tone: calm, concise, "
                "professional, confident, never arrogant."
            )

        gender = str(person.get("voice_gender", "female")).lower()
        if gender == "female":
            parts.append(
                "Your voice is feminine, composed, and warm — like a "
                "trusted aide. Speak with quiet poise and precision."
            )

        length = person.get("response_length", "short")
        if length == "short":
            parts.append("Prefer short answers (2 to 5 sentences).")
        elif length == "detailed":
            parts.append("Provide detailed answers when appropriate.")

        memories = self.memory.recall_for("", top=0)
        relevant = self.memory.recall_for("")
        if relevant:
            parts.append(
                "Useful personal memories you may reference: "
                + "; ".join(relevant)
            )

        return "\n".join(parts)

    @staticmethod
    def _is_offline_message(answer):
        """Classify assistant output that must never reach memory (B1).

        Four sources: connection, timeout, generic error (any internal
        detail), and the empty-response fallback. Exact-match for the
        stable messages so legitimate answers mentioning Ollama survive;
        prefix-match only for the generic error line.
        """
        lowered = answer.strip().lower()
        if not lowered:
            return True
        if lowered in _OFFLINE_RESPONSES:
            return True
        return lowered.startswith(GENERIC_ERROR_PREFIX.lower())

    def clean_response(self, text):
        if not text:
            return ""

        text = text.replace("\r\n", "\n")

        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        text = re.sub(r"([,.!?;:])([A-Za-z])", r"\1 \2", text)

        text = re.sub(r"[ \t]+", " ", text)

        lines = [line.rstrip() for line in text.split("\n")]
        text = "\n".join(lines)

        return text.strip()