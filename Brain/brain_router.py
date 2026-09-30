import re
import time

from AI.ai_engine import AIEngine
from Brain.command_corrector import CommandCorrector
from Brain.command_engine import CommandEngine
from Brain.intent_engine import IntentEngine
from Config.config import Config
from Logs.logger import Logger
from Memory.memory_engine import MemoryEngine

# ROADMAP 12.1: the autonomy levels that exist today. "agent" is absent
# because it needs the Phase 12.2 planner; Config and BrainRouter both
# refuse it rather than pretend.
# "agent" is legal only with ai.agent_enabled (Config refuses the pair), so
# listing it here cannot itself widen autonomy.
ROUTING_MODES = ("controlled", "smart", "agent")

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

        # SEC-11: a destructive action may only be confirmed in a *separate*
        # turn, so one request ("yes shut down") cannot both ask and confirm.
        # State: {"intent", "value", "source", "expires"}.
        self._pending = None
        self._confirm_ttl = float(
            Config.remote_config().get("confirm_ttl_seconds", 60))
        self._confirm_source = None

        # ROADMAP 12.1: "controlled" (default) or "smart". Config rejects
        # anything else, and the router falls back to the safest mode if a
        # hand-edited value slips past, so no spelling of a future mode
        # can quietly switch autonomy on.
        mode = str(Config.ai_config().get("routing_mode", "controlled")).lower()
        self.agent_enabled = bool(
            Config.ai_config().get("agent_enabled", False))
        if mode == "agent" and not self.agent_enabled:
            # Belt and braces: Config.validate already refuses this pair at
            # load time, but a value set in memory by a caller must not be
            # able to skip that check.
            self.logger.warning(
                "routing_mode 'agent' ignored: ai.agent_enabled is not set")
            mode = "controlled"
        self.routing_mode = mode if mode in ROUTING_MODES else "controlled"

        # ROADMAP 12.3/12.5: ceilings for one goal. Both are read from
        # config and bounded there (1-10) so an autonomous turn cannot be
        # turned into an unbounded one by a stray value.
        self.agent_max_iterations = int(
            Config.ai_config().get("agent_max_iterations", 4))
        self.agent_max_steps = int(
            Config.ai_config().get("agent_max_steps", 4))

    def _propose_skill(self, question):
        """Let the model pick a skill, in the order: allowlist -> schema ->
        SEC-11 gate -> dispatch. Returns None when nothing should run, so
        the caller falls back to a prose answer.

        Every branch that is not an execution returns None rather than an
        error string: a rejected or unparsable proposal should read as a
        normal conversational turn, not as a refusal the user never asked
        for.
        """
        from Security.permissions import Permissions

        try:
            tools = self.command.skills.tool_schemas()
            _answer, call = self.ai.ask_with_tools(question, tools)
        except Exception as error:  # noqa: BLE001 - never break the turn
            self.logger.warning(f"Smart-mode proposal failed: {error}")
            return None

        if not call:
            return None

        name, arguments = call
        # 1. Allowlist. A model cannot reach a capability by inventing a
        #    name; only Permissions decides what may run.
        if not Permissions.can_execute(name):
            self.logger.warning(
                f"Smart-mode proposal refused: {name} is not allowlisted")
            return None
        if self.command.skills.schema_for(name) is None:
            self.logger.warning(
                f"Smart-mode proposal refused: {name} has no schema")
            return None

        # 2. Destructive intents keep the human gate, unchanged and
        #    outside the model's reach. The proposal is dropped: asking
        #    for shutdown must never be something a model can do.
        if Permissions.requires_confirmation(name):
            self.logger.warning(
                f"Smart-mode proposal refused: {name} is destructive and "
                "needs the user's own words")
            return None

        # 3. Validate, then dispatch. execute_args refuses malformed
        #    arguments before any skill is constructed.
        self.logger.info(f"Smart-mode dispatch: {name}")
        return self.command.skills.execute_args(name, arguments)

    def _run_plan(self, question):
        """Plan, then execute, under a ceiling (ROADMAP 12.2-12.5).

        The order matters and is the security property: plan (which refuses
        non-allowlisted, destructive and schema-invalid steps) -> execute
        (which re-checks all of it at dispatch time, under an iteration cap
        and loop detection) -> roll back anything a later failure made
        worth undoing.

        Returns None when the model produced no usable plan, so the caller
        falls back to a prose answer rather than a refusal the user never
        asked for.
        """
        from AI.llm_planner import parse_plan, plan_prompt, PLAN_SHAPE
        from Security.permissions import Permissions
        from Skills.agent_executor import AgentExecutor

        tools = self.command.skills.tool_schemas()
        if not tools:
            return None

        def _validate(skill, arguments):
            """The plan-time gate. Mirrors the executor's dispatch-time
            check on purpose: refusing here means the plan never mentions
            a capability the loop must not touch."""
            if not Permissions.can_execute(skill):
                return f"{skill} is not allowlisted"
            if Permissions.requires_confirmation(skill):
                return f"{skill} is destructive"
            schema = self.command.skills.schema_for(skill)
            if schema is None:
                return f"{skill} has no schema"
            try:
                schema.validate(arguments)
            except Exception as error:  # noqa: BLE001
                return str(error)
            return None

        try:
            raw = self.ai.ask_json(plan_prompt(question, tools),
                                   schema_hint=PLAN_SHAPE)
        except Exception as error:  # noqa: BLE001 - never break the turn
            self.logger.warning(f"Agent planning failed: {error}")
            return None

        plan = parse_plan(raw, _validate, max_steps=self.agent_max_steps)
        if not plan:
            self.logger.info("Agent mode: no usable plan")
            return None

        executor = AgentExecutor(self.command.skills, self.logger,
                                 max_iterations=self.agent_max_iterations)
        results = executor.execute(plan)
        summary = self._summarise_run(results)
        if any(not result.ok for result in results):
            rollback = executor.rollback(results)
            if rollback["failures"]:
                self.logger.warning(
                    f"Agent rollback incomplete: {rollback['failures']}")
            if rollback["reverted"]:
                summary += " I undid the earlier steps I could."
        return summary

    def _summarise_run(self, results):
        """Say what happened, in order, without inventing success."""
        said = [result.describe() for result in results
                if result.ok and result.describe()]
        for result in results:
            if not result.ok and result.skill not in (
                    "AGENT_STEP_LIMIT", "AGENT_LOOP", "AGENT_NO_STEPS"):
                said.append(f"{result.skill} didn't work: {result.error}")

        stop = next((result for result in results if not result.ok), None)
        if stop is not None and stop.skill in (
                "AGENT_STEP_LIMIT", "AGENT_LOOP"):
            said.append(f"I stopped there ({stop.error}).")

        if not said:
            return "I didn't manage to do anything."
        # " " join, first letter capitalised: the parts are already
        # sentences the skills wrote.
        text = " ".join(said)
        return text[0].upper() + text[1:] if text else text

    def bind_source(self, source):
        """Identify the caller for confirmation binding (SEC-11).

        The remote server sets this to the client address so one device
        cannot confirm a prompt another device raised. Voice input passes
        ``None``: one human, one assistant, no cross-caller concern.
        """
        self._confirm_source = source or None

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

        self.logger.info(f"Router: '{self.logger.utterance(text)}' -> intent={intent}")

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
            spoken_confirmation = (
                any(word in corrected for word in confirm_words)
                and "not" not in corrected
            )
            return self._gate_destructive(
                intent, value, corrected, spoken_confirmation)

        # A bare confirmation only means something right after a prompt,
        # and only for the caller that raised it (SEC-11).
        if self._pending_is_ours() and self._is_bare_confirmation(corrected):
            return self._consume_pending(f"source={self._confirm_source}")

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
                # SEC-11: that confirmation must be a separate turn.
                return self._gate_bulk_wipe(
                    spoken_confirmation=any(
                        word in corrected for word in self._CONFIRM_WORDS)
                    and "not" not in corrected)
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
        # ROADMAP 12.1/12.7: in "smart" mode the model may *propose* an
        # allowlisted, schema-backed skill. In "controlled" mode (the
        # default) it may only talk. Either way the proposal is validated
        # against the allowlist and the intent's schema, and a
        # destructive intent still has to survive the SEC-11 gate, so the
        # model can never act on its own.
        if self.routing_mode == "agent":
            # 12.2: the model may chain allowlisted, schema-backed skills
            # under a ceiling. The single-step gate in "smart" mode is a
            # strict subset of what this checks, so nothing destructive
            # and nothing unvalidated can run here either.
            ran = self._run_plan(corrected)
            if ran is not None:
                return ran
        elif self.routing_mode == "smart":
            proposed = self._propose_skill(corrected)
            if proposed is not None:
                return proposed

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

    # ==================================================
    # DESTRUCTIVE CONFIRMATION (SEC-11)
    #
    # A destructive action can never be asked for and confirmed in the
    # same utterance: "yes shut down" is refused and re-prompted, and
    # only a bare confirmation ("yes") in a *later* turn executes the
    # action that was held. The pending state expires
    # ``confirm_ttl_seconds`` after the prompt and is bound to the caller
    # that raised it, so a second device cannot confirm for the first.
    # ==================================================

    _CONFIRM_WORDS = ("confirm", "yes", "yeah", "do it", "go ahead",
                      "sure", "ok")

    _BARE_CONFIRMATIONS = {
        "y", "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "ok thanks",
        "confirm", "confirmed", "do it", "go ahead", "go on", "proceed",
        "affirmative", "yes please", "yes do it", "do it please",
    }

    @staticmethod
    def _is_bare_confirmation(text):
        """True only for an utterance that is nothing but a confirmation.

        Strict on purpose: "yes shut down" or "yes but what time is it"
        must not count as a confirmation.
        """
        cleaned = re.sub(r"[^a-z ]+", " ", (text or "").lower())
        cleaned = " ".join(cleaned.split())
        if not cleaned or "not" in cleaned.split():
            return False
        return cleaned in BrainRouter._BARE_CONFIRMATIONS

    def _expire_pending(self):
        if self._pending is not None and time.monotonic() > self._pending["expires"]:
            self._pending = None

    def _pending_is_ours(self):
        """The pending prompt belongs to this caller and has not expired."""
        self._expire_pending()
        if self._pending is None:
            return False
        return self._pending.get("source") in (None, self._confirm_source)

    def _consume_pending(self, audit_label):
        pending, self._pending = self._pending, None
        self.logger.info(
            f"SEC-11: {pending['intent']} confirmed in a separate turn "
            f"by {audit_label}")
        return self.command.execute(
            pending["exec_intent"], pending["exec_value"], pending["text"])

    def _hold_for_confirmation(self, intent, value, text,
                               exec_intent=None, exec_value=None):
        self._pending = {
            "intent": intent,
            "value": value,
            "text": text,
            "source": self._confirm_source,
            "expires": time.monotonic() + self._confirm_ttl,
            # The prompt is labelled by capability, but the skill call can
            # differ (a bulk wipe prompts as DELETE_MEMORY_BULK and executes
            # DELETE_MEMORY with value "all").
            "exec_intent": exec_intent or intent,
            "exec_value": value if exec_value is None else exec_value,
        }
        self.logger.info(
            f"SEC-11: {intent} held; a separate confirmation turn is required")
        from Security.permissions import Permissions

        return (Permissions.confirmation_for(intent)
                or f"I won't {intent.lower()} without your confirmation.")

    def _gate_destructive(self, intent, value, corrected, spoken_confirmation):
        if (spoken_confirmation and self._is_bare_confirmation(corrected)
                and self._pending_is_ours()
                and self._pending["intent"] == intent):
            return self._consume_pending(f"source={self._confirm_source}")
        # Includes the "yes shut down" case: the confirmation word is
        # present, but the action was not prompted for in an earlier turn.
        return self._hold_for_confirmation(intent, value, corrected)

    def _gate_bulk_wipe(self, spoken_confirmation):
        if (spoken_confirmation and self._pending_is_ours()
                and self._pending["intent"] == "DELETE_MEMORY_BULK"):
            self.logger.warning(
                "SEC-08: bulk memory wipe confirmed in a separate turn")
            self._pending = None
            return self.command.execute("DELETE_MEMORY", "all")
        if spoken_confirmation and not self._pending_is_ours():
            self.logger.warning(
                "SEC-11: bulk wipe asked for and confirmed in one turn; "
                "refused and re-prompted")
        return self._hold_for_confirmation(
            "DELETE_MEMORY_BULK", "all",
            "delete all memories",
            exec_intent="DELETE_MEMORY", exec_value="all")

    def _clarify(self, corrected):
        to_check = (corrected or "").strip().lower()
        for prefix, prompt in self._UNKNOWN_VERB_PROMPTS:
            if to_check == prefix.strip() or to_check.startswith(prefix):
                self.logger.info(
                    "Router: clarifying UNKNOWN verb phrase: "
                    f"{self.logger.utterance(corrected)}"
                )
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
                self.logger.info(
                    f"Auto-learned: {self.logger.utterance(fact)}"
                )
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