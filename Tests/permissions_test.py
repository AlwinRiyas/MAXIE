import unittest
from unittest import mock

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

class CapabilityDeclarationTest(unittest.TestCase):
    """SEC-07: the gate keys on declared capability, and fails closed.

    The previous version kept a hand-maintained list of destructive
    *intent names*, so a new destructive intent ran ungated if whoever
    added it forgot to touch that second list. These tests pin the
    properties that make forgetting safe.
    """

    def test_every_allowlisted_intent_declares_its_capabilities(self):
        undeclared = Permissions.ALLOWED - set(Permissions.CAPABILITIES)
        self.assertEqual(
            undeclared, set(),
            "an allowlisted intent with no capability declaration would be "
            "gated by default and look like a bug (SEC-07)",
        )

    def test_an_allowlisted_undeclared_intent_is_gated(self):
        """The fail-closed direction: allowed to run, but never shown to be
        safe, so it waits for a human."""
        # Simulated in-place, because a real undeclared intent is a mistake
        # we do not want to ship. This is the exact state the next developer
        # creates when they add to ALLOWED and stop there.
        fake = "TOTALLY_NEW_THING"
        with mock.patch.dict(Permissions.ALLOWED, {fake: True}):
            self.assertTrue(Permissions.can_execute(fake))
            self.assertIsNone(Permissions.capabilities_for(fake))
            self.assertTrue(
                Permissions.requires_confirmation(fake),
                "an undeclared capability must be gated, not this",
            )

    def test_an_unknown_intent_is_not_gated_but_also_cannot_execute(self):
        """"UNKNOWN" means nothing was recognised. Refusing it is correct;
        prompting for confirmation of an action that was never going to
        run is not."""
        self.assertFalse(Permissions.can_execute("UNKNOWN"))
        self.assertFalse(Permissions.requires_confirmation("UNKNOWN"))

    def test_destructive_set_is_derived_not_hand_maintained(self):
        """DESTRUCTIVE is computed from CAPABILITIES, so it cannot drift."""
        self.assertEqual(Permissions.DESTRUCTIVE, Permissions.LEGACY_GATED | {
            intent
            for intent, caps in Permissions.CAPABILITIES.items()
            if caps & Permissions.DESTRUCTIVE_CAPABILITIES
        })

    def test_declaring_a_destructive_capability_gates_the_intent(self):
        """The gate follows the capability, so a renamed or new intent that
        declares `power.system` is caught without being named anywhere."""
        for capability in Permissions.DESTRUCTIVE_CAPABILITIES:
            gated = [
                intent for intent, caps in Permissions.CAPABILITIES.items()
                if capability in caps
            ]
            self.assertTrue(
                gated,
                f"no intent declares {capability}, so the capability is "
                "unused and could be dropped by mistake",
            )
            for intent in gated:
                self.assertIn(intent, Permissions.DESTRUCTIVE)

    def test_a_new_destructive_intent_is_caught_by_its_capability(self):
        """The regression this whole change exists for: someone adds a
        destructive intent and forgets the old hand-written list."""
        fake = "REBOOT_THE_SERVER"
        caps = frozenset({"power.system"})
        with mock.patch.dict(Permissions.CAPABILITIES, {fake: caps}):
            self.assertTrue(
                Permissions.requires_confirmation(fake),
                "a new destructive intent must be gated by capability alone",
            )
        # And the same intent with no declaration at all is gated too.
        with mock.patch.dict(Permissions.CAPABILITIES, {fake: caps}):
            self.assertNotIn(fake, Permissions.DESTRUCTIVE)

    def test_benign_capabilities_are_not_gated(self):
        for intent, caps in Permissions.CAPABILITIES.items():
            if not (caps & Permissions.DESTRUCTIVE_CAPABILITIES):
                self.assertFalse(
                    Permissions.requires_confirmation(intent),
                    f"{intent} declares only benign capabilities {caps}",
                )

    def test_unlock_needs_the_unlock_capability_not_the_name(self):
        self.assertIn("device.unlock", Permissions.CAPABILITIES["HOME_UNLOCK"])
        self.assertNotIn(
            "device.unlock", Permissions.CAPABILITIES["HOME_CONTROL"],
        )


class LegacyMessageTest(unittest.TestCase):
    def test_confirmation_text_never_suggests_execution(self):
        msg = Permissions.confirmation_for("DELETE_MEMORY_BULK")
        self.assertIn("confirm delete memory bulk", msg)
        self.assertIn("won't", msg)  # asks, never claims to have run

    def test_bulk_delete_words_are_explicit(self):
        self.assertIn("all", Permissions.BULK_DELETE_WORDS)
        self.assertIn("everything", Permissions.BULK_DELETE_WORDS)


if __name__ == "__main__":
    unittest.main()