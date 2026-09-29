from AI.ai_engine import AIEngine
from Brain.command_corrector import CommandCorrector
from Brain.command_engine import CommandEngine
from Brain.intent_engine import IntentEngine
from Config.config import Config
from Logs.logger import Logger
from Memory.memory_engine import MemoryEngine

VERBS_OPEN = ("open ", "launch ", "start ", "run ")
VERBS_CLOSE = ("close ", "kill ", "quit ", "exit app ")
VERBS_SEARCH = ("search for ", "search ", "look up ", "google ")
FORGET_PREFIXES = ("forget ", "delete my memory about ", "forget about ")


class BrainRouter:
    """Routing: skills vs memory vs conversational AI.

    Rules:
      - canonical phrases (time/date/weather) -> skills
      - open/close/search/calculate/volume/system -> skills
      - remember/forget -> memory
      - everything else -> local LLM (with context + memory injection)
    """

    def __init__(self, command_engine=None):
        self.command = command_engine if command_engine is not None else CommandEngine()
        self.intent = IntentEngine()
        self.corrector = CommandCorrector()
        self.memory = MemoryEngine()
        self.ai = AIEngine(memory=self.memory)
        self.logger = Logger.instance()

    # ==================================================
    # PUBLIC: process text -> response string
    # ==================================================

    def process(self, text):
        if not text or not text.strip():
            return "I didn't catch that."

        corrected = self.corrector.correct(text)
        intent = self.intent.classify(corrected)

        self.logger.info(f"Router: '{text}' -> intent={intent}")

        # ------------------------------------------------------------
        # Continuous learning: MAXIE quietly records preference phrases
        # ("I like X", "my favorite Y") even when the user never says
        # "remember". Never changes the reply; facts persist to SQLite
        # and survive reboots.
        # ------------------------------------------------------------
        if intent not in ("SAVE_MEMORY", "DELETE_MEMORY", "TODO_ADD"):
            self._auto_learn(corrected or text)

        self.memory.add_context("user", corrected or text)

        value = self._extract(corrected, intent)

        # ---------------- Confirmation-gated destructive actions ----------------
        from Security.permissions import Permissions

        if intent in ("SHUTDOWN", "RESTART"):
            confirm_words = ("confirm", "yes", "yeah", "do it", "go ahead",
                             "sure", "ok")
            if any(word in corrected for word in confirm_words
                   ) and "not" not in corrected:
                return self.command.execute(intent, value, corrected)
            return (Permissions.confirmation_for(intent)
                    or f"I won't {intent.lower()} without your confirmation.")

        # ---------------- Skills ----------------
        direct = {"TIME", "DATE", "WEATHER", "SYSTEM_INFO", "SCREENSHOT"}
        if intent in direct:
            return self.command.execute(intent, value, corrected)

        if intent in ("OPEN_APP", "CLOSE_APP", "SEARCH", "CALCULATE", "VOLUME",
                      "TODO_ADD", "TODO_LIST", "TODO_DONE", "TODO_REMOVE",
                      "TODO_CLEAR", "MEDIA_NEXT", "MEDIA_PREVIOUS",
                      "MEDIA_PLAY_PAUSE", "CALL_ANSWER", "CALL_REJECT",
                      "YOUTUBE_SEARCH", "RECOMMEND"):
            return self.command.execute(intent, value, corrected)

        # ---------------- Memory ----------------
        if intent == "SAVE_MEMORY":
            return self.command.execute("SAVE_MEMORY", corrected)

        if intent == "RECALL_MEMORY":
            return self.command.execute("RECALL_MEMORY", corrected)

        if intent == "DELETE_MEMORY":
            if any(word in corrected for word in ("all", "everything", "memories")):
                return self.command.execute("DELETE_MEMORY", "all")
            return self.command.execute("DELETE_MEMORY", value)

        # ---------------- Greeting ----------------
        if intent == "GREETING":
            from Core.greeting_engine import GreetingEngine

            return GreetingEngine().get_greeting()

        if intent == "HELP":
            return self._help_text()

        # ---------------- Conversational AI ----------------
        answer = self.ai.ask(corrected)
        return answer

    # ==================================================
    # CONTINUOUS LEARNING (auto-captured preferences)
    # ==================================================

    def _auto_learn(self, corrected):
        """Quietly persist preference sentences. Returns the captured
        fact or None. Used so MAXIE 'keeps learning' even when the user
        hasn't said 'remember'."""

        markers = (
            "i like ", "i love ", "i prefer ", "i hate ",
            "my favorite ", "my favourite ", "my hobby ",
            "i am learning ", "i'm learning ", "i am studying ",
            "i study ", "i'm studying ",
        )
        first = None
        for marker in markers:
            idx = corrected.find(marker)
            if idx != -1 and (first is None or idx < first):
                first = idx

        if first is None:
            return None

        fact = corrected[first:].strip()
        for stop in (" and ", ",", ".", " but ", " so ", " because "):
            fact = fact.split(stop)[0]
        fact = fact.strip(" .!?")

        if not (3 <= len(fact) <= 60):
            return None
        try:
            self.memory.remember_sentence("remember that " + fact)
            self.logger.info(f"Auto-learned: {fact}")
            return fact
        except Exception as error:
            self.logger.error(f"Auto-learn failed: {error}")
            return None

    # ==================================================
    # VALUE EXTRACTION
    # ==================================================

    def _extract(self, text, intent):
        if intent == "OPEN_APP":
            for verb in VERBS_OPEN:
                if text.startswith(verb):
                    return text[len(verb):].strip()
            return text.strip()

        if intent == "CLOSE_APP":
            for verb in VERBS_CLOSE:
                if text.startswith(verb):
                    return text[len(verb):].strip()
            return text.strip()

        if intent == "SEARCH":
            for verb in VERBS_SEARCH:
                if text.startswith(verb):
                    return text[len(verb):].strip()
            return text.strip()

        if intent == "YOUTUBE_SEARCH":
            query = text.strip()
            for prefix in ("open youtube and search ", "open youtube and play ",
                           "search for ", "search ", "play ", "watch ",
                           "find ", "youtube search "):
                if query.startswith(prefix):
                    query = query[len(prefix):].strip()
                    break
            for marker in (" on youtube", " on yt", " in youtube"):
                query = query.replace(marker, " ").strip()
            return query.strip()

        if intent == "DELETE_MEMORY":
            for prefix in FORGET_PREFIXES:
                if text.startswith(prefix):
                    return text[len(prefix):].strip()
            for phrase in ("delete my memory", "clear my memory"):
                if text.startswith(phrase):
                    return "all"
            return text.strip()

        return text.strip()

    # ==================================================
    # HELP
    # ==================================================

    def _help_text(self):
        name = Config.ASSISTANT_NAME
        return (
            f"I'm {name}. I can open apps and YouTube searches, play or "
            "skip songs, answer or reject calls, set the volume, manage "
            "your to-do list, recommend movies or music, tell the time or "
            "date, check the weather, do math, search the web, show system "
            "info, take a screenshot, or remember and recall things. "
            "With confirmation I can shut down or restart the computer. "
            "Say 'exit' to quit."
        )