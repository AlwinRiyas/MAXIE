import re


class IntentEngine:
    """Classify routing intent for a normalized command string."""

    def classify(self, text):
        text = text.lower().replace(",", " ").replace("?", " ").strip()
        tokens = re.findall(r"[\w']+", text)

        # --------------------------------------------------
        # Open / close applications
        # --------------------------------------------------
        if text.startswith("open ") and "youtube" in text and any(
                phrase in text for phrase in ("search", "play", "watch",
                                              "find", "and")):
            return "YOUTUBE_SEARCH"

        if any(text.startswith(p) for p in ("open ", "launch ", "start ", "run ")):
            return "OPEN_APP"

        if any(text.startswith(p) for p in ("close ", "quit ", "kill ", "exit app ")):
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
        )):
            return "SHUTDOWN"

        if any(phrase in text for phrase in (
            "restart the pc", "restart pc", "restart computer", "reboot",
            "restart the laptop", "restart laptop",
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