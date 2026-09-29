import re

from AI.ollama_client import OllamaClient
from Config.config import Config
from Memory.memory_engine import MemoryEngine


class AIEngine:
    """Conversational AI with bounded context and memory injection.

    Holds a short-term context so follow-up questions ("Who created
    it?") resolve correctly. Relevant stored memories are added to the
    system prompt so MAXIE can answer from personal memory.
    """

    def __init__(self, client=None, memory=None):
        self.client = client if client is not None else OllamaClient()
        self.memory = memory if memory is not None else MemoryEngine()

    def ask(self, question):
        if not question.strip():
            return "I didn't catch that."

        history = self.memory.get_context()
        system = self._build_system_prompt()

        raw = self.client.ask(question, history=history, system=system)

        answer = self.clean_response(raw) or (
            "I couldn't come up with an answer right now."
        )

        if not self._is_offline_message(answer):
            self.memory.add_context("user", question)
            self.memory.add_context("assistant", answer)

        return answer

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
        lowered = answer.lower()
        return "ollama" in lowered and "running" in lowered

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