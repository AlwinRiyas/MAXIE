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

    def test_destructive_capability_keying(self):
        """SEC-07: the confirmation gate is capability-keyed, so a new
        destructive intent can't bypass it by mere omission from a
        known-bad list."""
        for intent in ("SHUTDOWN", "RESTART", "DELETE_MEMORY", "FORMAT"):
            self.assertTrue(
                Permissions.requires_confirmation(intent), intent)
        for intent in ("TIME", "OPEN_APP", "SAVE_MEMORY", "AI_CHAT"):
            self.assertFalse(
                Permissions.requires_confirmation(intent), intent)

    def test_confirmation_text_never_suggests_execution(self):
        msg = Permissions.confirmation_for("DELETE_MEMORY_BULK")
        self.assertIn("confirm delete memory bulk", msg)
        self.assertIn("won't", msg)  # asks, never claims to have run

    def test_bulk_delete_words_are_explicit(self):
        self.assertIn("all", Permissions.BULK_DELETE_WORDS)
        self.assertIn("everything", Permissions.BULK_DELETE_WORDS)


if __name__ == "__main__":
    unittest.main()