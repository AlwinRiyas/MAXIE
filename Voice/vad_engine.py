import logging
import time
from collections import deque

import numpy as np

from Config.config import Config


class VADEngine:
    """Speech activity detection.

    Uses Silero VAD when torch + silero_vad are installed; otherwise
    falls back to an adaptive RMS energy gate so the pipeline still
    works headless / without the ML stack.

    API preserved from the original module:
      get_speech_timestamps(audio) -> [{'start':..,'end':..}, ...]
      has_voice(audio)              -> bool
      get_speech_region(audio, padding_seconds) -> (start, end) | None

    Added for streaming:
      speech_probability(block)     -> float 0..1
      process_block(block)          -> bool (is speech)
      adaptive_threshold()
    """

    log = logging.getLogger("MAXIE.vad")

    def __init__(self):
        self.sample_rate = int(Config.audio().get("sample_rate", 16000))
        self.threshold = float(Config.audio().get("vad_threshold", 0.35))
        self.min_speech_duration_ms = int(
            Config.audio().get("min_speech_ms", 150)
        )
        self.min_silence_duration_ms = int(
            Config.audio().get("min_silence_ms", 500)
        )

        self.model = None
        self._silero_loaded = False
        self._last_silero_attempt = 0.0
        self._silero_retry_seconds = float(
            Config.audio().get("silero_retry_seconds", 60)
        )
        self._noise_floor = None
        self._energy_threshold = float(
            Config.audio().get("barge_in_rms_threshold", 0.003)
        )
        # TD-05: the adaptive gate is *calibrated* — a bounded SNR ratio, not
        # a fixed 3x ambient that real rooms (1.5-2x) can never satisfy.
        self._noise_ratio = float(Config.audio().get("vad_noise_ratio", 1.8))
        self._recent_probs = deque(maxlen=4)

    # ----------------------------------------------------------
    # Model loading (lazy, optional)
    # ----------------------------------------------------------

    def _ensure_silero(self):
        if self._silero_loaded:
            return
        now = time.monotonic()
        if now - self._last_silero_attempt < self._silero_retry_seconds:
            return
        self._last_silero_attempt = now
        try:
            from silero_vad import load_silero_vad

            self.model = load_silero_vad()
            self._silero_loaded = True  # only latch on success (TD-06)
            self.log.info("Silero VAD loaded.")
        except Exception as error:
            self.model = None
            self._silero_loaded = False
            self.log.warning(f"Silero unavailable (falling back to energy VAD): {error}")

    @property
    def has_ml(self):
        self._ensure_silero()
        return self.model is not None

    # ----------------------------------------------------------
    # Streaming decisions
    # ----------------------------------------------------------

    def speech_probability(self, block):
        block = self._as_float(block)
        if self.has_ml:
            try:
                import torch

                tensor = torch.from_numpy(block)
                return float(self.model(tensor, self.sample_rate))
            except Exception:
                pass
        return None

    def process_block(self, block):
        """Return True if the block contains speech.

        Uses Silero VAD probabilities (smoothed over a few blocks) when
        available, otherwise an adaptive RMS energy gate.
        """
        block = self._as_float(block)
        if len(block) == 0:
            return False

        if self.has_ml:
            prob = self.speech_probability(block)
            if prob is not None:
                self._recent_probs.append(prob)
                if len(self._recent_probs) < 3:
                    return False
                average = sum(self._recent_probs) / len(self._recent_probs)
                return average >= self.threshold * 0.6

        rms = float(np.sqrt(np.mean(block * block)))

        if self.noise_floor is None:
            return rms > self._energy_threshold

        # A real room's speech hovers ~1.5-2x its ambient noise floor. The
        # gate is the *larger* of the absolute calibrated floor and a bounded
        # adaptive floor (ambient * ratio), so loud rooms adapt while still
        # requiring a genuine SNR step above ambient.
        adaptive_floor = self.noise_floor * self._noise_ratio
        return rms > max(self._energy_threshold, adaptive_floor)

    @property
    def noise_floor(self):
        return self._noise_floor

    def observe_noise(self, block):
        """Calibrate the ambient noise floor from a quiet block."""
        block = self._as_float(block)
        if len(block) == 0:
            return
        rms = float(np.sqrt(np.mean(block * block)))
        if self._noise_floor is None:
            self._noise_floor = rms
        else:
            self._noise_floor = 0.9 * self._noise_floor + 0.1 * rms

    def reset_noise(self):
        self._noise_floor = None

    def set_energy_threshold(self, value):
        self._energy_threshold = max(0.0001, float(value))

    def get_energy_threshold(self):
        return self._energy_threshold

    # ----------------------------------------------------------
    # Offline tools (whole clip)
    # ----------------------------------------------------------

    def get_speech_timestamps(self, audio):
        if audio is None:
            return []
        audio = self._as_float(audio)
        if len(audio) < 512:
            return []

        # ML path.
        if self.has_ml:
            try:
                import torch
                from silero_vad import get_speech_timestamps as silero_ts

                tensor = torch.from_numpy(audio)
                return silero_ts(
                    tensor,
                    self.model,
                    sampling_rate=self.sample_rate,
                    threshold=self.threshold,
                    min_speech_duration_ms=self.min_speech_duration_ms,
                    min_silence_duration_ms=self.min_silence_duration_ms,
                )
            except Exception as error:
                self.log.debug(f"Silero timestamp error: {error}")

        # Energy fallback.
        return self._energy_timestamps(audio)

    def _energy_timestamps(self, audio):
        block = self.sample_rate // 20  # 50 ms hop
        speech_mask = []
        for i in range(0, len(audio) - block + 1, block):
            window = audio[i:i + block]
            rms = float(np.sqrt(np.mean(window * window)))
            speech_mask.append(rms > self._energy_threshold)

        if not any(speech_mask):
            return []

        start_sample = speech_mask.index(True) * block
        last_true = len(speech_mask) - 1 - speech_mask[::-1].index(True)
        end_sample = min(len(audio), (last_true + 1) * block)
        start_sample = max(0, start_sample - self.sample_rate // 20)
        end_sample = min(len(audio), end_sample + self.sample_rate // 20)

        return [{"start": start_sample, "end": end_sample}]

    def has_voice(self, audio):
        return len(self.get_speech_timestamps(audio)) > 0

    def get_speech_region(self, audio, padding_seconds=0.15):
        timestamps = self.get_speech_timestamps(audio)
        if not timestamps:
            return None

        start = timestamps[0]["start"]
        end = timestamps[-1]["end"]

        padding = int(padding_seconds * self.sample_rate)
        start = max(0, start - padding)
        end = min(len(audio), end + padding)
        return start, end

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _as_float(block):
        return np.asarray(block, dtype=np.float32).flatten()