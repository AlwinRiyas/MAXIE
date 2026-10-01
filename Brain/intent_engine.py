import re


# Words that name a smart-home device. Kept here, next to the patterns
# that use them, so a new device type is one edit.
HOME_DEVICE_WORDS = (
    "light", "lights", "lamp", "lamps", "fan", "fans", "plug", "plugs",
    "thermostat", "radiator", "blind", "blinds", "curtain", "curtains",
    "speaker", "television", "tv", "lock", "door",
)

HOME_ON_WORDS = ("turn on", "switch on", "put on", "light up")
HOME_OFF_WORDS = ("turn off", "switch off", "put out", "kill the lights")
HOME_TOGGLE_WORDS = ("toggle", "flip")
HOME_STATUS_WORDS = ("is the", "what state", "status of", "are the")
HOME_UNLOCK_WORDS = ("unlock", "open the door", "open the front door")
HOME_LEVEL_RE = re.compile(r"(\d{1,3})\s*(?:%|percent)?")


def _home_intent(text, tokens):
    """Classify a smart-home request, or None.

    Ordered so a lock wins over a light in the same sentence ("turn off the
    porch light and unlock the front door"), and so a destructive word is
    never mistaken for a switch.
    """
    if not any(word in text for word in HOME_DEVICE_WORDS):
        return None

    if any(phrase in text for phrase in HOME_UNLOCK_WORDS):
        return "HOME_UNLOCK"

    if any(phrase in text for phrase in HOME_STATUS_WORDS):
        return "HOME_CONTROL"

    if "dim" in text or "brightness" in text:
        return "HOME_CONTROL"

    if any(word in tokens for word in ("lock", "unlock")):
        return "HOME_UNLOCK"
    return "HOME_CONTROL"


class IntentEngine:
    """Classify routing intent for a normalized command string."""

    def classify(self, text):
        text = text.lower().replace(",", " ").replace("?", " ").strip()
        tokens = re.findall(r"[\w']+", text)

        # --------------------------------------------------
        # Home automation (Phase 13)
        # --------------------------------------------------
        # Ahead of the app verbs on purpose: "open the front door" starts
        # with "open", and a door is not an application. _home_intent
        # returns None unless a device word is present, so "open brave"
        # still falls through to OPEN_APP.
        home = _home_intent(text, tokens)
        if home:
            return home

        # --------------------------------------------------
        # Open / close applications
        # --------------------------------------------------
        if text.startswith("open ") and "youtube" in text and any(
                phrase in text for phrase in ("search", "play", "watch",
                                              "find", "and")):
            return "YOUTUBE_SEARCH"

        if any(text.startswith(p) for p in ("open ", "launch ", "start ", "run ")):
            return "OPEN_APP"

        if text in {"open", "launch", "start", "run"}:
            # Phase 8.7: a bare verb still routes to the skill so the router
            # can ask for the missing argument instead of dropping to the AI.
            return "OPEN_APP"

        if any(text.startswith(p) for p in ("close ", "quit ", "kill ", "exit app ")):
            return "CLOSE_APP"

        if text in {"close", "kill"}:
            return "CLOSE_APP"

        # --------------------------------------------------
        # Core queries
        # --------------------------------------------------
        if "time" in tokens:  # token match: "12 times 8" has no "time" token
            return "TIME"
        if any(word in text for word in ("weather", "temperature", "forecast")):
            return "WEATHER"
        if any(word in tokens for word in ("date", "day", "today")):
            return "DATE"

        # --------------------------------------------------
        # System
        # --------------------------------------------------
        if any(phrase in text for phrase in (
            "system info", "system information", "battery",
            "cpu usage", "ram usage", "how much ram", "how is my pc",
            "system status",
        )):
            return "SYSTEM_INFO"

        if "volume" in text or "mute" in text or "unmute" in text:
            return "VOLUME"

        if any(phrase in text for phrase in (
            "shutdown the pc", "shut down the pc", "shutdown pc",
            "shutdown computer", "turn off the pc", "turn off pc",
            "shut down the laptop", "shutdown laptop", "turn off laptop",
            # Phrasing a person actually says. Without these, "shut down the
            # computer" fell through to the LLM instead of the power skill.
            "shut down the computer", "shutting down the computer",
            "shut down computer", "shut it down", "shut the computer down",
            "power off", "power the pc off", "power off the computer",
            "turn off the computer", "turn the computer off",
        )):
            return "SHUTDOWN"

        if any(phrase in text for phrase in (
            "restart the pc", "restart pc", "restart computer", "reboot",
            "restart the laptop", "restart laptop",
            "restart the computer", "restart my computer", "reboot the pc",
            "reboot computer", "reboot the computer",
        )):
            return "RESTART"

        if text in {"screenshot", "take a screenshot", "capture screen"}:
            return "SCREENSHOT"

        # --------------------------------------------------
        # To-do list
        # --------------------------------------------------
        todo_markers = ("todo", "to do", "to-do", "task", "my list")
        if any(m in text for m in todo_markers):
            if any(word in text for word in ("clear", "empty")):
                return "TODO_CLEAR"
            if any(word in text for word in ("add", "put", "remind",
                                             "write", "note")):
                return "TODO_ADD"
            if any(word in text for word in ("done", "complete", "finish",
                                             "finished", "completed")):
                return "TODO_DONE"
            if any(word in text for word in ("remove", "delete", "drop")):
                return "TODO_REMOVE"
            if any(word in text for word in ("show", "what", "list",
                                             "display", "view")):
                return "TODO_LIST"
        if "remind me to" in text:
            return "TODO_ADD"
        if "done" in text and any(word in text for word in ("mark", "marked")):
            return "TODO_DONE"

        # --------------------------------------------------
        # Media control
        # --------------------------------------------------
        if any(word in text for word in ("next", "previous", "prev", "skip",
                                         "change", "switch")) and any(
                word in text for word in (
                    "song", "track", "music", "playback", "playlist")):
            if any(word in text for word in ("previous", "prev",
                                             "go back", "last")):
                return "MEDIA_PREVIOUS"
            return "MEDIA_NEXT"
        if "go back a song" in text or "go back to the previous song" in text:
            return "MEDIA_PREVIOUS"
        if text in {"pause", "pause music", "pause the music", "resume",
                    "resume music", "play music", "play some music",
                    "play a song", "play my music", "play my songs",
                    "unpause", "stop the music", "stop music"} or any(
                phrase in text for phrase in ("toggle music", "play pause")):
            return "MEDIA_PLAY_PAUSE"

        # --------------------------------------------------
        # Calls (answer / reject)
        # --------------------------------------------------
        if any(word in text for word in ("answer", "attend", "accept",
                                         "pick up", "pickup", "receive")):
            if any(word in text for word in ("call", "phone", "ring", "line")):
                return "CALL_ANSWER"
        if any(word in text for word in ("reject", "decline", "ignore",
                                         "hang up", "end", "deny")):
            if any(word in text for word in ("call", "phone", "ring", "line")):
                return "CALL_REJECT"

        # --------------------------------------------------
        # Recommendations
        # --------------------------------------------------
        if any(word in text for word in ("recommend", "suggest",
                                         "suggestion")):
            return "RECOMMEND"
        if text in {"give me a match", "give me a recommendation",
                    "recommend me something"}:
            return "RECOMMEND"
        if any(phrase in text for phrase in ("what should i watch",
                                             "what should i listen to",
                                             "what should i play")):
            return "RECOMMEND"

        # --------------------------------------------------
        # Memory
        # --------------------------------------------------
        if any(word in text for word in ("remember", "memorize")):
            return "SAVE_MEMORY"

        memory_retrieval = (
            "what did i",
            "what do i",
            "what am i",
            "what is my",
            "what are my",
            "what did you save",
            "what did i tell you",
            "do you remember",
            "what do you know about me",
            "what did we",
            "recall",
        )
        if any(phrase in text for phrase in memory_retrieval):
            return "RECALL_MEMORY"

        if any(word in text for word in ("forget", "delete my memory",
                                         "remove memory")):
            return "DELETE_MEMORY"

        # Less-formal bulks ("delete all memories", "erase my history")
        # must still route to the memory skill so the security gate can
        # intercept the wipe (SEC-08) instead of the AI answering.
        if any(word in text for word in (
                "delete all", "wipe", "erase my", "erase all",
                "clear my memory", "forget everything")):
            return "DELETE_MEMORY"

        # --------------------------------------------------
        # Math
        # --------------------------------------------------
        if any(phrase in text for phrase in (
            "calculate", "what is", "what's", "whats",
            "plus", "minus", "multiplied by", "divided by",
            "times", "percent of", "to the power of",
            "squared", "cubed", "square root", "sqrt",
        )) and any(op in text for op in ("+", "-", "*", "/", "times", "plus",
                                         "minus", "multiply", "divide",
                                         "percent", "percent of",
                                         "root", "sqrt", "squared", "cubed",
                                         "power")):
            return "CALCULATE"

        # --------------------------------------------------
        # Web / search / youtube
        # --------------------------------------------------
        if "youtube" in text and any(phrase in text for phrase in (
                "search", "find", "play ", "watch", "and search")):
            return "YOUTUBE_SEARCH"

        if any(text.startswith(p) for p in ("search for ", "search ",
                                            "look up ", "google ")):
            return "SEARCH"

        if text in {"search", "look up", "google"}:
            return "SEARCH"

        if text.startswith("play ") and not self._is_game_name(text):
            return "YOUTUBE_SEARCH"

        # --------------------------------------------------
        # Greeting / help / misc
        # --------------------------------------------------
        if "hello maxie" in text or text in {
            "hello", "hey maxie", "hi maxie", "hey", "hi", "good morning",
            "good afternoon", "good evening", "wake up",
        }:
            return "GREETING"

        if text in {"help", "what can you do", "what can you do maxie",
                    "help maxie", "commands", "show commands"}:
            return "HELP"

        if "who are you" in text or "what are you" in text:
            return "AI_CHAT"

        if any(word in text for word in ("stop", "quit", "exit", "goodbye",
                                         "good bye", "shut up", "be quiet",
                                         "enough", "cancel")):
            if text in {"stop", "quit", "exit", "bye", "goodbye", "good bye",
                        "stop stop", "exit exit", "quit quit"}:
                return "EXIT_OR_STOP"
            return "UNKNOWN"

        return "UNKNOWN"

    # ----------------------------------------------------------
    # Heuristic: is a "play <name>" command a game-like request?
    # Kept simple: game/app keywords remain UNKNOWN so the AI can
    # answer; music/video phrases route to YouTube.
    # ----------------------------------------------------------

    @staticmethod
    def _is_game_name(text):
        return any(word in text for word in (
            "minecraft", "fortnite", "cod", "valorant", "gta", "fifa",
            "chess", "cricket", "football", "candycrush", "skyrim",
            "elden ring", "zelda", "pubg",
        ))