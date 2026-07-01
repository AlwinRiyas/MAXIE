from Voice.audio_stream import AudioStream
from Voice.voice_activity import VoiceActivity
from Voice.transcriber import Transcriber


class SpeechPipeline:

    def __init__(self):

        self.stream = AudioStream()
        self.vad = VoiceActivity()
        self.transcriber = Transcriber()

    def recognize(self):

        print("🎤 Waiting for speech...")

        # Temporary until VAD integration
        filename = "voice.wav"

        return self.transcriber.transcribe(filename)