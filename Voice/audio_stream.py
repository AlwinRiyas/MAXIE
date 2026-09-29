import logging

from Voice.audio_manager import AudioManager


class AudioStream:
    """Continuous raw audio stream used for diagnostics and future
    real-time features. Requires sounddevice only at runtime."""

    log = logging.getLogger("MAXIE.audio_stream")

    def __init__(self):
        self.sample_rate = 16000
        self.channels = 1
        self.block_size = 512

        self.audio = AudioManager()
        self.queue = None
        self.stream = None
        self._sd = None

    @staticmethod
    def is_available():
        return AudioManager.is_available()

    def callback(self, indata, frames, time_info, status):
        if status:
            return
        if self.queue is not None:
            self.queue.put_nowait(indata.copy().flatten())

    def start(self):
        if not self.is_available() or self.stream is not None:
            return

        import queue as _queue

        import sounddevice as sd

        self._sd = sd
        self.queue = _queue.Queue(maxsize=1024)
        device = self.audio.get_best_microphone()

        print(f"\nUsing Microphone: {device}")

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.block_size,
            dtype="float32",
            device=device,
            callback=self.callback,
        )
        self.stream.start()
        print("🎤 Audio Stream Started")

    def read(self, timeout=1.0):
        if self.queue is None:
            return None
        try:
            return self.queue.get(timeout=timeout)
        except Exception:
            return None

    def clear(self):
        if self.queue is None:
            return
        try:
            while True:
                self.queue.get_nowait()
        except Exception:
            pass

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            self.queue = None