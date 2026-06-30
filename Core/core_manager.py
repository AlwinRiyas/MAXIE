from Voice.voice_engine import VoiceEngine

from Core.greeting_engine import GreetingEngine
from Core.date_engine import DateEngine
from Core.time_engine import TimeEngine

from Automation.system_info import SystemInfo
from Automation.application_discovery import ApplicationDiscovery

from Weather.weather_engine import WeatherEngine

from Logs.logger import Logger

from Brain.command_engine import CommandEngine

from Conversation.conversation_engine import ConversationEngine


class Maxie:

    def __init__(self):

        # Systems
        self.logger = Logger()
        self.voice = VoiceEngine()
        self.greeting = GreetingEngine()
        self.date = DateEngine()
        self.time = TimeEngine()
        self.system = SystemInfo()
        self.weather = WeatherEngine()

        # Automation
        self.application_discovery = ApplicationDiscovery()

        # Brain
        self.command = CommandEngine()

        # Conversation
        self.conversation = ConversationEngine(self.command)

    def start(self):

        self.logger.info("MAXIE Boot Started")

        message = f"""
{self.greeting.get_greeting()}

Today is {self.date.get_today()}.

The current time is {self.time.get_time()}.

The current weather is {self.weather.get_weather()}.

All systems are operational.

How may I assist you today?
"""

        self.voice.speak(message)

        self.logger.info("MAXIE Started Successfully")

        # -----------------------------
        # APPLICATION DISCOVERY
        # -----------------------------
        applications = self.application_discovery.scan()

        print("\n========== APPLICATIONS ==========\n")

        count = 0

        for app in sorted(applications):

            print(app)

            count += 1

            if count == 20:
                break

        print(f"\nTotal Applications Found: {len(applications)}")

        # -----------------------------
        # SYSTEM INFORMATION
        # -----------------------------
        info = self.system.get_system_info()

        print("\n========== SYSTEM ==========\n")

        for key, value in info.items():

            print(f"{key:<20}: {value}")

        print("\n============================")

        # -----------------------------
        # START CONVERSATION
        # -----------------------------
        self.conversation.start()