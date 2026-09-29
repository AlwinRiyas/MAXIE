import unittest

from Security.permissions import Permissions


class PermissionsTest(unittest.TestCase):

    def test_allowlist(self):
        for intent in ("TIME", "DATE", "WEATHER", "OPEN_APP", "CLOSE_APP",
                       "CALCULATE", "SEARCH", "VOLUME", "SYSTEM_INFO",
                       "SAVE_MEMORY", "RECALL_MEMORY", "HELP"):
            self.assertTrue(Permissions.can_execute(intent), intent)

    def test_destructive_gated_by_confirmation(self):
        # New design: power actions live in the allowlist but the router
        # only executes them after an explicit yes/confirm, and the LLM is
        # still never executing arbitrary actions.
        self.assertTrue(Permissions.can_execute("SHUTDOWN"))
        self.assertFalse(Permissions.can_execute("FORMAT"))
        self.assertFalse(Permissions.can_execute("UNKNOWN_HACK"))
        killer_intents = "delete everything", "drop database", "rm -rf"
        for text in killer_intents:
            from Brain.intent_engine import IntentEngine

            self.assertNotEqual(IntentEngine().classify(text), "SHUTDOWN")

    def test_confirmation_messages(self):
        self.assertIsNotNone(Permissions.confirmation_for("SHUTDOWN"))
        self.assertIsNotNone(Permissions.confirmation_for("RESTART"))
        self.assertIsNone(Permissions.confirmation_for("TIME"))


if __name__ == "__main__":
    unittest.main()