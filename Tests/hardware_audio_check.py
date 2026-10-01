"""MAXIE physical audio verification helper.

Run on the target laptop from the MAXIE repository:
    python Tests/hardware_audio_check.py

This script performs only diagnostics. It does not modify MAXIE configuration,
source files, models, or persistent memory. Hardware-dependent conclusions
must be based on the output from the target machine.
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


def check_import(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def main() -> int:
    print("=" * 72)
    print("MAXIE 1 — TASK 2 PHYSICAL AUDIO VERIFICATION")
    print("=" * 72)
    print("This is a diagnostic only. No MAXIE source/configuration is modified.")
    print()

    print("Environment")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")
    print(f"Repository: {ROOT}")
    print()

    print("1. Dependency availability")
    deps = {
        "numpy": check_import("numpy"),
        "sounddevice": check_import("sounddevice"),
        "torch": check_import("torch"),
        "silero_vad": check_import("silero_vad"),
        "faster_whisper": check_import("faster_whisper"),
    }
    for name, present in deps.items():
        report(f"import {name}", "PASS" if present else "UNVERIFIED",
               "available" if present else "not installed in this Python environment")
    print()

    if not deps["sounddevice"]:
        report("Audio device enumeration", "UNVERIFIED",
               "sounddevice is unavailable; install/use the project's intended audio dependency.")
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

    print("2. Microphone capture diagnostic")
    capture_path = None
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

            fd, capture_path = tempfile.mkstemp(prefix="maxie_task2_", suffix=".wav")
            os.close(fd)
            with wave.open(capture_path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                pcm = np.clip(audio, -1.0, 1.0)
                wav.writeframes((pcm * 32767).astype(np.int16).tobytes())

            if peak <= 0.0001:
                report("Microphone capture", "FAIL",
                       f"recording was effectively silent (RMS={rms:.6f}, peak={peak:.6f})")
            else:
                report("Microphone capture", "PASS",
                       f"captured {seconds}s; RMS={rms:.6f}, peak={peak:.6f}")
        except Exception as exc:
            report("Microphone capture", "FAIL", repr(exc))
    print()

    print("3. MAXIE VAD diagnostic")
    if capture_path is None:
        report("VAD on physical recording", "UNVERIFIED",
               "no physical microphone recording was produced")
    else:
        try:
            import numpy as np
            import soundfile as sf

            from Voice.vad_engine import VADEngine

            audio, rate = sf.read(capture_path, dtype="float32")
            audio = np.asarray(audio).reshape(-1)

            vad = VADEngine()
            if rate != vad.sample_rate:
                report("VAD on physical recording", "UNVERIFIED",
                       f"recording rate={rate}, MAXIE VAD rate={vad.sample_rate}")
            else:
                timestamps = vad.get_speech_timestamps(audio)
                if timestamps:
                    report("VAD on physical recording", "PASS",
                           f"speech region(s) detected: {timestamps}")
                else:
                    report("VAD on physical recording", "FAIL",
                           "no speech region detected in the spoken recording")
        except Exception as exc:
            report("VAD on physical recording", "UNVERIFIED", repr(exc))
    print()

    print("4. Faster-Whisper real transcription diagnostic")
    if capture_path is None:
        report("Real STT transcription", "UNVERIFIED",
               "no physical microphone recording was produced")
    elif not deps["faster_whisper"]:
        report("Real STT transcription", "UNVERIFIED",
               "faster_whisper is not installed in this Python environment")
    else:
        try:
            from faster_whisper import WhisperModel

            print("            Loading the configured model may take time on first run.")
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, info = model.transcribe(capture_path, beam_size=1)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                report("Real STT transcription", "PASS",
                       f"detected language={getattr(info, 'language', '?')}; text={text!r}")
            else:
                report("Real STT transcription", "FAIL",
                       "Whisper completed but returned no transcription")
        except Exception as exc:
            report("Real STT transcription", "FAIL", repr(exc))
    print()

    print("5. TTS / speaker diagnostic")
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
        print("            Confirm physically whether the phrase was audible.")
        report("Speaker playback", "UNVERIFIED",
               "requires human confirmation of audible playback")
    except Exception as exc:
        report("TTS invocation", "FAIL", repr(exc))
        report("Speaker playback", "UNVERIFIED",
               "TTS invocation failed before physical playback could be confirmed")
    print()

    if capture_path:
        try:
            os.remove(capture_path)
        except OSError:
            pass

    print("=" * 72)
    print("TASK 2 DIAGNOSTIC COMPLETE")
    print("Do not treat UNVERIFIED results as PASS.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
