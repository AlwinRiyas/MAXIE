import unittest
from unittest import mock

from Brain.brain_router import BrainRouter
from Security.permissions import Permissions
from Skills.skill_manager import SkillManager


class _StubAI:
    """Stands in for the model: returns whatever call the test dictates."""

    def __init__(self, call=None, answer="AI said.", raises=None):
        self.call = call
        self.answer = answer
        self.raises = raises
        self.asked_with_tools = []
        self.plain_questions = []

    def ask(self, question):
        self.plain_questions.append(question)
        return self.answer

    def ask_with_tools(self, question, tools):
        self.asked_with_tools.append((question, tools))
        if self.raises is not None:
            raise self.raises
        return self.answer, self.call


class _RealSkills(SkillManager):
    """The real dispatch, with every skill replaced by a recorder so
    nothing real is launched, wiped, or powered off."""

    EXECUTED = []
    REFUSED = []

    def execute(self, intent, value="", extra=None):
        type(self).EXECUTED.append((intent, value))
        return f"did {intent}"

    def _logger(self):
        return mock.MagicMock()


def _router(call=None, mode="smart", **kwargs):
    router = BrainRouter()
    _RealSkills.EXECUTED = []
    _RealSkills.REFUSED = []
    router.command = type("Engine", (), {
        "skills": _RealSkills(),
        "execute": lambda intent, value="", text=None: "unreachable",
    })()
    router.ai = _StubAI(call=call, **kwargs)
    router.routing_mode = mode
    return router


class SmartModeDefaultsTest(unittest.TestCase):
    """The model must not be able to select a skill unless the user asked
    for that autonomy."""

    def setUp(self):
        _RealSkills.EXECUTED = []

    def test_default_mode_is_controlled(self):
        router = BrainRouter()
        self.assertEqual(router.routing_mode, "controlled")

    def test_controlled_mode_ignores_a_proposed_skill(self):
        router = _router(call=("OPEN_APP", {"app": "brave"}),
                         mode="controlled")
        router.process("something the model would like to open")
        self.assertEqual(_RealSkills.EXECUTED, [])
        self.assertEqual(router.ai.plain_questions,
                         ["something the model would like to open"])

    def test_controlled_mode_never_offers_tools(self):
        router = _router(call=("OPEN_APP", {"app": "brave"}),
                         mode="controlled")
        router.process("do the thing with my browser")
        self.assertEqual(router.ai.asked_with_tools, [])
        self.assertEqual(_RealSkills.EXECUTED, [])

    def test_smart_mode_offers_only_allowlisted_tools(self):
        router = _router(call=None, mode="smart")
        router.process("do you know what a prime number is")
        _question, tools = router.ai.asked_with_tools[0]
        names = {t["function"]["name"] for t in tools}
        for name in names:
            self.assertTrue(Permissions.can_execute(name), name)
        self.assertIn("OPEN_APP", names)


class SmartModeDispatchTest(unittest.TestCase):
    def setUp(self):
        _RealSkills.EXECUTED = []

    def test_valid_proposal_runs_the_skill(self):
        router = _router(call=("OPEN_APP", {"app": "brave"}))
        response = router.process("do the thing with my browser")
        self.assertEqual(_RealSkills.EXECUTED, [("OPEN_APP", "brave")])
        self.assertIn("OPEN_APP", response)

    def test_no_proposal_falls_back_to_prose(self):
        router = _router(call=None)
        response = router.process("what is the meaning of life")
        self.assertEqual(response, "AI said.")

    def test_proposal_without_arguments_never_runs(self):
        router = _router(call=("OPEN_APP", {}))
        response = router.process("do the thing with my browser")
        self.assertEqual(_RealSkills.EXECUTED, [])
        self.assertIn("app is required", response)

    def test_extra_argument_is_refused_before_dispatch(self):
        router = _router(call=("OPEN_APP", {"app": "brave",
                                            "command": "rm -rf /"}))
        response = router.process("do something dangerous")
        self.assertEqual(_RealSkills.EXECUTED, [],
                         "a smuggled field must not reach the skill")
        self.assertIn("unknown argument", response)

    def test_wrong_type_is_refused_before_dispatch(self):
        router = _router(call=("OPEN_APP", {"app": {"nested": "object"}}))
        router.process("open the thing")
        self.assertEqual(_RealSkills.EXECUTED, [])

    def test_intent_without_a_schema_is_refused(self):
        router = _router(call=("AI_CHAT", {"text": "hi"}))
        router.process("be chatty")
        self.assertEqual(_RealSkills.EXECUTED, [])


class SmartModeSecurityTest(unittest.TestCase):
    """SEC-07/SEC-11 hold inside smart mode. Autonomy must not become
    a way around the allowlist or the human gate."""

    def setUp(self):
        _RealSkills.EXECUTED = []

    def test_unknown_capability_is_never_reached(self):
        router = _router(call=("RUN_SHELL", {"cmd": "whoami"}))
        router.process("run something for me")
        self.assertEqual(_RealSkills.EXECUTED, [])
        self.assertFalse(Permissions.can_execute("RUN_SHELL"))

    def test_destructive_proposal_is_never_executed(self):
        router = _router(call=("SHUTDOWN", {}))
        response = router.process("shut everything down")
        self.assertEqual(_RealSkills.EXECUTED, [],
                         "a model must not be able to power the machine off")
        self.assertEqual(response, "AI said.")

    def test_restart_proposal_is_never_executed(self):
        router = _router(call=("RESTART", {}))
        router.process("restart whenever you like")
        self.assertEqual(_RealSkills.EXECUTED, [])

    def test_model_cannot_stand_in_for_a_user_confirmation(self):
        """The dangerous sequence: the model proposes the action, and a
        confirmation-shaped turn follows. The proposal arms nothing, so
        there is nothing for a confirmation to consume."""
        router = _router(call=("SHUTDOWN", {}))
        router.process("end this session for good")
        self.assertEqual(_RealSkills.EXECUTED, [])
        self.assertIsNone(router._pending)
        router.ai.call = None
        router.process("yes")
        self.assertEqual(_RealSkills.EXECUTED, [],
                         "a confirmation needs a prompt the user raised")

    def test_model_proposal_leaves_no_pending_prompt(self):
        router = _router(call=("SHUTDOWN", {}))
        router.process("end this session for good")
        self.assertIsNone(router._pending,
                          "a refused proposal must not arm anything")

    def test_destructive_tools_are_not_offered_to_the_model(self):
        """The router would refuse them anyway; not advertising them keeps
        the model from spending a turn trying."""
        router = _router(call=None, mode="smart")
        router.process("do the thing with my browser")
        _question, tools = router.ai.asked_with_tools[0]
        names = {t["function"]["name"] for t in tools}
        for destructive in ("SHUTDOWN", "RESTART", "DELETE_MEMORY"):
            self.assertNotIn(destructive, names)

    def test_failing_model_falls_back_to_a_prose_answer(self):
        router = _router(call=None, raises=RuntimeError("model exploded"))
        response = router.process("tell me a joke")
        self.assertEqual(_RealSkills.EXECUTED, [])
        self.assertEqual(response, "AI said.")

    def test_unoffered_destructive_call_is_still_refused(self):
        """Defence in depth: a model can emit a tool it was never offered,
        so the dispatch-time refusal is the control that matters."""
        router = _router(call=("SHUTDOWN", {}))
        router.process("end this session for good")
        self.assertEqual(_RealSkills.EXECUTED, [])


class RoutingModeConfigTest(unittest.TestCase):
    def test_router_reads_the_configured_mode(self):
        with mock.patch("Config.config.Config.ai_config",
                        return_value={"routing_mode": "SMART"}):
            router = BrainRouter()
        self.assertEqual(router.routing_mode, "smart")

    def test_unknown_mode_falls_back_to_the_safest(self):
        """Config rejects bad modes, but a hand-edited value must not be
        able to switch autonomy on either."""
        with mock.patch("Config.config.Config.ai_config",
                        return_value={"routing_mode": "agent"}):
            router = BrainRouter()
        self.assertEqual(router.routing_mode, "controlled")
        router.ai = _StubAI(call=("OPEN_APP", {"app": "brave"}))
        _RealSkills.EXECUTED = []
        router.process("do a thing")
        self.assertEqual(_RealSkills.EXECUTED, [],
                         "only 'smart' may reach the proposal path")


if __name__ == "__main__":
    unittest.main()
