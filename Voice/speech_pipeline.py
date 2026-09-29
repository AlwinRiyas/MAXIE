from Voice.audio_manager import AudioManager
from Voice.audio_recorder import AudioRecorder
from Voice.transcriber import Transcriber


class SpeechPipeline:
    """Audio capture -> transcription."""

    def __init__(self):
        self.recorder = AudioRecorder()
        self.transcriber = Transcriber()
        self.audio_manager = self.recorder.audio_manager

    @staticmethod
    def is_available():
        return AudioManager.is_available()

    def recognize(self, filename=None):
        filename = filename or "voice.wav"

        captured = self.recorder.record(filename=filename)
        if not captured:
            return ""

        text = self.transcriber.transcribe(captured)
        return text if text else ""