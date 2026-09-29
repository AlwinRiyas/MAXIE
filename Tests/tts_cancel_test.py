import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Config.config import Config  # noqa: E402
from Voice.voice_engine import VoiceEngine  # noqa: E402


def _make_engine():
    """A VoiceEngine with a stubbed engine name, bypassing detection."""
    engine = VoiceEngine.__new__(VoiceEngine)
    engine.logger = mock.MagicMock()
    engine.process = None
    engine.lock = __import__("threading").Lock()
    engine._speaking = False
    engine._cancel = __import__("threading").Event()
    engine._synth_process = None
    engine._pytts_engine = None
    engine._pytts_error = None
    engine._worker = None
    engine._queue = None
    engine._stop_signal = None
    engine.rate = 0
    engine.gender = "female"
    engine._engine_name = "piper"
    return engine


class _FakeSynthProcess:
    """Stands in for a piper/edge synthesis subprocess.

    ``terminate`` is what a real `stop()` would do; recording it lets the test
    assert that cancellation actually reaches synthesis, not just the player.
    """

    def __init__(self, exit_delay=0.0, create_output=True):
        self._exit_delay = exit_delay
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stdin = mock.MagicMock()
        self.stdout = None
        self.stderr = None
        self._create_output = create_output
        self._t0 = time.monotonic()

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if self._exit_delay and (
            time.monotonic() - self._t0 >= self._exit_delay
        ):
            self.returncode = 0
            if self._create_output:
                self._write_output()
        return self.returncode

    def _write_output(self):
        # _speak_piper_synth's caller checks os.path.exists(wav) indirectly
        # via the play path; we only need the process to exit 0 here.
        pass

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def communicate(self, timeout=None):
        return b"", b""


class TtsCancellationTest(unittest.TestCase):
    """TD-01: stop() during synthesis must prevent playback entirely.

    Before the fix, synthesis ran in a `subprocess.run` whose handle was never
    stored, so `stop()` could only kill the player. Saying "stop" during the
    piper synthesis window therefore let synthesis finish and then play at full
    volume into the microphone the conversation loop had just reopened.
    """

    def _run_speak_piper(self, engine, fake, wait_for_thread=True):
        model = os.path.join("Config", "tts_models", "fake.onnx")
        engine._piper_bin = mock.MagicMock(return_value=["piper"])
        engine._piper_model = mock.MagicMock(return_value=model)
        with mock.patch("os.path.exists", return_value=True), \
                mock.patch("subprocess.Popen", return_value=fake), \
                mock.patch("Voice.voice_engine.Config.temp_path",
                           return_value="/tmp/maxie-test.wav"), \
                mock.patch("Voice.voice_engine.Config.audio",
                           return_value={"tts_synth_timeout": 60}):
            result = engine._speak_piper("this is a long reply to interrupt")
            if wait_for_thread:
                for thread in threading_enumerate():
                    if thread.name.startswith("Thread-") and thread.is_alive():
                        thread.join(timeout=5.0)
        return result

    def test_stop_during_synthesis_prevents_playback(self):
        engine = _make_engine()
        played = []
        engine._play_audio = lambda path, kind: played.append(path) or True

        # Synthesis that does NOT finish on its own: it stays running until
        # terminate() is called, which is exactly the pre-fix failure window.
        fake = _FakeSynthProcess(exit_delay=30.0, create_output=False)

        started = []

        real_popen = subprocess.Popen

        def slow_popen(*a, **kw):
            started.append(time.monotonic())
            return fake

        engine._piper_bin = mock.MagicMock(return_value=["piper"])
        engine._piper_model = mock.MagicMock(
            return_value=os.path.join("Config", "tts_models", "fake.onnx")
        )

        with mock.patch("os.path.exists", return_value=True), \
                mock.patch("subprocess.Popen", side_effect=slow_popen), \
                mock.patch("Voice.voice_engine.Config.temp_path",
                           return_value="/tmp/maxie-test.wav"), \
                mock.patch("Voice.voice_engine.Config.audio",
                           return_value={"tts_synth_timeout": 60}):
            self.assertTrue(engine._speak_piper("interrupt me"))
            # Let synthesis get as far as Popen + the poll loop.
            time.sleep(0.15)
            # The user interrupts mid-synthesis.
            engine.stop()
            time.sleep(0.3)

        self.assertTrue(
            fake.terminated or fake.killed,
            "stop() must terminate the synthesis process, not only the player",
        )
        self.assertEqual(
            played, [],
            "cancelled synthesis must never reach playback (TD-01)",
        )

    def test_speak_clears_cancel_flag_for_next_utterance(self):
        """A new utterance must not be born cancelled by a previous stop()."""
        engine = _make_engine()
        engine._speak_piper = mock.MagicMock(return_value=True)
        engine._speak_edge = mock.MagicMock(return_value=True)

        engine.stop()
        self.assertTrue(engine._cancel.is_set(), "stop() must raise the flag")

        engine.speak("first reply")
        self.assertFalse(
            engine._cancel.is_set(),
            "speak() must clear the cancel flag for the new utterance",
        )

    def test_play_audio_refuses_when_cancelled(self):
        engine = _make_engine()
        engine._cancel.set()
        with mock.patch.object(engine, "_player_cmd",
                               return_value=["paplay", "x.wav"]), \
                mock.patch("subprocess.Popen") as popen:
            self.assertFalse(engine._play_audio("/tmp/x.wav", "wav"))
        popen.assert_not_called()


class PiperSuccessPlaybackTest(unittest.TestCase):
    """A successful Piper synthesis must actually reach the speaker.

    The cancellable-synthesis rewrite left `_speak_piper` calling
    `_speak_piper_synth` and discarding its result, so the WAV was synthesised
    and immediately unlinked without ever being played. MAXIE went silent on
    the default engine while every cancellation test still passed, because
    none of them exercised the success path.
    """

    def _speak_piper(self, engine, fake, wav="/tmp/maxie-ok.wav"):
        engine._piper_bin = mock.MagicMock(return_value=["piper"])
        engine._piper_model = mock.MagicMock(
            return_value=os.path.join("Config", "tts_models", "fake.onnx")
        )
        with mock.patch("os.path.exists", return_value=True), \
                mock.patch("subprocess.Popen", return_value=fake), \
                mock.patch("Voice.voice_engine.Config.temp_path",
                           return_value=wav), \
                mock.patch("Voice.voice_engine.Config.audio",
                           return_value={"tts_synth_timeout": 60}):
            result = engine._speak_piper("a reply the user must hear")
            for _ in range(200):
                if not engine.is_speaking():
                    break
                time.sleep(0.02)
        return result

    def test_successful_synthesis_is_played(self):
        engine = _make_engine()
        played = []
        engine._play_audio = lambda path, kind: played.append((path, kind)) or True

        # Exits 0 on its own: the success path.
        fake = _FakeSynthProcess(exit_delay=0.01, create_output=True)

        self.assertTrue(self._speak_piper(engine, fake))
        self.assertEqual(
            played, [("/tmp/maxie-ok.wav", "wav")],
            "a WAV that was synthesised successfully must be played",
        )
        self.assertFalse(
            fake.terminated or fake.killed,
            "a synthesis that exited on its own must not be terminated",
        )

    def test_successful_synthesis_clears_speaking(self):
        engine = _make_engine()
        engine._play_audio = mock.MagicMock(return_value=True)
        fake = _FakeSynthProcess(exit_delay=0.01, create_output=True)

        self._speak_piper(engine, fake)
        self.assertFalse(
            engine.is_speaking(),
            "the speaking flag must clear after playback is dispatched",
        )

    def test_failed_synthesis_is_not_played(self):
        engine = _make_engine()
        engine._play_audio = mock.MagicMock(return_value=True)
        # Non-zero exit: synthesis produced nothing usable.
        fake = _FakeSynthProcess(exit_delay=0.01, create_output=True)
        fake.returncode = 1

        self._speak_piper(engine, fake)
        engine._play_audio.assert_not_called()

    def test_temporary_wav_is_removed_after_playback(self):
        engine = _make_engine()
        engine._play_audio = mock.MagicMock(return_value=True)
        fake = _FakeSynthProcess(exit_delay=0.01, create_output=True)

        removed = []
        real_unlink = os.unlink
        with mock.patch("os.unlink", side_effect=lambda p: (
            removed.append(p), real_unlink.__call__(p) if os.path.exists(p) else None
        )[0]):
            self._speak_piper(engine, fake, wav="/tmp/maxie-ok.wav")

        self.assertEqual(
            removed, ["/tmp/maxie-ok.wav"],
            "the temp WAV must be cleaned up after playback",
        )


class TtsSpeakingLatchTest(unittest.TestCase):
    """TD-02: `_speaking` must clear on every failure path.

    Before the fix `_speaking` was only cleared downstream of a successful
    synthesis plus a real player process. A missing piper binary left the flag
    True forever, so `ConversationEngine._speak_with_barge` spun to its 40s
    deadline on every subsequent reply, permanently.
    """

    def test_piper_failure_clears_speaking_flag(self):
        engine = _make_engine()
        engine._piper_bin = mock.MagicMock(return_value=["piper"])
        engine._piper_model = mock.MagicMock(
            return_value=os.path.join("Config", "tts_models", "fake.onnx")
        )
        engine._play_audio = mock.MagicMock(return_value=True)

        # Synthesis raises, as it would with a broken/mismatched piper binary.
        with mock.patch("os.path.exists", return_value=True), \
                mock.patch("Voice.voice_engine.Config.temp_path",
                           return_value="/tmp/maxie-test.wav"), \
                mock.patch("Voice.voice_engine.Config.audio",
                           return_value={"tts_synth_timeout": 60}), \
                mock.patch("subprocess.Popen",
                           side_effect=OSError("piper binary vanished")):
            self.assertTrue(engine._speak_piper("will fail"))
            for _ in range(100):
                if not engine._speaking:
                    break
                time.sleep(0.02)

        self.assertFalse(
            engine.is_speaking(),
            "a TTS failure must not latch _speaking (TD-02)",
        )

    def test_piper_cancel_clears_speaking_flag(self):
        engine = _make_engine()
        engine._piper_bin = mock.MagicMock(return_value=["piper"])
        engine._piper_model = mock.MagicMock(
            return_value=os.path.join("Config", "tts_models", "fake.onnx")
        )
        engine._play_audio = mock.MagicMock(return_value=True)
        fake = _FakeSynthProcess(exit_delay=30.0, create_output=False)

        with mock.patch("os.path.exists", return_value=True), \
                mock.patch("subprocess.Popen", return_value=fake), \
                mock.patch("Voice.voice_engine.Config.temp_path",
                           return_value="/tmp/maxie-test.wav"), \
                mock.patch("Voice.voice_engine.Config.audio",
                           return_value={"tts_synth_timeout": 60}):
            engine._speak_piper("cancel me")
            time.sleep(0.15)
            engine.stop()
            time.sleep(0.3)

        self.assertFalse(engine.is_speaking())
        engine._play_audio.assert_not_called()

    def test_edge_failure_clears_speaking_flag(self):
        engine = _make_engine()
        engine._edge_bin = mock.MagicMock(return_value=["edge-tts"])
        engine._edge_voice_name = mock.MagicMock(return_value="en-US-JennyNeural")
        engine._play_audio = mock.MagicMock(return_value=True)

        with mock.patch("Voice.voice_engine.Config.temp_path",
                        return_value="/tmp/maxie-test.mp3"), \
                mock.patch("Voice.voice_engine.Config.audio",
                           return_value={"tts_synth_timeout": 90}), \
                mock.patch("subprocess.Popen",
                           side_effect=OSError("edge offline")):
            self.assertTrue(engine._speak_edge("will fail"))
            for _ in range(100):
                if not engine._speaking:
                    break
                time.sleep(0.02)

        self.assertFalse(engine.is_speaking())


def threading_enumerate():
    import threading
    return threading.enumerate()


if __name__ == "__main__":
    unittest.main()
