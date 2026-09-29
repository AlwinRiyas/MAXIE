import logging
import time
from collections import deque

import numpy as np

from Config.config import Config
from Voice.audio_manager import AudioManager
from Voice.microphone_capture import MicrophoneCapture
from Voice.vad_engine import VADEngine


class AudioRecorder:
    """Streaming, VAD-driven audio recorder.

    Unlike the previous fixed-duration ``sd.rec`` approach, this opens
    a block stream and only captures while speech is present:

      - waits for speech start (silero probability or energy, with an
        adaptive noise floor so background noise is tolerated)
      - captures speech + a short pre-roll
      - finalizes after ``min_silence_ms`` of trailing silence
      - caps at ``max_seconds``
      - normalizes weak speech without clipping

    No fixed-length waiting. Returns the wav filename or None when no
    speech was found.
    """

    log = logging.getLogger("MAXIE.recorder")

    def __init__(self):
        cfg = Config.audio()
        self.sample_rate = int(cfg.get("sample_rate", 16000))
        self.channels = 1
        self.block_size = int(cfg.get("block_size", 512))

        self.max_seconds = float(cfg.get("max_seconds", 12))
        self.min_silence_ms = int(cfg.get("min_silence_ms", 500))
        self.silence_blocks = max(
            2, int(self.min_silence_ms * self.sample_rate / 1000 / self.block_size)
        )
        self.pre_roll_ms = int(cfg.get("pre_roll_ms", 220))
        self.pre_roll_blocks = max(
            1, int(self.pre_roll_ms * self.sample_rate / 1000 / self.block_size)
        )
        self.speech_wait_timeout = float(cfg.get("speech_wait_timeout", 20))

        self.blocks_per_second = self.sample_rate / self.block_size

        # Adaptive gain state (ROADMAP 1.4): a slow-attack, fast-release
        # target so weak microphones are boosted without blasting loud ones.
        self._agc_target = float(cfg.get("agc_target_rms", 0.02))
        self._agc_max_gain = float(cfg.get("agc_max_gain", 8.0))
        self._agc_gain = 1.0

        self.audio_manager = AudioManager()
        self.vad = VADEngine()

        self.last_audio = None

    # ----------------------------------------------------------
    # PUBLIC
    # ----------------------------------------------------------

    def record(self, filename="voice.wav", max_seconds=None):
        if not AudioManager.is_available():
            self.log.warning("sounddevice not installed; cannot record.")
            print("🎤 Audio input unavailable (sounddevice missing).")
            return None

        if not MicrophoneCapture.backend_available():
            self.log.warning("no capture backend available.")
            print("🎤 Audio input unavailable.")
            return None

        device = self.audio_manager.get_best_microphone()
        if device is None:
            print("🎤 No microphone found.")
            return None

        capture_limit = max_seconds or self.max_seconds
        if capture_limit <= 0:
            capture_limit = self.max_seconds

        # Absolute wall-clock budget for this listen, so a stalled device can
        # never hang the conversation thread (TD-03).
        total_budget = self._total_budget(capture_limit)

        block_seconds = self.block_size / self.sample_rate
        max_total_blocks = int(capture_limit * self.blocks_per_second) + self.silence_blocks + 2
        speech_samples = int(capture_limit * self.sample_rate)

        capture = self._open_capture(device)
        if capture is None:
            print("🎤 Recording error: cannot open a microphone stream.")
            return None

        print("🎤 Listening...")

        # Re-calibrate the ambient floor for this session (TD-05). Without a
        # production caller the floor latches to whichever blocks happened to
        # arrive in a previous session and never recovers.
        self.vad.reset_noise()

        try:
            speech = self._listen_loop(
                capture, max_total_blocks, speech_samples, block_seconds,
                max_total_seconds=total_budget,
            )
        finally:
            capture.close()

        if speech is None:
            print("⚠️ No speech detected.")
            return None

        self.last_audio = speech

        # Trim leading/trailing silence.
        region = self.vad.get_speech_region(speech, padding_seconds=0.10)
        if region is not None:
            start, end = region
            speech = speech[start:end]

        if len(speech) < 512:
            print("⚠️ Recording too short.")
            return None

        speech = self._apply_agc(speech)

        try:
            from scipy.io import wavfile as wav

            wav.write(filename, self.sample_rate, speech)
        except OSError as error:
            self.log.error(f"Couldn't write wav: {error}")
            return None

        duration = len(speech) / self.sample_rate
        print(f"✅ Audio captured ({duration:.2f}s) -> {filename}")
        return filename

    # ----------------------------------------------------------
    # STREAMING LOOP
    # ----------------------------------------------------------

    def _open_capture(self, device):
        try:
            return MicrophoneCapture(
                sample_rate=self.sample_rate,
                channels=self.channels,
                block_size=self.block_size,
                device=device,
            ).open()
        except Exception as error:
            self.log.error(f"Recording error: {error}")
            print(f"🎤 Recording error: {error}")
            return None

    def _read_block(self, capture, timeout=0.1):
        try:
            if isinstance(capture, MicrophoneCapture):
                return capture.read(timeout=timeout)
            # Plain queue.Queue (unit tests, deadline/cleanup paths).
            return capture.get(timeout=timeout)
        except Exception:
            return None

    def _total_budget(self, capture_limit):
        """Wall-clock budget for one listen, in seconds.

        Pre-speech wait + a full utterance + trailing-silence grace. Exposed as
        a method so the deadline is testable without sleeping (TD-03).
        """
        return self.speech_wait_timeout + max(0.0, capture_limit) + 5.0

    def _listen_loop(self, incoming, max_total_blocks, speech_samples,
                     block_seconds, max_total_seconds=None):
        buffer = []
        pre_roll = deque(maxlen=self.pre_roll_blocks)
        start_time = time.monotonic()

        speech_started_at = None
        silent_blocks = 0
        total_blocks = 0
        collected_samples = 0
        last_diag = time.monotonic()

        # Whether `incoming` is a MicrophoneCapture (which can detect hot-plug
        # stalls) or a plain queue handed to tests via _read_block.
        has_recovery = isinstance(incoming, MicrophoneCapture)

        # Wall-clock deadline (TD-03). Block counting alone is not a
        # termination condition: if PortAudio stops delivering callbacks the
        # queue stays empty forever and `incoming.get` raises Empty on every
        # iteration, so `total_blocks` never advances and the loop never
        # returns. Unplugging a USB headset mid-sentence killed the
        # conversation thread permanently this way. The budget covers the
        # pre-speech wait plus a full utterance plus trailing silence.
        if max_total_seconds is None:
            max_total_seconds = self.speech_wait_timeout + self.max_seconds + 5.0
        deadline = start_time + max_total_seconds
        timed_out = False
        stalled = False

        while total_blocks < max_total_blocks:
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                break

            block = self._read_block(incoming, timeout=0.1)
            if block is None:
                # Hot-plug recovery: a device that stops delivering blocks
                # (USB headset unplugged mid-listen) is closed and reopened
                # once, bounded, instead of deadlining the whole read (TD-03).
                if (
                    has_recovery
                    and incoming.has_stalled()
                    and speech_started_at is None
                ):
                    stalled = True
                    if incoming.recover():
                        self.vad.observe_noise(block or np.zeros(
                            self.block_size, dtype=np.float32))
                        deadline = time.monotonic() + max_total_seconds
                        continue
                # Silence is fine, but not forever.
                continue

            block = np.asarray(block, dtype=np.float32).flatten()
            if len(block) == 0:
                continue

            total_blocks += 1
            collected_samples += len(block)
            if has_recovery:
                incoming.stall_blocks = 0

            is_speech = self.vad.process_block(block)

            if not self.vad.has_ml and not self.vad.noise_floor:
                # Energy mode: warm the noise floor from the initial blocks.
                self.vad.observe_noise(block)

            if buffer:
                # ---- collecting speech ----
                if is_speech:
                    buffer.append(block)
                    silent_blocks = 0
                else:
                    buffer.append(block)
                    silent_blocks += 1
                    if silent_blocks >= self.silence_blocks:
                        break
                if collected_samples >= speech_samples:
                    break
            else:
                # ---- waiting for speech ----
                if is_speech:
                    buffer.extend(pre_roll)
                    buffer.append(block)
                    collected_samples += self.pre_roll_blocks * len(
                        pre_roll[0]) if pre_roll else 0
                    speech_started_at = time.monotonic()
                else:
                    pre_roll.append(block)
                    if time.monotonic() - last_diag > 3.0:
                        last_diag = time.monotonic()
                    if (
                        speech_started_at is None
                        and time.monotonic() - start_time > self.speech_wait_timeout
                    ):
                        break

        if stalled:
            self.log.warning(
                "Capture device stalled; the stream was reopened mid-listen."
            )

        if timed_out:
            self.log.warning(
                f"Recording hit the {max_total_seconds:.0f}s wall-clock deadline "
                "(capture stalled or utterance too long)."
            )
            print("⚠️ Recording timed out.")

        if not buffer:
            return None

        audio = np.concatenate(buffer)

        elapsed = time.monotonic() - start_time
        self._print_late_diagnostics(audio, elapsed)
        return audio

    # ----------------------------------------------------------
    # DIAGNOSTICS / NORMALIZATION
    # ----------------------------------------------------------

    def _print_late_diagnostics(self, audio, elapsed):
        rms = float(np.sqrt(np.mean(audio * audio)))
        peak = float(np.max(np.abs(audio)))
        print(f"🔊 RMS {rms:.5f} | Peak {peak:.3f} | waited {elapsed:.1f}s")

    def _apply_agc(self, speech):
        """Adaptive gain control (ROADMAP 1.4).

        Replaces the fixed ``_normalize`` boost: a slow-attack, fast-release
        gain tracks a target RMS so quiet microphones are boosted up to
        ``agc_max_gain`` while loud ones are pulled down. The RMS is computed
        in a single pass (the old code scanned the growing buffer on every
        block, O(n²)).
        """
        speech = np.asarray(speech, dtype=np.float32)
        peak = float(np.max(np.abs(speech)))
        if peak == 0:
            return speech

        rms = float(np.sqrt(np.mean(speech * speech)))
        target = self._agc_target
        max_gain = self._agc_max_gain

        # Slow-attack toward target (boost weak speech), fast-release (never
        # let a loud block blow up).
        if rms > 0:
            desired = min(max_gain, target / rms)
            self._agc_gain += 0.2 * (desired - self._agc_gain)
        gain = self._agc_gain

        speech = speech * gain

        # Soft peak headroom clip (never hard-clip signal).
        max_abs = float(np.max(np.abs(speech)))
        if max_abs > 0.98:
            speech = speech * (0.98 / max_abs)

        return np.clip(speech, -1.0, 1.0)

    def reset_gain(self):
        """Re-arm the AGC gain to unity (call on a new speaker/session)."""
        self._agc_gain = 1.0

    # ----------------------------------------------------------
    # COMPAT
    # ----------------------------------------------------------

    def clear_audio(self):
        """Kept for compatibility; the streaming recorder keeps no
        cached audio between take() calls."""
        self.last_audio = None