import unittest

from AI.ai_engine import AIEngine


class _FakeClient:
    """Stub OllamaClient that never hits the network."""

    def __init__(self):
        self.asked = None
        self.response = "Certainly. That is a clean, confident answer."

    def ask(self, prompt, history=None, system=None):
        self.asked = {"prompt": prompt, "history": history or [], "system": system}
        return self.response


class _FakeMemory:
    def __init__(self):
        self.history = []

    def get_context(self):
        return list(self.history)

    def add_context(self, role, text):
        self.history.append((role, text))

    def recall_for(self, prompt, top=3):
        return []


class AIEngineTest(unittest.TestCase):

    def setUp(self):
        self.client = _FakeClient()
        self.memory = _FakeMemory()
        self.ai = AIEngine(client=self.client, memory=self.memory)

    def test_ask_returns_cleaned_answer(self):
        answer = self.ai.ask("What is Python?")
        self.assertIn("clean, confident answer", answer)
        self.assertEqual(len(self.memory.history), 2)
        self.assertEqual(self.memory.history[0], ("user", "What is Python?"))

    def test_ask_stores_context_sent_to_model(self):
        self.ai.ask("Hello")
        # First round trip: no prior history.
        self.assertEqual(self.client.asked["history"], [])
        self.assertEqual(self.memory.history, [
            ("user", "Hello"),
            ("assistant", "Certainly. That is a clean, confident answer."),
        ])

    def test_follow_up_carries_context(self):
        self.ai.ask("Hello")
        self.ai.ask("Who created you?")
        self.assertEqual(
            self.client.asked["history"][-2:],
            [("user", "Hello"),
             ("assistant", "Certainly. That is a clean, confident answer.")],
        )

    def test_empty_input_guarded(self):
        self.assertEqual(self.ai.ask("   "), "I didn't catch that.")

    def test_system_prompt_mentions_persona(self):
        prompt = self.ai._build_system_prompt()
        self.assertIn("personal assistant", prompt.lower())
        self.assertIn("MAXIE", prompt)

    def test_clean_response_trims_and_spaces(self):
        self.assertEqual(
            self.ai.clean_response("  Hello   world ,how are you?  "),
            "Hello world, how are you?",
        )

    def test_all_four_failure_modes_never_persist(self):
        """B1: every Ollama failure string must be classified offline."""
        from AI.ollama_client import (
            CONNECTION_ERROR_MESSAGE,
            GENERIC_ERROR_PREFIX,
            TIMEOUT_MESSAGE,
        )

        failures = [
            CONNECTION_ERROR_MESSAGE,
            TIMEOUT_MESSAGE,
            f"{GENERIC_ERROR_PREFIX} connection reset by peer",
            "I couldn't come up with an answer right now.",
        ]
        for message in failures:
            self.assertTrue(
                self.ai._is_offline_message(message),
                f"failure string not filtered: {message!r}",
            )

    def test_offline_failure_not_persisted(self):
        self.client.response = (
            "I can't reach Ollama right now. "
            "Please make sure Ollama is running on this machine."
        )
        answer = self.ai.ask("hello")
        self.assertEqual(self.memory.history, [], "offline answer leaked to memory")

    def test_timeout_failure_not_persisted(self):
        self.client.response = (
            "Ollama took too long to respond. Please try again."
        )
        self.ai.ask("hello")
        self.assertEqual(self.memory.history, [], "timeout answer leaked to memory")

    def test_generic_error_not_persisted(self):
        self.client.response = "I hit an error talking to the model: boom"
        self.ai.ask("hello")
        self.assertEqual(self.memory.history, [], "generic error leaked to memory")

    def test_empty_response_fallback_not_persisted(self):
        self.client.response = ""
        self.ai.ask("hello")
        self.assertEqual(
            self.memory.history, [], "empty-response fallback leaked to memory"
        )

    def test_legit_ollama_mention_is_not_filtered(self):
        self.client.response = (
            "Ollama is running and the model is ready. Ask anything."
        )
        answer = self.ai.ask("hello")
        self.assertIn("Ollama is running", answer)
        self.assertEqual(
            len(self.memory.history), 2,
            "a legitimate prose answer must still be persisted",
        )


if __name__ == "__main__":
    unittest.main()