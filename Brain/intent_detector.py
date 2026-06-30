class IntentDetector:

    def detect(self, command):

        if command.startswith("open "):
            return "OPEN_APP"

        elif command.startswith("search "):
            return "SEARCH"

        elif command.startswith("shutdown"):
            return "SHUTDOWN"

        elif command.startswith("restart"):
            return "RESTART"

        return "UNKNOWN"