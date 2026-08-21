from Voice.audio_recorder import AudioRecorder
from Voice.transcriber import Transcriber


class SpeechPipeline:

    def __init__(self):

        self.recorder = AudioRecorder()
        self.transcriber = Transcriber()

    def recognize(self):

        filename = self.recorder.record(
            filename="voice.wav",
            max_seconds=10,
            silence_seconds=1.0
        )

        if filename is None:

            return ""

        text = self.transcriber.transcribe(
            filename
        )

        if not text:

            return ""

        return text.strip()