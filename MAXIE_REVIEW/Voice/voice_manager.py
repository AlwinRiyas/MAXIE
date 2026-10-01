from Voice.audio_manager import AudioManager
from Voice.speech_engine import SpeechEngine
from Voice.voice_state import VoiceState


class VoiceManager:
    """State machine + listen() facade around the speech pipeline."""

    def __init__(self):
        self.audio = AudioManager()
        self.speech = SpeechEngine()
        self.state = VoiceState.WAITING

    @property
    def available(self):
        return self.speech.pipeline.is_available()

    def set_state(self, state):
        self.state = state

    def get_state(self):
        return self.state

    def listen(self):
        if not self.available:
            return ""
        self.state = VoiceState.LISTENING
        text = self.speech.recognize()
        self.state = VoiceState.PROCESSING
        return text

    def speaking(self):
        self.state = VoiceState.SPEAKING

    def waiting(self):
        self.state = VoiceState.WAITING