from faster_whisper import WhisperModel


class Transcriber:

    def __init__(self):

        print("Loading Whisper Base Model...")

        self.model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )

        print("Whisper Base Ready.")

    def transcribe(self, filename):

        segments, info = self.model.transcribe(
            filename,
            beam_size=5,
            language="en"
        )

        text = ""

        for segment in segments:
            text += segment.text

        return text.strip().lower()