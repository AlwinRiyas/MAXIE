from Voice.audio_manager import AudioManager
from Voice.microphone import Microphone
from Voice.voice_activity import VoiceActivity
from Voice.wake_word_engine import WakeWordEngine
from Voice.speech_engine import SpeechEngine


class VoiceManager:

    def __init__(self):

        self.audio = AudioManager()
        self.microphone = Microphone()
        self.activity = VoiceActivity()
        self.wake_word = WakeWordEngine()
        self.speech = SpeechEngine()

    def initialize(self):

        print("Initializing Voice Manager...")

        if self.microphone.status():
            print("✅ Microphone Connected")
        else:
            print("❌ Microphone Not Found")

    def listen(self):

        return self.speech.recognize()