from Security.permissions import Permissions


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