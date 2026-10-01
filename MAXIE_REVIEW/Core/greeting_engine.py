from datetime import datetime

from Config.config import Config


class GreetingEngine:
    """FRIDAY/Jarvis-style greetings for time of day."""

    def get_greeting(self):
        hour = datetime.now().hour
        name = Config.USER_NAME

        if 5 <= hour < 12:
            return (
                f"Good morning, {name}. All systems are running smoothly. "
                "What can I do for you?"
            )
        if 12 <= hour < 17:
            return (
                f"Good afternoon, {name}. Everything is ready whenever "
                "you are."
            )
        if 17 <= hour < 22:
            return (
                f"Good evening, {name}. At your service as always."
            )
        return (
            f"You're up late, {name}. Even a smart assistant would suggest "
            "you take a break."
        )
