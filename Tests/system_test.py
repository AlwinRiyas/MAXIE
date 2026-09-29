import unittest

from Brain.brain_router import BrainRouter
from Config.config import Config


class _StubSkills:
    """Skill manager stub so no app is actually launched in tests."""

    def execute(self, intent, value="", extra=None):
        if intent == "OPEN_APP":
            return f"Opening {value or extra or 'app'}."
        return "stub"


class BrainRouterTest(unittest.TestCase):

    def setUp(self):
        self.router = BrainRouter()

    def test_time(self):
        response = self.router.process("what time is it")
        self.assertTrue(response.startswith("The time is "))

    def test_date(self):
        response = self.router.process("date")
        self.assertTrue(response.startswith("Today is "))

    def test_calculator(self):
        response = self.router.process("what is 12 times 8")
        self.assertEqual(response, "The answer is 96.")

    def test_calculator_symbols_survive_correction(self):
        response = self.router.process("what is 47 + 53?")
        self.assertEqual(response, "The answer is 100.")
        response = self.router.process("what is the square root of 144")
        self.assertEqual(response, "The answer is 12.")
        response = self.router.process("50 percent of 200")
        self.assertEqual(response, "The answer is 100.")

    def test_open_site(self):
        router = BrainRouter()
        router.command = _StubSkills()
        response = router.process("open youtube")
        self.assertEqual(response, "Opening youtube.")

    def test_memory_save_and_recall(self):
        self.router.process("remember that I like coffee")
        response = self.router.process("what do I like")
        self.assertIn("coffee", response.lower())

    def test_shutdown_requires_confirmation(self):
        response = self.router.process("shutdown the pc")
        self.assertIn("confirm", response.lower())

    def test_help(self):
        response = self.router.process("help")
        self.assertTrue(response.startswith("I'm Maxie"))

    def test_empty_input(self):
        self.assertEqual(self.router.process(""), "I didn't catch that.")

    def test_open_app_routed(self):
        # Route "open chrome" -> OPEN_APP intent without spawning anything.
        router = BrainRouter()
        router.command = _StubSkills()
        response = router.process("open chrome")
        self.assertEqual(response, "Opening chrome.")

    def test_weather_offline_safe(self):
        response = self.router.process("weather")
        self.assertTrue("is" in response or "isn't available" in response)

    def test_greeting(self):
        # GreetingEngine is time-of-day dependent, so assert on a
        # wall-clock-independent property. This previously asserted
        # startswith("Good"), which failed every evening from 22:00 onward
        # because the late-night branch does not start with "Good".
        response = self.router.process("hello maxie")
        self.assertTrue(response, "greeting must not be empty")
        self.assertIn(Config.USER_NAME, response)
        self.assertNotIn("I'm Maxie", response)

    def test_voice_commands_gate(self):
        from Brain.voice_commands import VoiceCommands

        gate = VoiceCommands()
        self.assertTrue(gate.is_stop("stop"))
        self.assertTrue(gate.is_exit("goodbye"))


if __name__ == "__main__":
    unittest.main()