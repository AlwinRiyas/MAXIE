import unittest

from AI.ai_engine import AIEngine


class _FakeClient:
    """Stub OllamaClient that never hits the network."""

    def __init__(self):
        self.asked = None

    def ask(self, prompt, history=None, system=None):
        self.asked = {"prompt": prompt, "history": history or [], "system": system}
        return "Certainly. That is a clean, confident answer."


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


if __name__ == "__main__":
    unittest.main()