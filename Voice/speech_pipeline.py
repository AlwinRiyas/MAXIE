import os
import tempfile

from Voice.audio_manager import AudioManager
from Voice.audio_recorder import AudioRecorder
from Voice.transcriber import Transcriber


class SpeechPipeline:
    """Audio capture -> transcription."""

    def __init__(self):
        self.recorder = AudioRecorder()
        # SEC-01 / ROADMAP 5.8: share the process-wide Whisper model so the
        # laptop mic and the phone /voice endpoint never load it twice.
        self.transcriber = Transcriber.shared()
        self.audio_manager = self.recorder.audio_manager
        self._tmpdir = None

    @staticmethod
    def is_available():
        return AudioManager.is_available()

    def recognize(self, filename=None):
        # TD-31: never write a relative "voice.wav" into the CWD. Capture to
        # a per-process temp file and remove it after transcription.
        own_tmp = not filename
        if filename is None:
            if self._tmpdir is None:
                self._tmpdir = tempfile.mkdtemp(prefix="maxie_voice_")
            filename = os.path.join(self._tmpdir, "voice.wav")

        try:
            captured = self.recorder.record(filename=filename)
            if not captured:
                return ""

            text = self.transcriber.transcribe(captured)
            return text if text else ""
        finally:
            if own_tmp:
                try:
                    os.remove(filename)
                except OSError:
                    pass