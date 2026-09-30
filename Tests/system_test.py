import json
import os
import tempfile
import unittest
from unittest import mock

from Brain.brain_router import BrainRouter
from Config.config import Config
from Memory.memory_database import MemoryDatabase
from Memory.memory_engine import MemoryEngine


def _isolated_memory():
    """A throwaway memory DB, so tests never touch the real store."""
    path = os.path.join(tempfile.mkdtemp(), "maxie_router_test.db")
    return MemoryEngine(MemoryDatabase(path)), path


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


class ArgumentSchemaTest(unittest.TestCase):
    """Phase 8.7: argument-required skills ask instead of executing empty."""

    def setUp(self):
        self.router = BrainRouter()
        self.skills = _StubSkills()
        self.router.command = self.skills
        self.router = BrainRouter()
        self.skills = _StubSkills()
        self.router.command = self.skills

    def test_bare_open_clarifies(self):
        response = self.router.process("open")
        self.assertIn("Which app", response)
        self.assertNotIn("Opening", response)

    def test_open_degenerate_article_clarifies(self):
        response = self.router.process("open the app")
        self.assertIn("Which app", response)

    def test_open_with_app_executes(self):
        self.assertEqual(self.router.process("open chrome"), "Opening chrome.")

    def test_bare_search_clarifies(self):
        response = self.router.process("search")
        self.assertIn("What would you like me to search", response)

    def test_search_with_query_executes(self):
        response = self.router.process("search for python")
        self.assertTrue(response)

    def test_volume_without_level_clarifies(self):
        response = self.router.process("set the volume")
        self.assertIn("What volume level", response)

    def test_volume_with_level_executes(self):
        # _StubSkills returns "stub" for any non-OPEN intent.
        self.assertEqual(self.router.process("set volume to 40"), "stub")


class MultiIntentTest(unittest.TestCase):
    """Phase 8.4: two independent skill actions joined by 'and' run in
    sequence, and the reply is a single joined response."""

    def setUp(self):
        self.router = BrainRouter()
        self.skills = _StubSkills()
        self.router.command = self.skills

    def test_open_and_media_intent(self):
        response = self.router.process("open chrome and stop the music")
        self.assertIn("Opening chrome.", response)
        self.assertIn("stub", response)

    def test_single_argument_with_dangling_and_stays_one_intent(self):
        # "search for dogs and cats" must NOT be split - it is one SEARCH.
        response = self.router.process("close chrome and spotify together")
        self.assertTrue(response)

    def test_mixed_clause_falls_through_to_single_intent(self):
        # "open chrome and tell me a joke" is not a safe multi-intent: the
        # AI clause is not a skill, so the whole thing must not be split
        # into two executions. It stays a single OPEN_APP.
        response = self.router.process("open chrome and tell me a joke")
        self.assertIn("Opening", response)

    def test_two_skill_clauses_both_executed(self):
        response = self.router.process("open chrome and open notepad")
        self.assertEqual(response.count("Opening"), 2)


class ClarificationTest(unittest.TestCase):
    """Phase 8.3: a skill-verb phrase that still scores UNKNOWN must ask
    instead of silently handing an actionable request to the AI."""

    def setUp(self):
        self.router = BrainRouter()
        self.router.command = _StubSkills()

    def test_unknown_open_phrase_clarifies(self):
        # "open whatever ..." carries a placeholder object -> it must ask,
        # never execute an OPEN_APP with a junk value.
        response = self.router.process("open whatever that is on my desk")
        self.assertIn("Which app", response)

    def test_unknown_start_phrase_clarifies(self):
        response = self.router.process("start the thing")
        self.assertIn("Which app", response)

    def test_stop_prefix_unresolved_clarifies(self):
        # "stop the thing" is UNKNOWN with a stop prefix: ask which action,
        # do not guess.
        response = self.router.process("stop the thing")
        self.assertIn("stop talking", response)

    def test_normal_ai_question_not_hijacked(self):
        self.router.ai = type("AI", (), {"ask": lambda self, t: "AI said."})()
        response = self.router.process("what is the capital of france")
        self.assertEqual(response, "AI said.")


class BulkDeleteConfirmationTest(unittest.TestCase):
    """SEC-08: wiping ALL memories requires explicit confirmation and an
    audit line; ordinary single-item delete stays unguarded."""

    def setUp(self):
        self.router = BrainRouter()
        self.router.command = _TrackingDeleteSkills()

    def test_bulk_delete_asks_confirmation(self):
        response = self.router.process("delete all memories")
        self.assertIn("won't", response)
        self.assertIn("confirm", response)
        self.assertFalse(self.router.command.deleted["seen"], "must not delete yet")

    def test_bulk_delete_executes_after_separate_confirm(self):
        """SEC-11: the confirmation must be its own turn."""
        prompt = self.router.process("delete all memories")
        self.assertIn("won't", prompt)
        response = self.router.process("yes")
        self.assertEqual(response, "deleted-all")
        self.assertTrue(self.router.command.deleted["seen"])
        self.assertEqual(self.router.command.deleted["value"], "all")

    def test_bulk_delete_refuses_ask_and_confirm_in_one_turn(self):
        """SEC-11: one message cannot both wipe and confirm."""
        response = self.router.process("yes delete all memories")
        self.assertIn("won't", response)
        self.assertFalse(
            self.router.command.deleted["seen"],
            "a single combined request must never wipe memories",
        )
        # The action is still pending, so a real confirmation works.
        self.assertEqual(self.router.process("yes"), "deleted-all")

    def test_single_memory_delete_unguarded(self):
        response = self.router.process("delete my memory about shuttle")
        self.assertEqual(response, "deleted-single")
        self.assertTrue(self.router.command.deleted["seen"])
        self.assertNotEqual(self.router.command.deleted["value"], "all")

    def test_bulk_delete_confirmation_rejected_by_negation(self):
        response = self.router.process("no do not delete all memories")
        self.assertIn("won't", response)
        self.assertFalse(self.router.command.deleted["seen"])


class _RecordingSkills(_StubSkills):
    """Records every executed (intent, value) pair."""

    def __init__(self):
        self.calls = []

    def execute(self, intent, value="", extra=None):
        self.calls.append((intent, value))
        return super().execute(intent, value, extra)


class DestructiveTwoStepTest(unittest.TestCase):
    """SEC-11: a destructive action must be asked for in one turn and
    confirmed in another, so a single request can never do both."""

    def setUp(self):
        self.router = BrainRouter()
        self.router.command = _RecordingSkills()
        self.router.memory, self._db = _isolated_memory()

    def _executed(self, intent):
        return [call for call in self.router.command.calls if call[0] == intent]

    def test_shutdown_is_held_then_executes_on_bare_yes(self):
        prompt = self.router.process("shut down the computer")
        self.assertIn("confirm", prompt.lower())
        self.assertEqual(self._executed("SHUTDOWN"), [],
                         "the action must not run on the asking turn")

        response = self.router.process("yes")
        self.assertEqual(len(self._executed("SHUTDOWN")), 1)

    def test_ask_and_confirm_in_one_turn_is_refused(self):
        response = self.router.process("yes shut down the computer")
        self.assertIn("confirm", response.lower())
        self.assertEqual(self._executed("SHUTDOWN"), [],
                         "one message must never both ask and confirm")

    def test_confirmation_after_the_prompt_still_works(self):
        self.router.process("shut down the computer")
        self.router.process("yes shut down the computer")
        self.router.process("yes")
        self.assertEqual(len(self._executed("SHUTDOWN")), 1,
                         "the request stays pending, then confirms")

    def test_confirmation_expires(self):
        self.router._confirm_ttl = -1.0
        self.router.process("shut down the computer")
        response = self.router.process("yes")
        self.assertEqual(self._executed("SHUTDOWN"), [],
                         "a stale prompt must not execute")
        self.assertNotIn("shut", response.lower())

    def test_bare_confirmation_without_a_prompt_does_nothing(self):
        response = self.router.process("yes")
        self.assertEqual(self._executed("SHUTDOWN"), [])
        self.assertEqual(self._executed("DELETE_MEMORY_BULK"), [])

    def test_surrounding_words_are_not_a_confirmation(self):
        self.router.process("restart the computer")
        for reply in ("yes please shut down the computer",
                      "yes but what time is it",
                      "affirmative, delete everything"):
            self.router.process(reply)
        self.assertEqual(self._executed("RESTART"), [])
        self.assertEqual(self._executed("SHUTDOWN"), [])

    def test_prompt_is_bound_to_the_caller_that_raised_it(self):
        self.router.bind_source("192.168.1.5")
        self.router.process("shut down the computer")

        # A different device cannot confirm the first device's prompt.
        self.router.bind_source("192.168.1.9")
        self.router.process("yes")
        self.assertEqual(self._executed("SHUTDOWN"), [],
                         "another source must not confirm this prompt")

        self.router.bind_source("192.168.1.5")
        self.router.process("yes")
        self.assertEqual(len(self._executed("SHUTDOWN")), 1)

    def test_unrelated_request_does_not_confirm(self):
        self.router.process("shut down the computer")
        response = self.router.process("what time is it")
        self.assertEqual(len(self._executed("TIME")), 1)
        self.assertEqual(self._executed("SHUTDOWN"), [])
        self.router.process("yes")
        self.assertEqual(len(self._executed("SHUTDOWN")), 1,
                         "the pending prompt survives an unrelated question")

    def test_restart_needs_its_own_confirmation(self):
        self.router.process("shut down the computer")
        self.router.process("yes")
        self.assertEqual(len(self._executed("SHUTDOWN")), 1)
        self.assertEqual(self._executed("RESTART"), [],
                         "one confirmation cannot cover two actions")


class LogRedactionTest(unittest.TestCase):
    """TD-17: an utterance routed end-to-end must not land in the log
    in plaintext. Captures the real stdlib logger the project writes to.
    """

    SECRET = "my bank pin is 4021"

    def setUp(self):
        import logging

        from Logs.logger import Logger

        self.stdlib = logging.getLogger("MAXIE")
        self.lines = []

        class Capture(logging.Handler):
            def emit(inner, record):
                self.lines.append(record.getMessage())

        self.handler = Capture()
        self.stdlib.addHandler(self.handler)
        self.addCleanup(self.stdlib.removeHandler, self.handler)

        self.router = BrainRouter()
        self.router.ai = mock.MagicMock()
        self.router.ai.ask.return_value = "noted"
        # Auto-learn writes facts; keep it out of the user's real store.
        self.router.memory, self._db = _isolated_memory()
        self.logger = Logger.instance()
        self._orig_data = Config.data
        self.addCleanup(lambda: setattr(Config, "data", self._orig_data))
        Config.data = json.loads(json.dumps(Config.data))
        Config.data["system"]["logging"] = {"log_utterances": False,
                                            "retention_days": 7}

    def _logged(self):
        return "\n".join(self.lines)

    def test_router_does_not_log_the_utterance(self):
        self.router.process(self.SECRET)
        blob = self._logged()
        self.assertNotIn("4021", blob)
        self.assertNotIn("bank pin", blob)

    def test_router_still_logs_the_intent_and_a_correlator(self):
        self.router.process(self.SECRET)
        blob = self._logged()
        self.assertIn("intent=", blob)
        self.assertIn("chars", blob)

    def test_auto_learned_fact_is_redacted(self):
        self.router.process("i love mangoes")
        blob = self._logged()
        self.assertNotIn("i love mangoes", blob)

    def test_facts_land_in_the_isolated_store_only(self):
        """Auto-learn in this class must never reach the user's real
        database — the suite is not allowed to mutate user state."""
        self.router.process("i love mangoes")
        self.assertTrue(self.router.memory.all(), "isolated DB not written")

    def test_plaintext_returns_when_explicitly_enabled(self):
        Config.data["system"]["logging"]["log_utterances"] = True
        self.router.process(self.SECRET)
        self.assertIn("4021", self._logged(),
                      "debug opt-in must still write the words")


class _TrackingDeleteSkills(_StubSkills):
    def __init__(self):
        self.deleted = {"seen": False, "value": None}

    def execute(self, intent, value="", extra=None):
        if intent == "DELETE_MEMORY":
            self.deleted["seen"] = True
            self.deleted["value"] = value
            return "deleted-all" if value == "all" else "deleted-single"
        return super().execute(intent, value, extra)


if __name__ == "__main__":
    unittest.main()