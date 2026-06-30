import pyttsx3
from Config.config import Config


class VoiceEngine:

    def __init__(self):

        self.engine = pyttsx3.init()

        self.engine.setProperty("rate", Config.VOICE_RATE)

        self.engine.setProperty("volume", 1.0)

        voices = self.engine.getProperty("voices")

        for voice in voices:

            print("Voice Found:", voice.name)

            if "zira" in voice.name.lower():

                self.engine.setProperty("voice", voice.id)

                print("Selected Voice:", voice.name)

                break

    def speak(self, text):

        print(f"\nMAXIE:\n{text}\n")

        self.engine.say(text)

        self.engine.runAndWait()