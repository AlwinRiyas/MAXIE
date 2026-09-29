import logging

from Config.config import Config


class Transcriber:
    """Speech transcription via faster-whisper.

    The model is loaded lazily (first use) from the configured model
    size. If faster-whisper isn't installed the transcriber degrades
    gracefully and returns empty text so the rest of MAXIE keeps
    running.
    """

    log = logging.getLogger("MAXIE.transcriber")

    def __init__(self):
        cfg = Config.audio()
        self.model_size = cfg.get("whisper_model", "base.en")
        self.device = cfg.get("whisper_device", "cpu")
        self.compute_type = cfg.get("whisper_compute_type", "int8")
        self.language = cfg.get("whisper_language", "en")

        self.model = None
        self._loaded = False

    @staticmethod
    def is_available():
        try:
            from faster_whisper import WhisperModel  # noqa: F401

            return True
        except Exception:
            return False

    def _ensure_model(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            from faster_whisper import WhisperModel

            print("Loading Whisper model...")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            print("Whisper Ready.")
        except Exception as error:
            self.model = None
            self.log.error(f"Whisper unavailable: {error}")

    def transcribe(self, filename):
        self._ensure_model()
        if not filename or self.model is None:
            return ""

        try:
            segments, info = self.model.transcribe(
                filename,
                language=self.language,
                beam_size=3,
                best_of=3,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
                initial_prompt=(
                    "MAXIE personal AI assistant. Common commands include: "
                    "open, launch, start, close, calculator, Brave, Chrome, "
                    "Android Studio, time, date, weather, remember, search, "
                    "exit, quit, stop."
                ),
            )
        except Exception as error:
            self.log.error(f"Transcription failed: {error}")
            return ""

        text = " ".join(
            segment.text.strip()
            for segment in segments
            if getattr(segment, "text", "") and segment.text.strip()
        ).strip()
        return text