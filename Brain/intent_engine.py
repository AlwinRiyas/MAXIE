class IntentEngine:

    def classify(self, text):

        text = text.lower().strip()

        if any(word in text for word in ["open", "launch", "start"]):
            return "OPEN_APP"

        if any(word in text for word in ["remember", "save"]):
            return "SAVE_MEMORY"

        if any(word in text for word in ["what is", "who is", "explain"]):
            return "AI_CHAT"

        if any(word in text for word in ["time"]):
            return "TIME"

        if any(word in text for word in ["date"]):
            return "DATE"

        if any(word in text for word in ["weather"]):
            return "WEATHER"

        return "UNKNOWN"