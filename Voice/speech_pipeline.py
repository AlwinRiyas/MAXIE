from Voice.audio_recorder import AudioRecorder
from Voice.transcriber import Transcriber


class SpeechPipeline:

    def __init__(self):

        self.recorder = AudioRecorder()
        self.transcriber = Transcriber()

    def recognize(self):

        print("\n🎤 Waiting for speech...")

        filename = self.recorder.record(
            seconds=3,
            filename="voice.wav"
        )

        text = self.transcriber.transcribe(filename)

        return text