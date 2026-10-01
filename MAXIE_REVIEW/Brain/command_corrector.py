import re
from difflib import SequenceMatcher


class CommandCorrector:

    APP_ALIASES = {
        "calculator": [
            "calculator",
            "calculater",
            "calculate",
            "calc",
        ],
        "brave": [
            "brave",
            "braille",
            "brave browser",
        ],
        "notepad": [
            "notepad",
            "note pad",
        ],
        "paint": [
            "paint",
            "ms paint",
        ],
        "android studio": [
            "android studio",
            "android studios",
        ],
    }

    def clean(self, text):

        text = text.lower().strip()

        # Keep math symbols (+ - * / % ^ .) and apostrophes so spoken
        # arithmetic like "47 + 53" still reaches the calculator.
        text = re.sub(
            r"[^\w\s+\-*/.%^']",
            " ",
            text
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    def correct(self, text):

        original = self.clean(text)

        # ---------------- EXACT TIME PHRASES ----------------

        time_phrases = {
            "what time is it",
            "whats the time",
            "what's the time",
            "what is the time",
            "tell me the time",
            "current time",
            "this is the time",
            "what time",
        }

        if original in time_phrases:
            return "time"

        # ---------------- EXACT DATE PHRASES ----------------

        date_phrases = {
            "what is the date",
            "what's the date",
            "whats the date",
            "today's date",
            "todays date",
            "current date",
        }

        if original in date_phrases:
            return "date"

        # ---------------- EXACT WEATHER PHRASES ----------------

        weather_phrases = {
            "what is the weather",
            "what's the weather",
            "whats the weather",
            "current weather",
            "weather today",
        }

        if original in weather_phrases:
            return "weather"

        # ---------------- APPLICATIONS ----------------

        for app, aliases in self.APP_ALIASES.items():

            for alias in aliases:

                if original == alias:
                    return f"open {app}"

                if original == f"open {alias}":
                    return f"open {app}"

                if original == f"launch {alias}":
                    return f"open {app}"

                if original == f"start {alias}":
                    return f"open {app}"

        # ---------------- KNOWN WHISPER CORRECTIONS ----------------

        corrections = {
            "until spray done": "open brave",
            "until brave": "open brave",
            "open braille": "open brave",
            "open calculated": "open calculator",
            "open calculater": "open calculator",
            "watch this python": "what is python",
        }

        if original in corrections:
            return corrections[original]

        # IMPORTANT:
        # Do NOT use broad fuzzy matching here.
        # Normal questions must reach the AI.

        return original