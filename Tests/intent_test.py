import unittest

from Brain.intent_engine import IntentEngine


class IntentEngineTest(unittest.TestCase):

    def setUp(self):
        self.intent = IntentEngine()

    def test_core_queries(self):
        self.assertEqual(self.intent.classify("what time is it"), "TIME")
        self.assertEqual(self.intent.classify("time"), "TIME")
        self.assertEqual(self.intent.classify("what is the date"), "DATE")
        self.assertEqual(self.intent.classify("weather today"), "WEATHER")

    def test_app_verbs(self):
        self.assertEqual(self.intent.classify("open chrome"), "OPEN_APP")
        self.assertEqual(self.intent.classify("launch android studio"), "OPEN_APP")
        self.assertEqual(self.intent.classify("close chrome"), "CLOSE_APP")
        self.assertEqual(self.intent.classify("kill notepad"), "CLOSE_APP")

    def test_memory_intents(self):
        self.assertEqual(self.intent.classify("remember my gym"), "SAVE_MEMORY")
        self.assertEqual(self.intent.classify("what am I learning"), "RECALL_MEMORY")
        self.assertEqual(self.intent.classify("forget my gym"), "DELETE_MEMORY")

    def test_math(self):
        self.assertEqual(self.intent.classify("what is 5 plus 3"), "CALCULATE")
        self.assertEqual(self.intent.classify("calculate 12*8"), "CALCULATE")
        self.assertEqual(self.intent.classify("50 percent of 200"), "CALCULATE")
        self.assertEqual(self.intent.classify("what is the square root of 144"), "CALCULATE")
        self.assertEqual(self.intent.classify("3 squared"), "CALCULATE")

    def test_search(self):
        self.assertEqual(self.intent.classify("search for python"), "SEARCH")

    def test_system(self):
        self.assertEqual(self.intent.classify("system info"), "SYSTEM_INFO")
        self.assertEqual(self.intent.classify("set volume to 40"), "VOLUME")
        self.assertEqual(self.intent.classify("take a screenshot"), "SCREENSHOT")

    def test_destructive_intents(self):
        self.assertEqual(self.intent.classify("shutdown pc"), "SHUTDOWN")
        self.assertEqual(self.intent.classify("restart pc"), "RESTART")

    def test_greeting_and_help(self):
        self.assertEqual(self.intent.classify("hello maxie"), "GREETING")
        self.assertEqual(self.intent.classify("what can you do"), "HELP")

    def test_unknown_falls_back(self):
        self.assertEqual(self.intent.classify("explain quantum physics"), "UNKNOWN")

    def test_bare_skill_verbs_stay_skills(self):
        """Phase 8.7: a bare verb still routes to the skill so the router
        can ask for the missing argument rather than dropping to the AI."""
        self.assertEqual(self.intent.classify("open"), "OPEN_APP")
        self.assertEqual(self.intent.classify("search"), "SEARCH")
        self.assertEqual(self.intent.classify("close"), "CLOSE_APP")
        self.assertEqual(self.intent.classify("kill"), "CLOSE_APP")


if __name__ == "__main__":
    unittest.main()