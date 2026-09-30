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

# Phase 8.7: skills that require a non-empty argument. When the user
# omits it ("open", "search", "set volume to" with nothing after), the
# router asks for clarification instead of executing with an empty value
# (which would silently do the wrong thing).
ARG_REQUIRED = {
    "OPEN_APP": "Which app should I open?",
    "CLOSE_APP": "Which app should I close?",
    "SEARCH": "What would you like me to search for?",
    "YOUTUBE_SEARCH": "What should I search on YouTube?",
    "TODO_ADD": "What should I add to your to-do list?",
    "VOLUME": "What volume level should I set?",
}


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
        from Config.config import Config

        self._auto_learn_session_cap = int(
            Config.ai_config().get("auto_learn_session_cap", 30))
        self._auto_learn_counts = 0

    # ==================================================
    # PUBLIC: process text -> response string
    # ==================================================

    def process(self, text):
        if not text or not text.strip():
            return "I didn't catch that."

        corrected = self.corrector.correct(text)

        # Phase 8.4: multi-intent. "open chrome and stop the music" is two
        # independent skill actions. Safe only when *every* clause classifies
        # to a deterministic, non-destructive skill intent; anything else
        # (AI chat, memory, shared-argument math) falls through to the
        # single-intent path below.
        clauses = self._split_and(corrected)
        if clauses:
            return self._execute_clauses(clauses)

        intent = self.intent.classify(corrected)

        self.logger.info(f"Router: '{text}' -> intent={intent}")

        # ------------------------------------------------------------
        # Continuous learning: MAXIE quietly records preference phrases
        # ("I like X", "my favorite Y") even when the user never says
        # "remember". Never changes the reply; facts persist to SQLite
        # and survive reboots.
        # ------------------------------------------------------------
        if intent not in ("SAVE_MEMORY", "DELETE_MEMORY", "TODO_ADD"):
            self._auto_learn(corrected or text, raw=text)

        self.memory.add_context("user", corrected or text)

        value = self._extract(corrected, intent)

        # ---------------- Confirmation-gated destructive actions ----------------
        from Security.permissions import Permissions

        if Permissions.requires_confirmation(intent) and intent != "DELETE_MEMORY":
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
            # Phase 8.7: argument schema validation. "open", "search",
            # "set volume to" carry no argument; ask instead of executing
            # a skill with an empty value.
            if intent in ARG_REQUIRED and not self._has_argument(value, intent):
                self.logger.info(f"Router: missing argument for {intent}")
                return ARG_REQUIRED[intent]
            return self.command.execute(intent, value, corrected)

        # ---------------- Memory ----------------
        if intent == "SAVE_MEMORY":
            return self.command.execute("SAVE_MEMORY", corrected)

        if intent == "RECALL_MEMORY":
            return self.command.execute("RECALL_MEMORY", corrected)

        if intent == "DELETE_MEMORY":
            from Security.permissions import Permissions

            if any(word in corrected for word in Permissions.BULK_DELETE_WORDS):
                # SEC-08: wiping everything needs explicit confirmation
                # and an audit log line; ordinary delete stays unguarded.
                confirm_words = ("confirm", "yes", "yeah", "do it", "go ahead",
                                 "sure", "ok")
                if any(word in corrected for word in confirm_words
                       ) and "not" not in corrected:
                    self.logger.warning(
                        f"SEC-08: bulk memory wipe confirmed and executed: "
                        f"{corrected}")
                    return self.command.execute("DELETE_MEMORY", "all")
                return (Permissions.confirmation_for("DELETE_MEMORY_BULK")
                        or "I won't wipe all memories without confirmation.")
            return self.command.execute("DELETE_MEMORY", value)

        # ---------------- Greeting ----------------
        if intent == "GREETING":
            from Core.greeting_engine import GreetingEngine

            return GreetingEngine().get_greeting()

        if intent == "HELP":
            return self._help_text()

        # ---------------- Clarification (Phase 8.3) ----------------
        # A phrase that opens with a skill verb but still classifies as
        # UNKNOWN is asking for an action MAXIE cannot yet identify
        # ("play the flute album", "open the thing on my desk"). Ask
        # instead of silently handing it to the AI, which cannot act.
        clarification = self._clarify(corrected)
        if clarification:
            return clarification

        # ---------------- Conversational AI ----------------
        answer = self.ai.ask(corrected)
        return answer

    # ==================================================
    # MULTI-INTENT (Phase 8.4)
    # ==================================================

    _MULTI_INTENT_OK = frozenset({
        "OPEN_APP", "CLOSE_APP", "SEARCH", "VOLUME", "TIME", "DATE",
        "WEATHER", "SYSTEM_INFO", "SCREENSHOT", "YOUTUBE_SEARCH",
        "MEDIA_NEXT", "MEDIA_PREVIOUS", "MEDIA_PLAY_PAUSE",
        "CALL_ANSWER", "CALL_REJECT", "RECOMMEND", "CALCULATE",
        "TODO_LIST", "TODO_REMOVE",
    })

    def _split_and(self, corrected):
        """Split 'clause1 and clause2' / 'clause1, clause2' into clauses.

        Phase 8.4. Only splits when *every* clause is independently a
        safe, deterministic skill intent with a real argument. Otherwise
        returns an empty list so process() falls through to the normal
        single-intent path ("search for dogs and cats" stays one SEARCH;
        "open chrome and tell me a joke" stays one OPEN_APP).
        """
        text = corrected.strip()
        candidates = [part.strip() for part in text.split(" and ")]
        if len(candidates) == 1:
            candidates = [part.strip() for part in text.split(", ")]
        candidates = [c for c in candidates if c]
        if len(candidates) < 2:
            return []

        for clause in candidates:
            intent = self.intent.classify(clause)
            if intent not in self._MULTI_INTENT_OK:
                return []
            if intent in ARG_REQUIRED and not self._has_argument(
                    self._extract(clause, intent), intent):
                return []
        return candidates

    def _execute_clauses(self, clauses):
        """Execute a multi-intent command clause-by-clause.

        Returns the joined response when *every* clause resolves to a
        distinct safe skill intent with a real argument; otherwise None
        so process() falls through to the single-intent path (which the
        AI can answer correctly).
        """
        if len(clauses) < 2:
            return None

        responses = []
        for clause in clauses:
            intent = self.intent.classify(clause)
            if intent not in self._MULTI_INTENT_OK:
                return None
            if intent in ARG_REQUIRED and not self._has_argument(
                    self._extract(clause, intent), intent):
                return None
            value = self._extract(clause, intent)
            responses.append(self.command.execute(intent, value, clause))
        return " ".join(str(r) for r in responses)

    # ==================================================
    # CLARIFICATION (Phase 8.3)
    # ==================================================

    _UNKNOWN_VERB_PROMPTS = (
        ("play ", "What would you like me to play?"),
        ("open ", "I'm not sure what that is. Could you name the app?"),
        ("launch ", "I'm not sure what that is. Could you name the app?"),
        ("start ", "I'm not sure what that is. Could you name the app?"),
        ("search ", "What would you like me to search for?"),
        ("look up ", "What would you like me to look up?"),
        ("close ", "I'm not sure what that is. Could you name the app?"),
        ("stop ", "Would you like me to stop talking, or stop an app?"),
    )

    def _clarify(self, corrected):
        to_check = (corrected or "").strip().lower()
        for prefix, prompt in self._UNKNOWN_VERB_PROMPTS:
            if to_check == prefix.strip() or to_check.startswith(prefix):
                self.logger.info(f"Router: clarifying UNKNOWN verb phrase: {corrected}")
                return prompt
        return ""

    # ==================================================
    # CONTINUOUS LEARNING (auto-captured preferences)
    # ==================================================

    def _auto_learn(self, corrected, raw=None):
        """Quietly persist preference sentences. Returns the captured
        fact or None. Used so MAXIE 'keeps learning' even when the user
        hasn't said 'remember'."""
        if raw and self._has_delimited_quotes(raw):
            self.logger.info(
                "SEC-06: auto-learn blocked quoted/ambient text")
            return None

        markers = (
            "i like ", "i love ", "i prefer ", "i hate ",
            "my favorite ", "my favourite ", "my hobby ",
            "i am learning ", "i'm learning ", "i am studying ",
            "i study ", "i'm studying ",
        )
        negations = (
            "don't ", "dont ", "do not ", "doesn't ", "doesnt ",
            "does not ", "didn't ", "didnt ", "did not ", "isn't ",
            "isnt ", "am not ", "can't ", "cant ", "cannot ", "not ",
        )
        first = None
        for marker in markers:
            idx = corrected.find(marker)
            if idx != -1 and (first is None or idx < first):
                first = idx

        if first is None:
            return None

        head = corrected[:first].strip()
        if head and any(negation in " " + head + " " for negation in negations):
            return None

        fact = corrected[first:].strip()
        for stop in (" and ", ",", ".", " but ", " so ", " because "):
            fact = fact.split(stop)[0]
        fact = fact.strip(" .!?")

        if not (3 <= len(fact) <= 60):
            return None

        # Per-session cap so a long ambient conversation cannot flood the
        # memory store (configurable via auto_learn_session_cap).
        if self._auto_learn_counts < self._auto_learn_session_cap:
            try:
                self.memory.remember_sentence("remember that " + fact)
                self._auto_learn_counts += 1
                self.logger.info(f"Auto-learned: {fact}")
                return fact
            except Exception as error:
                self.logger.error(f"Auto-learn failed: {error}")
                return None
        self.logger.info("SEC-06: auto-learn session cap reached; skipping")
        return None

    @staticmethod
    def _has_delimited_quotes(text):
        """SEC-06: True when the original transcript contains a quote
        mark that is *not* an intra-word apostrophe ("it's", "don't").

        Ambient audio that is actually quoted speech — a podcast saying
        ``"I like mining rigs"``, a prompt-injected page read aloud —
        surfaces quotes at word boundaries. Those must never become
        durable preference facts, because they would be re-injected into
        every future system prompt.
        """
        for i, char in enumerate(text or ""):
            if char not in "\"'`":
                continue
            prev = text[i - 1] if i > 0 else " "
            nxt = text[i + 1] if i + 1 < len(text) else " "
            if not (prev.isalnum() and nxt.isalnum()):
                return True
        return False

    # ==================================================
    # ARGUMENT VALIDATION (Phase 8.7)
    # ==================================================

    _DEGENERATE = {"", "an", "a", "the", "it", "that", "this",
                   "this app", "the app", "an app", "a app",
                   "something", "to", "for", "up",
                   "open", "launch", "start", "run",
                   "close", "kill", "quit", "exit app",
                   "search", "look up", "google"}

    _PLACEHOLDER_WORDS = {
    "whatever", "something", "anything", "thing", "the thing",
    "this thing", "that thing", "stuff", "it",
}

    def _has_argument(self, value, intent):
        """True when an argument-required intent has a real value.

        'open', 'open the app', 'search for' carry no usable argument;
        'open chrome' and 'set volume to 40' do. VOLUME additionally
        needs a level, not just any text. Placeholder objects ("open
        whatever", "start the thing") are not real arguments and ask
        again (Phase 8.3).
        """
        if value is None:
            return False
        text = value.strip().lower()
        if text in self._DEGENERATE:
            return False
        if not text:
            return False
        if intent == "VOLUME":
            return any(char.isdigit() for char in text)
        if any(word in text for word in self._PLACEHOLDER_WORDS):
            return False
        return True

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