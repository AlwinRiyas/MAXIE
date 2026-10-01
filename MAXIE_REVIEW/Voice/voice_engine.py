import os
import shutil
import subprocess
import sys
import threading
import uuid

from Config.config import Config
from Logs.logger import Logger


class VoiceEngine:
    """Cross-platform text-to-speech.

    Engine selection (``tts_engine`` in Config/audio_config.json):
      - ``piper``  offline neural voice (recommended, natural/clarity).
        Install with ``python Installers/setup_tts.py --engine piper``.
      - ``edge``   Microsoft Edge neural voices (most natural, needs
        internet). ``python Installers/setup_tts.py --engine edge``.
      - ``sapi``   Windows System.Speech (default on Windows when piper
        isn't set up).
      - ``pyttsx`` / ``espeak``  Linux fallbacks (robotic-ish).
      - ``auto``   best available in the order above.

    All engines expose speak(text), stop(), is_speaking(), shutdown()
    and never overlap: starting a new utterance stops the old one.
    """

    PIPER_MODEL_DIR = os.path.join("Config", "tts_models")
    PIPER_VOICES = {
        "female": "en_US-lessac-medium",
        "male": "en_US-ryan-medium",
    }

    def __init__(self):
        self.logger = Logger.instance()
        self.process = None
        self.lock = threading.Lock()
        self._speaking = False

        self._pytts_engine = None
        self._pytts_error = None
        self._worker = None
        self._queue = None
        self._stop_signal = None

        self.rate = int(Config.personality().get("speech_rate", 0))
        self.gender = str(
            Config.personality().get("voice_gender", "female")
        ).lower()

        self._engine_name = self._detect_engine()

    # ----------------------------------------------------------
    # Engine detection
    # ----------------------------------------------------------

    def _detect_engine(self):
        forced = str(Config.audio().get("tts_engine", "auto")).lower()

        if forced == "piper":
            return "piper"
        if forced == "edge":
            return "edge"

        if sys.platform.startswith("win"):
            if forced in ("auto", "sapi", "windows"):
                if self._piper_ready() and forced == "auto":
                    return "piper"
                return "sapi"
            return "disabled"

        if sys.platform.startswith("linux"):
            if forced == "auto":
                if self._piper_ready():
                    return "piper"
                if self._edge_ready():
                    return "edge"
                if self._pytts_available():
                    return "pyttsx"
                if Config.which("espeak") or Config.which("espeak-ng"):
                    return "espeak"
            elif forced in ("linux", "pyttsx"):
                if self._pytts_available():
                    return "pyttsx"
                if Config.which("espeak") or Config.which("espeak-ng"):
                    return "espeak"
            elif forced == "espeak":
                if Config.which("espeak") or Config.which("espeak-ng"):
                    return "espeak"
            return "disabled"
        return "disabled"

    @staticmethod
    def _pytts_available():
        try:
            import pyttsx3  # noqa: F401

            return True
        except Exception:
            return False

    # ----------------------------------------------------------
    # Neural engine readiness (piper/edge)
    # ----------------------------------------------------------

    @staticmethod
    def _piper_bin():
        """Return the piper launcher list, or None if not installed."""
        binary = shutil.which("piper")
        if binary:
            return [binary]
        try:
            import piper  # noqa: F401

            return [sys.executable, "-m", "piper"]
        except Exception:
            return None

    @staticmethod
    def _edge_bin():
        binary = shutil.which("edge-tts")
        if binary:
            return [binary]
        try:
            import edge_tts  # noqa: F401

            return [sys.executable, "-m", "edge_tts"]
        except Exception:
            return None

    def _piper_model(self):
        """Absolute path to the piper model, or None.

        Falls back from a stale configured voice to the gender's
        default so a bad config never silently kills TTS."""
        audio = Config.audio()
        configured = str(audio.get("piper_voice", "") or "").strip()
        candidates = []
        if configured:
            candidates.append(configured)
        candidates.append(
            self.PIPER_VOICES.get(self.gender, "en_US-lessac-medium")
        )
        seen = set()
        for voice in candidates:
            if voice in seen:
                continue
            seen.add(voice)
            path = os.path.join(
                Config.resolve(self.PIPER_MODEL_DIR), f"{voice}.onnx"
            )
            if os.path.exists(path):
                return path
        return None

    def _piper_ready(self):
        if not self._piper_bin():
            return False
        model = self._piper_model()
        return bool(model) and os.path.exists(model)

    def _edge_voice(self):
        audio = Config.audio()
        return str(audio.get("edge_voice", "")).strip() or (
            "en-US-JennyNeural"
            if self.gender != "male"
            else "en-US-GuyNeural"
        )

    def _edge_ready(self):
        return bool(self._edge_bin())

    @property
    def disabled(self):
        return self._engine_name == "disabled"

    # ----------------------------------------------------------
    # SPEAK
    # ----------------------------------------------------------

    def speak(self, text):
        if not text or not str(text).strip():
            return False
        if self.disabled:
            print("💬 TTS unavailable on this machine.")
            return False

        text = str(text).strip()

        max_chars = 500
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "."

        self.stop()

        if self._engine_name == "sapi":
            return self._speak_sapi(text)
        if self._engine_name == "piper":
            return self._speak_piper(text)
        if self._engine_name == "edge":
            return self._speak_edge(text)
        if self._engine_name == "pyttsx":
            return self._speak_pyttsx(text)
        if self._engine_name == "espeak":
            return self._speak_espeak(text)
        return False

    # ----------------------------------------------------------
    # Offline neural voice (piper)
    # ----------------------------------------------------------

    def _speak_piper(self, text):
        model = self._piper_model()
        if not self._piper_bin() or not model or not os.path.exists(model):
            self.logger.warning(
                "Piper TTS not available (run "
                "`python Installers/setup_tts.py --engine piper`)."
            )
            return False

        wav = Config.temp_path(f"piper_{uuid.uuid4().hex[:8]}.wav")
        scale = max(0.7, min(1.3, 1.0 + self.rate * 0.03))

        def synth_and_play():
            try:
                subprocess.run(
                    self._piper_bin()
                    + ["--model", model, "--output_file", wav,
                       "--length_scale", str(scale)],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=60,
                )
                if os.path.exists(wav):
                    self._play_audio(wav, "wav")
            except Exception as error:
                self.logger.error(f"Piper TTS failed: {error}")
            finally:
                try:
                    os.unlink(wav)
                except OSError:
                    pass

        with self.lock:
            self._speaking = True
        threading.Thread(target=synth_and_play, daemon=True).start()
        return True

    def _edge_voice_name(self):
        return self._edge_voice()

    def _speak_edge(self, text):
        base = self._edge_bin()
        if not base:
            self.logger.warning(
                "Edge TTS not installed (run "
                "`python Installers/setup_tts.py --engine edge`)."
            )
            return False

        out = Config.temp_path(f"edge_{uuid.uuid4().hex[:8]}.mp3")

        def synth_and_play():
            try:
                subprocess.run(
                    base + ["--voice", self._edge_voice_name(),
                            "--text", text, "--write-media", out],
                    capture_output=True,
                    timeout=90,
                )
                if os.path.exists(out):
                    self._play_audio(out, "mp3")
            except Exception as error:
                self.logger.error(f"Edge TTS failed: {error}")
            finally:
                try:
                    os.unlink(out)
                except OSError:
                    pass

        with self.lock:
            self._speaking = True
        threading.Thread(target=synth_and_play, daemon=True).start()
        return True

    def _player_cmd(self, path, kind):
        """Player command for a synthesized file, or None."""
        if sys.platform.startswith("win"):
            powershell = Config.which("powershell")
            if kind == "wav" and powershell:
                return [
                    powershell, "-NoProfile", "-WindowStyle", "Hidden",
                    "-Command",
                    f"(New-Object System.Media.SoundPlayer '{path}').PlaySync();",
                ]
            return None

        if kind == "wav":
            paplay = Config.which("paplay")
            if paplay:
                return [paplay, "-q", path]
            pw = Config.which("pw-play")
            if pw:
                return [pw, path]
            aplay = Config.which("aplay")
            if aplay:
                return [aplay, "-q", path]
            ffplay = Config.which("ffplay")
            if ffplay:
                return [ffplay, "-nodisp", "-autoexit",
                        "-loglevel", "quiet", path]
        else:  # mp3/any
            mpv = Config.which("mpv")
            if mpv:
                return [mpv, "--really-quiet", "--no-video", path]
            ffplay = Config.which("ffplay")
            if ffplay:
                return [ffplay, "-nodisp", "-autoexit",
                        "-loglevel", "quiet", path]
            vlc = Config.which("vlc")
            if vlc:
                return [vlc, "--play-and-exit", "--no-video", path]
            mplayer = Config.which("mplayer")
            if mplayer:
                return [mplayer, "-really-quiet", "-vo", "null", path]
        return None

    def _play_audio(self, path, kind):
        command = self._player_cmd(path, kind)
        if not command:
            self.logger.warning("No audio player found for " + kind)
            return False
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform.startswith("win") else 0
                ),
            )
            with self.lock:
                self.process = process
                self._speaking = True
            threading.Thread(
                target=self._watch_process, args=(process,), daemon=True
            ).start()
            return True
        except Exception as error:
            self.logger.error(f"Audio playback failed: {error}")
            return False

    # ----------------------------------------------------------
    # Windows SAPI
    # ----------------------------------------------------------

    def _speak_sapi(self, text):
        safe = text.replace("'", "''")
        rate = int(self.rate)
        gender_hint = (
            "[System.Speech.Synthesis.VoiceGender]::Female"
            if self.gender != "male"
            else "[System.Speech.Synthesis.VoiceGender]::Male"
        )
        command = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SelectVoiceByHints({gender_hint}); "
            f"$s.Rate = {rate}; "
            f"$s.SetOutputToDefaultAudioDevice(); "
            f"$s.Speak('{safe}');"
        )

        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

        try:
            process = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", command], **kwargs
            )
            with self.lock:
                self.process = process
                self._speaking = True
            threading.Thread(
                target=self._watch_process, args=(process,), daemon=True
            ).start()
            return True
        except Exception as error:
            self.logger.error(f"TTS error: {error}")
            return False

    def _watch_process(self, process):
        try:
            process.wait()
        except Exception:
            pass
        with self.lock:
            if self.process is process:
                self.process = None
                self._speaking = False

    # ----------------------------------------------------------
    # Linux pyttsx3 worker
    # ----------------------------------------------------------

    def _ensure_pytts(self):
        if self._worker is None:
            import queue

            import pyttsx3

            self._queue = queue.Queue()
            self._stop_signal = threading.Event()
            self._pytts_engine = pyttsx3.init()

            voices = self._pytts_engine.getProperty("voices")
            target = "female" if self.gender != "male" else "male"
            for voice in voices:
                lowered = (voice.name or "").lower()
                if target in lowered or (
                    "female" in target and any(
                        k in lowered for k in ("zira", "samantha", "female")
                    )
                ):
                    self._pytts_engine.setProperty("voice", voice.id)
                    break

            rate = int((self.rate + 10) * 15)  # SAPI scale -> WPM-ish
            self._pytts_engine.setProperty(
                "rate", max(100, min(250, 150 + rate))
            )

            def worker():
                while True:
                    try:
                        item = self._queue.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    text, done = item
                    try:
                        self._pytts_engine.say(text)
                        self._pytts_engine.runAndWait()
                    except Exception as error:
                        self.logger.error(f"pyttsx3 error: {error}")
                    done.set()

            self._worker = threading.Thread(target=worker, daemon=True)
            self._worker.start()

    def _speak_pyttsx(self, text):
        import queue as _queue

        try:
            self._ensure_pytts()
        except Exception as error:
            self.logger.error(f"pyttsx3 init failed: {error}")
            self._engine_name = "espeak" if (
                Config.which("espeak") or Config.which("espeak-ng")
            ) else "disabled"
            if self.disabled:
                return False
            return self.speak(text)

        done = _queue.Event()
        with self.lock:
            self._speaking = True
        self._queue.put((text, done))

        def watcher():
            done.wait()
            with self.lock:
                self._speaking = False

        threading.Thread(target=watcher, daemon=True).start()
        return True

    # ----------------------------------------------------------
    # Linux espeak
    # ----------------------------------------------------------

    def _speak_espeak(self, text):
        espeak = Config.which("espeak") or Config.which("espeak-ng") or "espeak"
        voice = "en-us+f3" if self.gender != "male" else "en-us+m3"
        wpm = int((self.rate + 10) * 15) + 5

        try:
            process = subprocess.Popen(
                [espeak, "-v", voice, "-s", str(wpm), text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self.lock:
                self.process = process
                self._speaking = True
            threading.Thread(
                target=self._watch_process, args=(process,), daemon=True
            ).start()
            return True
        except Exception as error:
            self.logger.error(f"espeak error: {error}")
            return False

    # ----------------------------------------------------------
    # STOP / STATUS / SHUTDOWN
    # ----------------------------------------------------------

    def stop(self):
        with self.lock:
            process = self.process
            self.process = None
            self._speaking = False

        if self._stop_signal is not None:
            self._stop_signal.set()

        if self._pytts_engine is not None:
            try:
                if self._queue is not None:
                    while True:
                        self._queue.get_nowait()
            except Exception:
                pass
            try:
                self._pytts_engine.stop()
            except Exception:
                pass

        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except Exception:
                pass

    def is_speaking(self):
        with self.lock:
            return self._speaking

    def shutdown(self):
        self.stop()

    def engine_name(self):
        return self._engine_name