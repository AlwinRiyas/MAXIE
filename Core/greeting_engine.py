from datetime import datetime

from Config.config import Config


class GreetingEngine:

    def get_greeting(self):

        hour = datetime.now().hour

        if 5 <= hour < 12:

            return (
                f"Good morning {Config.USER_NAME}. "
                "I hope you have a productive day ahead."
            )

        elif 12 <= hour < 17:

            return (
                f"Good afternoon {Config.USER_NAME}. "
                "Welcome back."
            )

        elif 17 <= hour < 22:

            return (
                f"Good evening {Config.USER_NAME}. "
                "Everything is ready whenever you are."
            )

        else:

            return (
                f"You're working late {Config.USER_NAME}. "
                "Remember to take breaks."
            )