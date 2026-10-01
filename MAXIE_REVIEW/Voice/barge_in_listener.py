import logging
import queue
import threading
import time

import numpy as np

from Config.config import Config
from Logs.logger import Logger


class BargeInListener:
    """Echo-aware STOP detection while MAXIE is speaking.

    Runs a separate microphone stream during TTS. Only short, pure
    stop-phrase utterances can interrupt:

      - adaptive RMS threshold (noise floor measured live, so the
        laptop speaker -> laptop microphone path isn't mistaken for a
        new utterance)
      - utterances longer than ``max_utterance_seconds`` (i.e. MAXIE's
        own continuous speech) are never treated as a stop command
      - recognized text must be a pure stop phrase ("stop", "stop stop",
        "be quiet", ...)

    Also guarded by a short settlement period after start.
    """

    STOP_PHRASES = {
        "stop",
        "stop stop",
        "stop speaking",
        "shut up",
        "shut up stop",
        "be quiet",
        "quiet",
        "quiet stop",
        "enough",
        "cancel",
        "stop now",
    }

    def __init__(self, transcriber, device):
        self.transcriber = transcriber
        self.device = device

        cfg = Config.audio()
        self.sample_rate = int(cfg.get("sample_rate", 16000))
        self.channels = 1
        self.block_size = int(cfg.get("block_size", 512))

        self.running = False
        self.interrupted = False

        self.stream = None
        self.thread = None
        self.queue = None

        self.rms_threshold = float(cfg.get("barge_in_rms_threshold", 0.003))
        self.capture_seconds = float(cfg.get("barge_in_capture_seconds", 1.0))
        self.max_utterance_seconds = float(
            cfg.get("barge_in_max_utterance_seconds", 2.2)
        )
        self.settlement_blocks = int(cfg.get("barge_in_settlement_blocks", 6))
        self.quiet_for_stop = float(cfg.get("barge_in_quiet_for_stop", 0.35))

        self.logger = Logger.instance()

    @staticmethod
    def _audio_available():
        try:
            import sounddevice  # noqa: F401

            return True
        except Exception:
            return False

    # ----------------------------------------------------------
    # START
    # ----------------------------------------------------------

    def start(self):
        if self.running:
            return
        if not self._audio_available():
            return

        import queue as _queue

        import sounddevice as sd

        self.running = True
        self.interrupted = False
        self.queue = _queue.Queue(maxsize=512)

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=self.block_size,
                dtype="float32",
                device=self.device,
                callback=self._callback,
            )
            self.stream.start()
            self.thread = threading.Thread(target=self._listen, daemon=True)
            self.thread.start()
        except Exception as error:
            self.running = False
            self.logger.error(f"Barge-in startup error: {error}")

    def _callback(self, indata, frames, time_info, status):
        if not self.running or status:
            return
        if self.queue is not None:
            try:
                self.queue.put_nowait(indata.copy())
            except Exception:
                pass

    # ----------------------------------------------------------
    # LISTEN WITH ECHO PROTECTION
    # ----------------------------------------------------------

    def _listen(self):
        speech_buffer = []
        speech_started = False
        start_time = 0.0
        noise_floor = None
        block_index = 0

        while self.running:
            try:
                block = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            block = np.asarray(block, dtype=np.float32).flatten()
            if len(block) == 0:
                continue

            block_index += 1
            rms = float(np.sqrt(np.mean(block * block)))

            # Live noise-floor calibration so MAXIE's own speaker audio
            # raises the floor once it reaches the mic.
            if block_index <= self.settlement_blocks:
                noise_floor = rms if noise_floor is None else max(noise_floor, rms)
                continue

            if noise_floor is None:
                noise_floor = rms
            else:
                noise_floor = 0.9 * noise_floor + 0.1 * rms

            threshold = max(self.rms_threshold, noise_floor * 2.5)

            if rms >= threshold:
                if not speech_started:
                    speech_started = True
                    start_time = time.monotonic()
                    speech_buffer = []
                speech_buffer.append(block)

                elapsed = time.monotonic() - start_time
                if elapsed >= self.capture_seconds and rms >= threshold:
                    # Enough energy captured; decode immediately so STOP
                    # is reacted to within a fraction of a second.
                    audio = np.concatenate(speech_buffer)
                    if self._maybe_interrupt(audio):
                        return
                    speech_buffer = []
                    speech_started = False

            elif speech_started:
                speech_buffer.append(block)
                elapsed = time.monotonic() - start_time
                if elapsed >= self.quiet_for_stop:
                    audio = np.concatenate(speech_buffer)
                    if self._maybe_interrupt(audio):
                        return
                    speech_buffer = []
                    speech_started = False

    # ----------------------------------------------------------
    # DECODE & MATCH
    # ----------------------------------------------------------

    def _maybe_interrupt(self, audio):
        if not self.running or audio is None:
            return False

        if len(audio) < 512:
            return False

        duration = len(audio) / self.sample_rate
        if duration > self.max_utterance_seconds:
            # Too long -> almost certainly MAXIE's own speech, not a
            # user's short STOP. Ignore to prevent echo false positives.
            return False

        text = self._transcribe(audio)
        if not text:
            return False

        self.logger.info(f"Barge-in recognized: {text}")

        if self._is_stop(text):
            print("🛑 STOP command detected.")
            self.interrupted = True
            self.running = False
            self._close_stream()
            return True
        return False

    def _transcribe(self, audio):
        if self.transcriber is None or self.transcriber.model is None:
            return ""

        filename = Config.temp_path("barge_stop.wav")

        try:
            try:
                from scipy.io import wavfile as wav

                wav.write(filename, self.sample_rate, audio)
            except OSError:
                return ""

            segments, info = self.transcriber.model.transcribe(
                filename,
                language="en",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
                without_timestamps=True,
                initial_prompt=(
                    "stop, stop speaking, be quiet, quiet, cancel, enough"
                ),
            )
        except Exception as error:
            self.logger.error(f"Barge-in recognition error: {error}")
            return ""
        finally:
            try:
                import os

                os.remove(filename)
            except OSError:
                pass

        text = " ".join(
            segment.text.strip()
            for segment in segments
            if getattr(segment, "text", "")
        ).strip().lower()
        return text

    def _is_stop(self, text):
        text = text.strip()
        for char in (".", ",", "!", "?"):
            text = text.replace(char, "")
        text = " ".join(text.split())

        if text in self.STOP_PHRASES:
            return True

        words = text.split()
        if words and all(word == "stop" for word in words):
            return True
        if words and all(word == "quiet" for word in words):
            return True

        return False

    # ----------------------------------------------------------
    # STATUS / STOP
    # ----------------------------------------------------------

    def was_interrupted(self):
        return self.interrupted

    def _close_stream(self):
        stream = self.stream
        self.stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def stop(self):
        self.running = False
        self._close_stream()
        if self.queue is not None:
            try:
                while True:
                    self.queue.get_nowait()
            except Exception:
                pass
        self.queue = None