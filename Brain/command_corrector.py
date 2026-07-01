from difflib import get_close_matches


class CommandCorrector:

    def correct(self, text):

        words = text.lower().split()

        known = [
            "calculator",
            "notepad",
            "paint",
            "android",
            "studio",
            "brave",
            "chrome",
            "spotify",
            "steam",
            "discord",
            "youtube"
        ]

        corrected = []

        for word in words:

            match = get_close_matches(word, known, n=1, cutoff=0.75)

            if match:
                corrected.append(match[0])
            else:
                corrected.append(word)

        return " ".join(corrected)