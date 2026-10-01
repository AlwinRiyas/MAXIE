"""MAXIE physical audio verification helper.

Run on the target laptop:
    python Tests/hardware_audio_check.py

Diagnostic only. It does not modify MAXIE configuration, source, models, or
persistent memory. Hardware conclusions must come from the target machine.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def report(name: str, status: str, detail: str = "") -> None:
    print(f"[{status:<9}] {name}")
    if detail:
        print(f"            {detail}")


def available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def main() -> int:
    print("=" * 72)
    print("MAXIE 1 — TASK 2 PHYSICAL AUDIO VERIFICATION")
    print("=" * 72)
    print("Diagnostic only; no MAXIE source/configuration is modified.")
    print()

    deps = {
        "numpy": available("numpy"),
        "sounddevice": available("sounddevice"),
        "torch": available("torch"),
        "silero_vad": available("silero_vad"),
        "faster_whisper": available("faster_whisper"),
    }

    print("1. Dependency availability")
    for name, present in deps.items():
        report(f"import {name}", "PASS" if present else "UNVERIFIED",
               "available" if present else "not installed in this Python environment")
    print()

    if not deps["sounddevice"]:
        report("Audio device enumeration", "UNVERIFIED", "sounddevice unavailable")
    else:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            report("Audio device enumeration", "PASS",
                   f"{len(devices)} PortAudio device entries found")
            for index, device in enumerate(devices):
                print(
                    f"            [{index}] {device.get('name', '<unknown>')} "
                    f"in={device.get('max_input_channels', 0)} "
                    f"out={device.get('max_output_channels', 0)} "
                    f"rate={device.get('default_samplerate', '?')}"
                )
        except Exception as exc:
            report("Audio device enumeration", "FAIL", repr(exc))
    print()

    capture_path = None
    print("2. Microphone capture")
    if not deps["sounddevice"] or not deps["numpy"]:
        report("Microphone capture", "UNVERIFIED",
               "sounddevice and/or numpy unavailable")
    else:
        try:
            import numpy as np
            import sounddevice as sd

            sample_rate = 16000
            seconds = 3
            print("            Speak normally for 3 seconds when recording starts.")
            recording = sd.rec(
                int(sample_rate * seconds),
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
            )
            sd.wait()

            audio = np.asarray(recording).reshape(-1)
            rms = float(np.sqrt(np.mean(audio * audio)))
            peak = float(np.max(np.abs(audio))) if len(audio) else 0.0

            fd, capture_path = tempfile.mkstemp(
                prefix="maxie_task2_", suffix=".wav"
            )
            os.close(fd)
            with wave.open(capture_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                pcm = np.clip(audio, -1.0, 1.0)
                wav.writeframes((pcm * 32767).astype(np.int16).tobytes())

            if peak <= 0.0001:
                report("Microphone capture", "FAIL",
                       f"effectively silent: RMS={rms:.6f}, peak={peak:.6f}")
            else:
                report("Microphone capture", "PASS",
                       f"{seconds}s captured: RMS={rms:.6f}, peak={peak:.6f}")
        except Exception as exc:
            report("Microphone capture", "FAIL", repr(exc))
    print()

    print("3. MAXIE VAD")
    if capture_path is None:
        report("VAD on physical recording", "UNVERIFIED", "no recording available")
    else:
        try:
            import numpy as np
            from Voice.vad_engine import VADEngine

            with wave.open(capture_path, "rb") as wav:
                rate = wav.getframerate()
                frames = wav.readframes(wav.getnframes())

            audio = (
                np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            )
            vad = VADEngine()
            if rate != vad.sample_rate:
                report("VAD on physical recording", "UNVERIFIED",
                       f"recording rate={rate}, MAXIE VAD rate={vad.sample_rate}")
            else:
                timestamps = vad.get_speech_timestamps(audio)
                if timestamps:
                    report("VAD on physical recording", "PASS",
                           f"speech region(s): {timestamps}")
                else:
                    report("VAD on physical recording", "FAIL",
                           "no speech region detected")
        except Exception as exc:
            report("VAD on physical recording", "UNVERIFIED", repr(exc))
    print()

    print("4. Faster-Whisper real transcription")
    if capture_path is None:
        report("Real STT transcription", "UNVERIFIED", "no recording available")
    elif not deps["faster_whisper"]:
        report("Real STT transcription", "UNVERIFIED",
               "faster_whisper unavailable")
    else:
        try:
            from faster_whisper import WhisperModel

            print("            Loading base.en may take time on first run.")
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, info = model.transcribe(capture_path, beam_size=1)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                report("Real STT transcription", "PASS",
                       f"language={getattr(info, 'language', '?')}; text={text!r}")
            else:
                report("Real STT transcription", "FAIL",
                       "Whisper returned no transcription")
        except Exception as exc:
            report("Real STT transcription", "FAIL", repr(exc))
    print()

    print("5. TTS / speaker")
    try:
        from Voice.voice_engine import VoiceEngine

        engine = VoiceEngine()
        print("            MAXIE will attempt a short local TTS phrase.")
        started = time.monotonic()
        result = engine.speak(
            "MAXIE audio verification. If you can hear this sentence, speaker playback works."
        )
        elapsed = time.monotonic() - started
        report("TTS invocation", "PASS" if result is not False else "FAIL",
               f"speak() returned {result!r} after {elapsed:.2f}s")
        report("Speaker playback", "UNVERIFIED",
               "requires human confirmation of audible playback")
    except Exception as exc:
        report("TTS invocation", "FAIL", repr(exc))
        report("Speaker playback", "UNVERIFIED",
               "TTS invocation failed before physical playback confirmation")
    print()

    if capture_path:
        try:
            os.remove(capture_path)
        except OSError:
            pass

    print("=" * 72)
    print("TASK 2 DIAGNOSTIC COMPLETE")
    print("UNVERIFIED is not PASS.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
