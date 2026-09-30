import unittest

from Skills.skill_manager import SkillManager
from Skills.skill_schema import SKILL_SCHEMAS, SchemaError, SkillSchema
from Security.permissions import Permissions


class SchemaValidationTest(unittest.TestCase):
    """ROADMAP 12.7: a schema is a narrowing of what a skill accepts,
    checked before dispatch, never a widening."""

    def test_required_argument_must_be_present(self):
        schema = SkillSchema("X", "x", (
            {"name": "app", "type": "string", "required": True},), "app")
        with self.assertRaises(SchemaError) as caught:
            schema.validate({})
        self.assertIn("app is required", str(caught.exception))

    def test_blank_required_argument_is_missing(self):
        schema = SkillSchema("X", "x", (
            {"name": "app", "type": "string", "required": True},), "app")
        for blank in ("", "   ", None):
            with self.assertRaises(SchemaError):
                schema.validate({"app": blank})

    def test_unknown_argument_is_rejected_not_forwarded(self):
        schema = SkillSchema("X", "x", (
            {"name": "app", "type": "string", "required": True},), "app")
        with self.assertRaises(SchemaError) as caught:
            schema.validate({"app": "brave", "shell": "rm -rf /"})
        self.assertIn("unknown argument", str(caught.exception))

    def test_numeric_string_is_coerced(self):
        schema = SkillSchema("VOLUME", "v", (
            {"name": "level", "type": "int"},), "level")
        self.assertEqual(schema.validate({"level": "40"}), {"level": 40})

    def test_uncoercible_number_is_a_hard_error(self):
        schema = SkillSchema("VOLUME", "v", (
            {"name": "level", "type": "int"},), "level")
        with self.assertRaises(SchemaError):
            schema.validate({"level": "loud"})

    def test_oversized_string_is_rejected(self):
        schema = SkillSchema("X", "x", (
            {"name": "text", "type": "string", "max_length": 10},), "text")
        with self.assertRaises(SchemaError):
            schema.validate({"text": "y" * 11})

    def test_whitespace_is_collapsed(self):
        schema = SkillSchema("X", "x", (
            {"name": "text", "type": "string"},), "text")
        self.assertEqual(schema.validate({"text": "  buy   milk "}),
                         {"text": "buy milk"})

    def test_enum_rejects_anything_outside_the_list(self):
        schema = SkillSchema("M", "m", (
            {"name": "action", "type": "enum",
             "values": ["play", "pause"]},), "action")
        self.assertEqual(schema.validate({"action": "play"})["action"], "play")
        with self.assertRaises(SchemaError):
            schema.validate({"action": "explode"})

    def test_bool_words_are_understood(self):
        schema = SkillSchema("X", "x", ({"name": "flag", "type": "bool"},),
                             "flag")
        self.assertIs(schema.validate({"flag": "yes"})["flag"], True)
        self.assertIs(schema.validate({"flag": "off"})["flag"], False)
        with self.assertRaises(SchemaError):
            schema.validate({"flag": "maybe"})

    def test_bounds_are_enforced(self):
        schema = SkillSchema("VOLUME", "v", (
            {"name": "level", "type": "int", "minimum": 0, "maximum": 100},),
            "level")
        with self.assertRaises(SchemaError):
            schema.validate({"level": 400})
        with self.assertRaises(SchemaError):
            schema.validate({"level": -5})

    def test_optional_argument_falls_back_to_its_default(self):
        schema = SkillSchema("X", "x", (
            {"name": "topic", "type": "string", "required": False,
             "default": ""},), "topic")
        self.assertEqual(schema.validate({}), {"topic": ""})

    def test_non_dict_arguments_are_rejected(self):
        schema = SkillSchema("X", "x", ())
        with self.assertRaises(SchemaError):
            schema.validate("open brave")

    def test_primary_value_is_what_a_skill_consumes(self):
        schema = SkillSchema("OPEN_APP", "x", (
            {"name": "app", "type": "string", "required": True},), "app")
        self.assertEqual(schema.primary_value({"app": "brave"}), "brave")

    def test_schema_without_primary_yields_empty_value(self):
        schema = SkillSchema("TIME", "x", ())
        self.assertEqual(schema.primary_value({}), "")

    def test_duplicate_argument_is_a_definition_error(self):
        with self.assertRaises(SchemaError):
            SkillSchema("X", "x", ({"name": "a"}, {"name": "a"}))

    def test_primary_must_be_a_declared_argument(self):
        with self.assertRaises(SchemaError):
            SkillSchema("X", "x", ({"name": "a"},), "b")


class SchemaToolRenderingTest(unittest.TestCase):
    """The model must see the same contract the validator enforces."""

    def test_required_and_optional_are_distinguished(self):
        tool = SKILL_SCHEMAS["OPEN_APP"].to_ollama_tool()
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["function"]["name"], "OPEN_APP")
        self.assertEqual(tool["function"]["parameters"]["required"], ["app"])

    def test_int_renders_as_json_integer(self):
        tool = SKILL_SCHEMAS["VOLUME"].to_ollama_tool()
        level = tool["function"]["parameters"]["properties"]["level"]
        self.assertEqual(level["type"], "integer")

    def test_enum_carries_its_values(self):
        tool = SKILL_SCHEMAS["MEDIA_PLAY_PAUSE"].to_ollama_tool()
        action = tool["function"]["parameters"]["properties"]["action"]
        self.assertIn("enum", action)

    def test_no_required_key_for_argumentless_skill(self):
        tool = SKILL_SCHEMAS["TIME"].to_ollama_tool()
        self.assertEqual(tool["function"]["parameters"]["required"], [])

    def test_every_rendered_tool_is_json_serialisable(self):
        import json

        for tool in SkillManager.tool_schemas():
            json.dumps(tool)


class SchemaCoverageTest(unittest.TestCase):
    """Every allowed, dispatchable intent needs a contract; a schema for a
    non-allowed intent is dead weight that could be offered by mistake."""

    DISPATCHED = {
        "TIME", "DATE", "WEATHER", "OPEN_APP", "CLOSE_APP", "CALCULATE",
        "SEARCH", "VOLUME", "SYSTEM_INFO", "SCREENSHOT", "SAVE_MEMORY",
        "RECALL_MEMORY", "DELETE_MEMORY", "TODO_ADD", "TODO_LIST",
        "TODO_DONE", "TODO_REMOVE", "TODO_CLEAR", "MEDIA_NEXT",
        "MEDIA_PREVIOUS", "MEDIA_PLAY_PAUSE", "CALL_ANSWER", "CALL_REJECT",
        "YOUTUBE_SEARCH", "RECOMMEND", "SHUTDOWN", "RESTART",
    }

    def test_every_dispatchable_intent_has_a_schema(self):
        missing = self.DISPATCHED - set(SKILL_SCHEMAS)
        self.assertEqual(missing, set())

    def test_no_schema_for_a_forbidden_intent(self):
        for intent in SKILL_SCHEMAS:
            self.assertTrue(Permissions.can_execute(intent),
                            f"{intent} is not allowlisted")

    def test_offered_tools_are_allowlisted_only(self):
        for tool in SkillManager.tool_schemas():
            intent = tool["function"]["name"]
            self.assertTrue(Permissions.can_execute(intent), intent)

    def test_destructive_tools_are_never_offered(self):
        """The router refuses destructive calls anyway; not advertising
        them keeps the model from burning a turn trying."""
        offered = {t["function"]["name"] for t in SkillManager.tool_schemas()}
        self.assertEqual(offered & Permissions.DESTRUCTIVE, set())

    def test_offering_destructive_tools_still_finds_them_in_the_registry(self):
        """The refusal path is defence in depth, so the schemas must
        still exist even though they are withheld."""
        for intent in Permissions.DESTRUCTIVE:
            if intent in SKILL_SCHEMAS:
                self.assertIsNotNone(SkillManager.schema_for(intent))


class ArgumentDispatchTest(unittest.TestCase):
    """execute_args validates first, then reuses the existing dispatch."""

    def setUp(self):
        self.skills = SkillManager()

    def test_valid_arguments_reach_the_skill(self):
        captured = {}
        self.skills.calculator = type("Calc", (), {
            "execute": lambda self, expr: captured.setdefault("expr", expr)
            or expr})()
        self.assertEqual(
            self.skills.execute_args("CALCULATE",
                                      {"expression": "2 + 2"}), "2 + 2")
        self.assertEqual(captured["expr"], "2 + 2")

    def test_invalid_arguments_never_reach_the_skill(self):
        self.skills.calculator = type("Calc", (), {
            "execute": lambda self, expr: "SHOULD NOT RUN"})()
        reply = self.skills.execute_args("CALCULATE", {})
        self.assertNotEqual(reply, "SHOULD NOT RUN")
        self.assertIn("expression is required", reply)

    def test_smuggled_argument_is_rejected(self):
        self.skills.calculator = type("Calc", (), {
            "execute": lambda self, expr: "SHOULD NOT RUN"})()
        reply = self.skills.execute_args(
            "CALCULATE", {"expression": "2+2", "shell": "whoami"})
        self.assertIn("unknown argument", reply)

    def test_forbidden_intent_is_refused_before_validation(self):
        reply = self.skills.execute_args("FORMAT", {"disk": "sda"})
        self.assertIn("format", reply.lower())

    def test_intent_without_a_schema_is_refused(self):
        reply = self.skills.execute_args("AI_CHAT", {"text": "hi"})
        self.assertIn("don't know how", reply)

    def test_media_action_enum_is_validated(self):
        seen = []
        self.skills.media = type("Media", (), {
            "execute": lambda self, action: seen.append(action) or "playing"}
        )()
        self.assertEqual(
            self.skills.execute_args("MEDIA_PLAY_PAUSE", {"action": "pause"}),
            "playing")
        self.assertEqual(seen, ["pause"])
        reply = self.skills.execute_args("MEDIA_PLAY_PAUSE",
                                         {"action": "self-destruct"})
        self.assertIn("action must be one of", reply)
        self.assertEqual(len(seen), 1, "a rejected enum must not run the skill")


if __name__ == "__main__":
    unittest.main()
