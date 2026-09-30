"""Phase 12.2-12.8: the bounded agent loop.

These tests are mostly refusals on purpose. The value of an autonomous
loop is not that it can do more; it is that every path where it could do
something unsafe stops before the dispatch, and each of those stops has a
test here that fails if the stop is removed.
"""

import json
import unittest
from unittest import mock

from AI.llm_planner import PLAN_SHAPE, parse_plan, plan_prompt
from Brain.brain_router import BrainRouter
from Config.config import Config, ConfigError
from Security.permissions import Permissions
from Skills.agent_executor import AgentExecutor
from Skills.skill_manager import SkillManager
from Skills.skill_result import SkillResult, is_undo_spec


def _accept(skill, arguments):
    return None


def _refuse(skill, arguments):
    return f"{skill} is not allowed"


class PlanParsingTest(unittest.TestCase):
    def test_a_good_plan_parses(self):
        raw = json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
            {"skill": "TIME", "arguments": {}},
        ]})
        plan = parse_plan(raw, _accept)
        self.assertEqual([step[0] for step in plan], ["OPEN_APP", "TIME"])

    def test_a_fenced_reply_still_parses(self):
        raw = '```json\n{"steps": [{"skill": "TIME", "arguments": {}}]}\n```'
        self.assertIsNotNone(parse_plan(raw, _accept))

    def test_a_bare_array_parses(self):
        raw = json.dumps([{"skill": "TIME", "arguments": {}}])
        self.assertIsNotNone(parse_plan(raw, _accept))

    def test_prose_is_not_a_plan(self):
        self.assertIsNone(parse_plan("Sure! I opened brave.", _accept))

    def test_an_empty_plan_is_not_a_plan(self):
        self.assertIsNone(parse_plan('{"steps": []}', _accept))
        self.assertIsNone(parse_plan('{"steps": "open brave"}', _accept))
        self.assertIsNone(parse_plan("null", _accept))
        self.assertIsNone(parse_plan(None, _accept))

    def test_a_step_without_a_skill_is_rejected(self):
        raw = json.dumps({"steps": [{"arguments": {"app": "brave"}}]})
        self.assertIsNone(parse_plan(raw, _accept))

    def test_non_dict_arguments_are_rejected(self):
        raw = json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": "brave"}]})
        self.assertIsNone(parse_plan(raw, _accept))

    def test_the_validator_gets_the_final_word(self):
        raw = json.dumps({"steps": [{"skill": "SHUTDOWN", "arguments": {}}]})
        self.assertIsNone(parse_plan(raw, _refuse))
        self.assertIsNotNone(parse_plan(raw, _accept))

    def test_one_bad_step_discards_the_whole_plan(self):
        """A plan is not half-trusted: if any step fails the gate, none of
        it runs. Partly executing a rejected plan is how a model gets a
        foothold it was refused."""
        raw = json.dumps({"steps": [
            {"skill": "TIME", "arguments": {}},
            {"skill": "SHUTDOWN", "arguments": {}},
        ]})
        self.assertIsNone(parse_plan(raw, _refuse))

    def test_a_repeated_step_is_not_a_plan(self):
        raw = json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
        ]})
        self.assertIsNone(parse_plan(raw, _accept))

    def test_argument_order_does_not_defeat_loop_detection(self):
        raw = json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave", "extra": 1}},
            {"skill": "OPEN_APP", "arguments": {"extra": 1, "app": "brave"}},
        ]})
        self.assertIsNone(parse_plan(raw, _accept))

    def test_the_step_count_is_capped(self):
        # distinct steps: an identical repeat is caught by loop detection,
        # which would mask what this test is checking.
        raw = json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": f"app{index}"}}
            for index in range(6)]})
        self.assertIsNone(parse_plan(raw, _accept, max_steps=4))
        self.assertIsNotNone(parse_plan(raw, _accept, max_steps=6))


class PlanPromptTest(unittest.TestCase):
    def test_the_prompt_lists_only_offered_tools(self):
        tools = SkillManager.tool_schemas()
        prompt = plan_prompt("do the thing", tools)
        for tool in tools:
            self.assertIn(tool["function"]["name"], prompt)
        for name in ("SHUTDOWN", "RESTART"):
            self.assertNotIn(f"- {name}:", prompt)

    def test_the_prompt_asks_for_the_documented_shape(self):
        prompt = plan_prompt("do the thing", SkillManager.tool_schemas())
        self.assertIn('"steps"', PLAN_SHAPE)
        self.assertIn('{"steps": []}', prompt)  # the "no tool helps" answer
        self.assertIn("do the thing", prompt)

    def test_the_documented_shape_is_what_the_parser_accepts(self):
        sample = PLAN_SHAPE.replace("SKILL_NAME", "TIME").replace(
            "{...}", "{}")
        self.assertIsNotNone(parse_plan(sample, _accept))


class _Skills(SkillManager):
    """Real dispatch, real schemas, every skill replaced by a recorder."""

    EXECUTED = []
    RESPONSES = {}

    def execute(self, intent, value="", extra=None):
        type(self).EXECUTED.append((intent, value))
        return self.RESPONSES.get(
            (intent, value),
            self.RESPONSES.get(intent, f"did {intent.lower()}"))

    def _logger(self):
        return mock.MagicMock()


def _executor(plan, max_iterations=4, responses=None):
    _Skills.EXECUTED = []
    _Skills.RESPONSES = dict(responses or {})
    return AgentExecutor(_Skills(), mock.MagicMock(),
                         max_iterations=max_iterations), plan


class ResultTypeTest(unittest.TestCase):
    def test_failure_carries_the_reason(self):
        result = SkillResult.failure("OPEN_APP", "no such app")
        self.assertFalse(result.ok)
        self.assertIn("no such app", result.describe())

    def test_success_prefers_the_skill_s_own_words(self):
        result = SkillResult.success("TIME", "It is half past three.")
        self.assertEqual(result.describe(), "It is half past three.")

    def test_signature_ignores_key_order(self):
        a = SkillResult.success("OPEN_APP").with_arguments(
            {"app": "brave", "x": 1})
        b = SkillResult.success("OPEN_APP").with_arguments(
            {"x": 1, "app": "brave"})
        self.assertEqual(a.signature(), b.signature())

    def test_signature_survives_unserialisable_arguments(self):
        result = SkillResult.success("OPEN_APP").with_arguments(
            {"app": object()})
        self.assertIn("OPEN_APP", result.signature())

    def test_undo_specs_are_checked_not_trusted(self):
        self.assertTrue(is_undo_spec(("TODO_REMOVE", {"n": 1})))
        self.assertFalse(is_undo_spec(("TODO_REMOVE", "n")))
        self.assertFalse(is_undo_spec(("TODO_REMOVE",)))
        self.assertFalse(is_undo_spec(None))
        self.assertFalse(is_undo_spec("TODO_REMOVE"))


class ExecutorCeilingTest(unittest.TestCase):
    def test_a_plan_runs_in_order(self):
        executor, plan = _executor([
            ("OPEN_APP", {"app": "brave"}, "open it"),
            ("TIME", {}, "then say the time"),
        ])
        results = executor.execute(plan)
        self.assertEqual([r.skill for r in results],
                         ["OPEN_APP", "TIME"])
        self.assertTrue(all(r.ok for r in results))

    def test_the_iteration_cap_is_hard(self):
        executor, plan = _executor(
            [("OPEN_APP", {"app": f"app{index}"}, "step")
             for index in range(8)], max_iterations=3)
        results = executor.execute(plan)
        dispatched = [r for r in results
                      if r.skill not in ("AGENT_STEP_LIMIT",)]
        self.assertEqual(len(dispatched), 3)
        self.assertIn("AGENT_STEP_LIMIT", [r.skill for r in results])
        self.assertEqual(len(_Skills.EXECUTED), 3)

    def test_a_cap_of_zero_is_clamped_to_one(self):
        executor, _plan = _executor([], max_iterations=0)
        self.assertEqual(executor.max_iterations, 1)

    def test_a_repeated_step_stops_the_run(self):
        """Loop detection at dispatch time, for a plan that arrived with a
        duplicate already in it (parse_plan also rejects those, so this
        covers the executor used on its own)."""
        executor, plan = _executor([
            ("OPEN_APP", {"app": "brave"}, "first"),
            ("OPEN_APP", {"app": "brave"}, "again"),
        ])
        results = executor.execute(plan)
        self.assertIn("AGENT_LOOP", [r.skill for r in results])
        self.assertEqual(len(_Skills.EXECUTED), 1)

    def test_an_empty_plan_reports_rather_than_returning_nothing(self):
        executor, plan = _executor([])
        results = executor.execute([])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].skill, "AGENT_NO_STEPS")


class ExecutorRefusalTest(unittest.TestCase):
    """Every dispatch-time gate. These four are the reason the executor is
    safe to hand a plan to at all."""

    def test_a_destructive_step_is_refused_even_in_a_valid_plan(self):
        executor, plan = _executor([("SHUTDOWN", {}, "power off")])
        results = executor.execute(plan)
        self.assertFalse(results[0].ok)
        self.assertEqual(_Skills.EXECUTED, [])
        self.assertEqual(results[0].error, "SHUTDOWN is destructive and was "
                                           "not offered")

    def test_a_restart_is_refused_too(self):
        executor, plan = _executor([("RESTART", {}, "reboot")])
        self.assertFalse(executor.execute(plan)[0].ok)
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_non_allowlisted_step_is_refused(self):
        executor, plan = _executor([("NOT_A_SKILL", {}, "imagine")])
        results = executor.execute(plan)
        self.assertFalse(results[0].ok)
        self.assertEqual(_Skills.EXECUTED, [])

    def test_schema_invalid_arguments_are_refused_before_dispatch(self):
        executor, plan = _executor([("OPEN_APP", {"app": ""}, "empty")])
        results = executor.execute(plan)
        self.assertFalse(results[0].ok)
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_skill_without_a_schema_is_refused(self):
        executor, plan = _executor([("AI_CHAT", {}, "think"),])
        results = executor.execute(plan)
        self.assertFalse(results[0].ok)
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_failing_step_stops_the_remaining_plan(self):
        executor, plan = _executor(
            [("OPEN_APP", {"app": "brave"}, "ok"),
             ("OPEN_APP", {"app": "libre"}, "not installed"),
             ("TIME", {}, "never reached")],
            responses={
                ("OPEN_APP", "libre"):
                    "I don't know how to do that yet."})
        results = executor.execute(plan)
        self.assertEqual([r.skill for r in results], ["OPEN_APP", "OPEN_APP"])
        self.assertFalse(results[-1].ok)
        self.assertEqual(_Skills.EXECUTED, [("OPEN_APP", "brave"),
                                            ("OPEN_APP", "libre")])

    def test_a_capability_not_in_the_allowlist_never_reaches_a_skill(self):
        """Permissions are read from the module at dispatch time, so a
        plan built while a capability was allowed cannot outlive the
        refusal."""
        executor, plan = _executor([("OPEN_APP", {"app": "brave"}, "open")])
        with mock.patch.object(Permissions, "can_execute",
                               return_value=False):
            results = executor.execute(plan)
        self.assertFalse(results[0].ok)
        self.assertEqual(_Skills.EXECUTED, [])


class RollbackTest(unittest.TestCase):
    def _results_with_undo(self, undo):
        return [
            SkillResult.success("OPEN_APP", "opened").with_arguments(
                {"app": "brave"}),
            SkillResult.success("TODO_ADD", "added milk", undo=undo),
        ]

    def test_a_declared_compensation_runs(self):
        executor, _plan = _executor([])
        outcome = executor.rollback(self._results_with_undo(
            ("TODO_REMOVE", {"task": "milk"})))
        self.assertEqual(outcome["reverted"], ["TODO_ADD"])
        self.assertTrue(outcome["complete"])
        self.assertIn(("TODO_REMOVE", "milk"), _Skills.EXECUTED)

    def test_rollback_is_reverse_order(self):
        executor, _plan = _executor([])
        results = [
            SkillResult.success("TODO_ADD", "first", undo=(
                "TODO_REMOVE", {"task": "a"})).with_arguments({"item": "a"}),
            SkillResult.success("TODO_ADD", "second", undo=(
                "TODO_REMOVE", {"task": "b"})).with_arguments({"item": "b"}),
        ]
        executor.rollback(results)
        self.assertEqual([value for _intent, value in _Skills.EXECUTED],
                         ["b", "a"])

    def test_a_compensation_with_the_wrong_argument_name_is_reported(self):
        """TODO_REMOVE takes "task"; an undo hook that says "item" is a
        skill bug, and the user is told the rollback was partial instead
        of being told everything went back."""
        executor, _plan = _executor([])
        outcome = executor.rollback(
            self._results_with_undo(("TODO_REMOVE", {"item": "milk"})))
        self.assertEqual(outcome["reverted"], [])
        self.assertFalse(outcome["complete"])
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_step_with_no_compensation_is_left_alone(self):
        executor, _plan = _executor([])
        results = [SkillResult.success("TIME", "half past").with_arguments({})]
        outcome = executor.rollback(results)
        self.assertEqual(outcome["reverted"], [])
        self.assertTrue(outcome["complete"])
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_destructive_compensation_is_refused(self):
        executor, _plan = _executor([])
        outcome = executor.rollback(
            self._results_with_undo(("SHUTDOWN", {})))
        self.assertEqual(outcome["reverted"], [])
        self.assertFalse(outcome["complete"])
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_non_allowlisted_compensation_is_refused(self):
        executor, _plan = _executor([])
        outcome = executor.rollback(
            self._results_with_undo(("NOT_A_SKILL", {})))
        self.assertFalse(outcome["complete"])
        self.assertEqual(_Skills.EXECUTED, [])

    def test_a_malformed_compensation_is_ignored_not_raised(self):
        executor, _plan = _executor([])
        outcome = executor.rollback(self._results_with_undo("TODO_REMOVE"))
        self.assertEqual(outcome["reverted"], [])
        self.assertEqual(_Skills.EXECUTED, [])

    def test_rollback_is_idempotent(self):
        executor, _plan = _executor([])
        results = self._results_with_undo(("TODO_REMOVE", {"task": "milk"}))
        executor.rollback(results)
        executor.rollback(results)
        self.assertEqual(len(_Skills.EXECUTED), 1)

    def test_a_failed_compensation_is_reported_as_partial(self):
        executor, _plan = _executor([])
        outcome = executor.rollback(
            self._results_with_undo(("TODO_REMOVE", {"task": ""})))
        self.assertFalse(outcome["complete"])
        self.assertTrue(outcome["failures"])


class AgentModeConfigTest(unittest.TestCase):
    def _validate(self, **ai):
        return Config.validate({"system": {"ai": dict(ai)}})

    def test_agent_mode_needs_the_explicit_opt_in(self):
        with self.assertRaises(ConfigError) as caught:
            self._validate(routing_mode="agent", agent_enabled=False)
        self.assertIn("agent_enabled", str(caught.exception))

    def test_the_opt_in_makes_it_legal(self):
        data = self._validate(routing_mode="agent", agent_enabled=True)
        self.assertEqual(data["system"]["ai"]["routing_mode"], "agent")

    def test_controlled_and_smart_need_no_opt_in(self):
        for mode in ("controlled", "smart"):
            self.assertEqual(
                self._validate(routing_mode=mode)["system"]["ai"][
                    "routing_mode"], mode)

    def test_the_ceilings_are_bounded(self):
        for field in ("agent_max_iterations", "agent_max_steps"):
            with self.assertRaises(ConfigError):
                self._validate(routing_mode="agent", agent_enabled=True,
                               **{field: 999})
            with self.assertRaises(ConfigError):
                self._validate(routing_mode="agent", agent_enabled=True,
                               **{field: 0})

    def test_the_defaults_are_off_and_capped(self):
        defaults = Config.DEFAULT_SYSTEM["ai"]
        self.assertFalse(defaults["agent_enabled"])
        self.assertEqual(defaults["routing_mode"], "controlled")
        self.assertLessEqual(defaults["agent_max_iterations"], 10)

    def test_the_router_ignores_agent_mode_without_the_opt_in(self):
        """Config refuses the pair at load time; a value poked into memory
        by a caller must not skip that check."""
        with mock.patch("Config.config.Config.ai_config", return_value={
                "routing_mode": "agent", "agent_enabled": False}):
            router = BrainRouter()
        self.assertEqual(router.routing_mode, "controlled")


class _StubAI:
    def __init__(self, plan=None, answer="AI said.", raises=None):
        self.plan = plan
        self.answer = answer
        self.raises = raises
        self.json_prompts = []
        self.plain_questions = []

    def ask(self, question):
        self.plain_questions.append(question)
        return self.answer

    def ask_json(self, prompt, schema_hint="", history=None, system=None):
        self.json_prompts.append((prompt, schema_hint))
        if self.raises is not None:
            raise self.raises
        return self.plan


def _agent_router(plan=None, **kwargs):
    router = BrainRouter()
    _Skills.EXECUTED = []
    _Skills.RESPONSES = {}
    router.command = type("Engine", (), {
        "skills": _Skills(),
        "execute": lambda *a, **k: "unreachable",
    })()
    router.ai = _StubAI(plan=plan, **{k: v for k, v in kwargs.items()
                                      if k in ("answer", "raises")})
    router.routing_mode = "agent"
    router.agent_enabled = True
    router.agent_max_iterations = kwargs.get("max_iterations", 4)
    router.agent_max_steps = kwargs.get("max_steps", 4)
    return router


class AgentModeRoutingTest(unittest.TestCase):
    def test_a_multi_step_goal_runs_every_step(self):
        router = _agent_router(plan=json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave"},
             "why": "open it"},
            {"skill": "TIME", "arguments": {}, "why": "then the time"},
        ]}))
        response = router.process("put milk on my shopping list then open brave")
        self.assertEqual(
            [intent for intent, _v in _Skills.EXECUTED],
            ["OPEN_APP", "TIME"])
        self.assertIn("open_app", response)
        self.assertIn("did time", response)

    def test_the_planner_is_only_asked_for_the_tools_it_may_use(self):
        router = _agent_router(plan=json.dumps(
            {"steps": [{"skill": "TIME", "arguments": {}}]}))
        router.process("do something vague for me")
        prompt, hint = router.ai.json_prompts[0]
        self.assertEqual(hint, PLAN_SHAPE)
        self.assertIn("OPEN_APP", prompt)
        self.assertNotIn("- SHUTDOWN:", prompt)

    def test_a_plan_naming_a_destructive_skill_runs_nothing(self):
        router = _agent_router(plan=json.dumps({"steps": [
            {"skill": "TIME", "arguments": {}},
            {"skill": "SHUTDOWN", "arguments": {}},
        ]}))
        router.process("add milk to the list and then shut down")
        self.assertEqual(_Skills.EXECUTED, [])
        self.assertEqual(router.ai.plain_questions,
                         ["add milk to the list and then shut down"])

    def test_a_deterministic_command_never_reaches_the_planner(self):
        router = _agent_router(plan=json.dumps(
            {"steps": [{"skill": "TIME", "arguments": {}}]}))
        router.process("open brave")
        self.assertEqual(router.ai.json_prompts, [])

    def test_an_unusable_plan_falls_back_to_prose(self):
        for plan in ("I will open brave", '{"steps": []}', None):
            router = _agent_router(plan=plan)
            response = router.process("do something vague for me")
            self.assertEqual(response, "AI said.")
            self.assertEqual(_Skills.EXECUTED, [])

    def test_a_planner_that_raises_falls_back_to_prose(self):
        router = _agent_router(raises=RuntimeError("ollama down"))
        response = router.process("do something vague for me")
        self.assertEqual(response, "AI said.")
        self.assertEqual(_Skills.EXECUTED, [])

    def test_the_step_ceiling_applies_to_a_model_proposal(self):
        router = _agent_router(
            plan=json.dumps({"steps": [
                {"skill": "OPEN_APP",
                 "arguments": {"app": f"app{index}"}}
                for index in range(6)]}),
            max_steps=2)
        router.process("do a lot of things")
        self.assertLessEqual(len(_Skills.EXECUTED), 2)

    def test_a_mid_plan_failure_is_reported_and_the_run_stops(self):
        """The step that fails is still dispatched -- it is the step after
        it that must not be, and the user is told the run stopped there."""
        router = _agent_router(plan=json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
            {"skill": "TIME", "arguments": {}},
            {"skill": "OPEN_APP", "arguments": {"app": "firefox"}},
        ]}))
        _Skills.RESPONSES[("TIME", "")] = \
            "I don't know how to do that yet."
        response = router.process("i want to read some news in brave")
        executed = [value for _i, value in _Skills.EXECUTED]
        self.assertEqual(executed, ["brave", ""])
        self.assertNotIn("firefox", executed)
        self.assertIn("TIME", response)

    def test_a_stuck_model_is_stopped_not_obeyed(self):
        router = _agent_router(plan=json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
        ]}))
        router.process("keep opening brave")
        # parse_plan rejects the duplicate outright, so nothing runs.
        self.assertEqual(_Skills.EXECUTED, [])
        self.assertEqual(router.ai.plain_questions,
                         ["keep opening brave"])

    def test_the_response_never_claims_an_unrun_step_succeeded(self):
        router = _agent_router(plan=json.dumps({"steps": [
            {"skill": "OPEN_APP", "arguments": {"app": "brave"}},
            {"skill": "NOT_A_SKILL", "arguments": {}},
        ]}))
        response = router.process("set a reminder and open brave")
        # One bad step discards the plan, so the model cannot be credited
        # with the half it would have liked.
        self.assertEqual(_Skills.EXECUTED, [])
        self.assertEqual(response, "AI said.")


if __name__ == "__main__":
    unittest.main()
