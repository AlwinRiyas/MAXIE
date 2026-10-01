from Security.permissions import Permissions
from Skills.skill_schema import SKILL_SCHEMAS, SchemaError


class SkillManager:
    """Registry of skills. Only actions in Permissions.ALLOWED can run;
    destructive ones return a confirmation requirement instead.

    Class name kept ('SkillManager') and 'execute(intent, value)'
    interface preserved for backward compatibility.
    """

    def __init__(self):
        self.open_app = None
        self.close_app = None
        self.calculator = None
        self.weather = None
        self.web_search = None
        self.volume = None
        self.system = None
        self.memory = None
        self.todo = None
        self.media = None
        self.phone = None
        self.power = None
        self.youtube = None
        self.recommend = None

    # Lazy constructors keep startup light.
    def _skill(self, name, module, class_name):
        attr = getattr(self, name)
        if attr is None:
            module = __import__(module, fromlist=[class_name])
            setattr(self, name, getattr(module, class_name)())
        return getattr(self, name)

    # ----------------------------------------------------------
    # Argument contracts (ROADMAP 12.7)
    # ----------------------------------------------------------

    @staticmethod
    def schema_for(intent):
        """The declarative argument contract for ``intent``, or None."""
        return SKILL_SCHEMAS.get(intent)

    @staticmethod
    def tool_schemas():
        """Tool definitions the model is allowed to see.

        Two filters, both deliberate:

        - only allowlisted intents, so offering a tool can never widen
          what MAXIE is permitted to do;
        - no destructive intents. The router would refuse them anyway,
          so advertising SHUTDOWN to a model only invites it to try, and
          spends tokens. The refusal path stays as defence in depth,
          because a model can still emit a tool it was never offered.
        """
        return [
            schema.to_ollama_tool()
            for intent, schema in SKILL_SCHEMAS.items()
            if Permissions.can_execute(intent)
            and not Permissions.requires_confirmation(intent)
        ]

    # Skills that can describe what they changed, so an agent run has
    # something to roll back (ROADMAP 12.9). Keyed by intent, because the
    # capability belongs to the skill and the intent is how it is reached.
    STRUCTURED = {
        "HOME_CONTROL": ("home_control",
                         "Skills.home_control_skill", "HomeControlSkill"),
    }

    def execute_args(self, intent, arguments):
        """Validate named arguments against the intent's schema, then
        dispatch the primary one as the skill's usual string value.

        Returns the skill's response, or a caller-facing refusal when the
        arguments do not satisfy the contract. Validation happens before
        the allowlist check is even needed, and never after dispatch, so a
        malformed call cannot half-run.
        """
        if not Permissions.can_execute(intent):
            return Permissions.confirmation_for(intent) or (
                f"I'm not allowed to do that ({intent}).")

        schema = self.schema_for(intent)
        if schema is None:
            return "I don't know how to do that yet."

        try:
            value = schema.primary_value(arguments)
        except SchemaError as error:
            self._logger().warning(f"Skill schema rejected: {error}")
            return f"I need to be clearer about that: {error}"

        structured = self.execute_structured(intent, arguments)
        if structured is not None:
            return structured

        return self.execute(intent, value)

    def execute_structured(self, intent, arguments):
        """Dispatch to a skill that reports a `SkillResult`, or None.

        None means "this intent has no structured skill", and the caller
        falls back to the ordinary string path. A structured skill is
        passed the *named* arguments, because that is the only way it can
        both act and say what it changed.
        """
        entry = self.STRUCTURED.get(intent)
        if entry is None:
            return None
        name, module, class_name = entry
        skill = self._skill(name, module, class_name)
        method = getattr(skill, "execute_result", None)
        if method is None:
            return None
        return method(**dict(arguments or {}))

    @staticmethod
    def _logger():
        from Logs.logger import Logger

        return Logger.instance()

    def execute(self, intent, value="", extra=None):
        if not Permissions.can_execute(intent):
            confirmation = Permissions.confirmation_for(intent)
            return confirmation or (
                f"I'm not allowed to do that ({intent})."
            )

        # ---------------- Core queries ----------------
        if intent == "TIME":
            return self._time(value)
        if intent == "DATE":
            return self._date(value)

        # ---------------- Apps ----------------
        if intent == "OPEN_APP":
            skill = self._skill(
                "open_app", "Skills.open_app_skill", "OpenAppSkill"
            )
            return skill.execute(value or extra or "")

        if intent == "CLOSE_APP":
            skill = self._skill(
                "close_app", "Skills.close_app_skill", "CloseAppSkill"
            )
            return skill.execute(value or extra or "")

        # ---------------- Math ----------------
        if intent == "CALCULATE":
            skill = self._skill(
                "calculator", "Skills.calculator", "CalculatorSkill"
            )
            expr = (extra or value or "").strip()
            if not expr:
                expr = "2 + 2"
            return skill.execute(expr)

        # ---------------- Web ----------------
        if intent == "SEARCH":
            skill = self._skill(
                "web_search", "Skills.web_search", "WebSearchSkill"
            )
            return skill.execute(value or extra or "")

        # ---------------- Weather ----------------
        if intent == "WEATHER":
            skill = self._skill(
                "weather", "Weather.weather_engine", "WeatherEngine"
            )
            return skill.get_weather()

        # ---------------- System ----------------
        if intent == "SYSTEM_INFO":
            skill = self._skill(
                "system", "Skills.system_skill", "SystemSkill"
            )
            return skill.system_info()
        if intent == "SCREENSHOT":
            skill = self._skill(
                "system", "Skills.system_skill", "SystemSkill"
            )
            return skill.screenshot()

        if intent == "VOLUME":
            skill = self._skill(
                "volume", "Skills.volume_skill", "VolumeSkill"
            )
            return skill.execute(value or extra or "")

        # ---------------- Memory ----------------
        if intent == "SAVE_MEMORY":
            skill = self._skill(
                "memory", "Skills.memory_skill", "MemorySkill"
            )
            return skill.save_sentence(value or extra or "")

        if intent == "RECALL_MEMORY":
            skill = self._skill(
                "memory", "Skills.memory_skill", "MemorySkill"
            )
            return skill.recall(value or extra or "")

        if intent == "DELETE_MEMORY":
            skill = self._skill(
                "memory", "Skills.memory_skill", "MemorySkill"
            )
            return skill.delete(value or extra or "")

        # ---------------- To-do list ----------------
        if intent == "TODO_ADD":
            skill = self._skill("todo", "Skills.todo_skill", "TodoListSkill")
            return skill.add(value or extra or "")
        if intent == "TODO_LIST":
            skill = self._skill("todo", "Skills.todo_skill", "TodoListSkill")
            return skill.show(value or extra or "")
        if intent == "TODO_DONE":
            skill = self._skill("todo", "Skills.todo_skill", "TodoListSkill")
            return skill.done(value or extra or "")
        if intent == "TODO_REMOVE":
            skill = self._skill("todo", "Skills.todo_skill", "TodoListSkill")
            return skill.remove(value or extra or "")
        if intent == "TODO_CLEAR":
            skill = self._skill("todo", "Skills.todo_skill", "TodoListSkill")
            return skill.clear(value or extra or "")

        # ---------------- Media control ----------------
        if intent in ("MEDIA_NEXT", "MEDIA_PREVIOUS", "MEDIA_PLAY_PAUSE"):
            skill = self._skill(
                "media", "Skills.media_controller", "MediaSkill"
            )
            return skill.execute(value or extra or "")

        # ---------------- Calls ----------------
        if intent == "CALL_ANSWER":
            skill = self._skill(
                "phone", "Skills.phone_controller", "PhoneController"
            )
            return skill.answer(value or extra or "")
        if intent == "CALL_REJECT":
            skill = self._skill(
                "phone", "Skills.phone_controller", "PhoneController"
            )
            return skill.reject(value or extra or "")

        # ---------------- Power (post-confirmation) ----------------
        if intent == "SHUTDOWN":
            skill = self._skill("power", "Skills.power_skill", "PowerSkill")
            return skill.shutdown(value or extra or "")
        if intent == "RESTART":
            skill = self._skill("power", "Skills.power_skill", "PowerSkill")
            return skill.restart(value or extra or "")

        # ---------------- YouTube / recommendations ----------------
        if intent == "YOUTUBE_SEARCH":
            skill = self._skill(
                "youtube", "Skills.youtube_skill", "YouTubeSkill"
            )
            return skill.search(value or extra or "")
        if intent in ("HOME_CONTROL", "HOME_UNLOCK"):
            # Phase 13: no backend is required. When none is configured the
            # skill says so; it never invents a device.
            skill = self._skill(
                "home_control", "Skills.home_control_skill", "HomeControlSkill"
            )
            # `extra` is a dict from the router (action + optional level) or
            # a bare action string from a simpler caller.
            if isinstance(extra, dict):
                home_action = str(extra.get("action", "on"))
                home_level = extra.get("level")
            else:
                home_action = str(extra) if extra else "on"
                home_level = None
            if home_action in ("status", "list"):
                return skill.status(value or "")
            return skill.execute(value or "", home_action, home_level,
                                 intent=intent)
        if intent == "RECOMMEND":
            skill = self._skill(
                "recommend", "Skills.recommendation_skill",
                "RecommendationSkill",
            )
            return skill.recommend(value or extra or "")

        # ---------------- Default ----------------
        return "I don't know how to do that yet."

    # ----------------------------------------------------------
    # Time / date (Core engines)
    # ----------------------------------------------------------

    def _time(self, value=""):
        from Core.time_engine import TimeEngine

        return TimeEngine().get_time_response()

    def _date(self, value=""):
        from Core.date_engine import DateEngine

        return DateEngine().get_date_response()