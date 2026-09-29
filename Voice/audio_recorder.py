import logging
import queue
import time
from collections import deque

import numpy as np

from Config.config import Config
from Voice.audio_manager import AudioManager
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

        try:
            import sounddevice as sd
        except Exception as error:
            self.log.warning(f"sounddevice import failed: {error}")
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

        incoming = queue.Queue(maxsize=512)
        stream = None
        stream_error = [None]

        def callback(indata, frames, time_info, status):
            if status:
                return
            if incoming.full():
                return
            incoming.put_nowait(indata.copy())

        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=self.block_size,
                dtype="float32",
                device=device,
                callback=callback,
            )
            stream.start()
        except Exception as error:
            stream_error[0] = error
            # InputStream() succeeded but start() failed — a common PortAudio
            # error. Close the handle or it leaks on every failed listen
            # (TD-31).
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
                stream = None

        if stream_error[0] is not None:
            print(f"🎤 Recording error: {stream_error[0]}")
            self.log.error(f"Recording error: {stream_error[0]}")
            return None

        print("🎤 Listening...")

        # Re-calibrate the ambient floor for this session (TD-05). Without a
        # production caller the floor latches to whichever blocks happened to
        # arrive in a previous session and never recovers.
        self.vad.reset_noise()

        try:
            speech = self._listen_loop(
                incoming, max_total_blocks, speech_samples, block_seconds,
                max_total_seconds=total_budget,
            )
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

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

        speech = self._normalize(speech)

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
        last_diag = time.monotonic()

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

        while total_blocks < max_total_blocks:
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                break

            try:
                block = incoming.get(timeout=0.1)
            except queue.Empty:
                # Silence is fine, but not forever.
                continue

            total_blocks += 1
            block = np.asarray(block, dtype=np.float32).flatten()
            if len(block) == 0:
                continue

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
                if sum(len(b) for b in buffer) >= speech_samples:
                    break
            else:
                # ---- waiting for speech ----
                if is_speech:
                    buffer.extend(pre_roll)
                    buffer.append(block)
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

    def _normalize(self, speech):
        """Normalize weak speech without clipping.

        - weak speech (< weak_rms_threshold) gets a gain scaled toward a
          comfortable headroom instead of a blind multiplier
        - everything is clipped at 0.98 to avoid distortion
        """
        speech = np.asarray(speech, dtype=np.float32)
        peak = float(np.max(np.abs(speech)))
        if peak == 0:
            return speech

        weak_threshold = float(Config.audio().get("weak_rms_threshold", 0.005))
        rms = float(np.sqrt(np.mean(speech * speech)))

        gain = 1.0
        if rms > 0 and rms < weak_threshold:
            module_gain = float(Config.audio().get("weak_speech_gain", 4.0))
            # Scale toward a target RMS (~0.04) but cap by module gain.
            target_rms = min(0.04, weak_threshold * module_gain)
            gain = min(module_gain, target_rms / rms)

        speech = speech * gain

        # Soft peak headroom clip (never hard-clip signal).
        max_abs = float(np.max(np.abs(speech)))
        if max_abs > 0.98:
            speech = speech * (0.98 / max_abs)

        return np.clip(speech, -1.0, 1.0)

    # ----------------------------------------------------------
    # COMPAT
    # ----------------------------------------------------------

    def clear_audio(self):
        """Kept for compatibility; the streaming recorder keeps no
        cached audio between take() calls."""
        self.last_audio = None