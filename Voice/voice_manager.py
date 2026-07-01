from Voice.audio_manager import AudioManager
from Voice.speech_engine import SpeechEngine
from Voice.voice_state import VoiceState


class VoiceManager:

    def __init__(self):

        self.audio = AudioManager()

        self.speech = SpeechEngine()

        self.state = VoiceState.WAITING

    def set_state(self, state):

        self.state = state

    def get_state(self):

        return self.state

    def listen(self):

        self.state = VoiceState.LISTENING

        text = self.speech.recognize()

        self.state = VoiceState.PROCESSING

        return text

    def speaking(self):

        self.state = VoiceState.SPEAKING

    def waiting(self):

        self.state = VoiceState.WAITING