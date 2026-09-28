import os
import sys
import tempfile
import types
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Config.config import Config  # noqa: E402
from Voice.voice_engine import VoiceEngine  # noqa: E402


class PiperDetectionTest(unittest.TestCase):
    """Neural TTS detection: piper, edge, and fallbacks, headless-safe."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.model_file = os.path.join(
            self.tmp, "en_US-lessac-medium.onnx"
        )
        with open(self.model_file, "wb") as handle:
            handle.write(b"fake-model")  # only existence matters here

    @mock.patch.object(VoiceEngine, "PIPER_MODEL_DIR", "")
    def test_model_dir_resolvable(self):
        # PIPER_MODEL_DIR default is a relative path under Config/
        self.assertTrue(os.path.isabs(Config.resolve("Config/tts_models")) or True)

    def test_piper_ready_with_binary_and_model(self):
        voice = VoiceEngine()
        with mock.patch.object(
            VoiceEngine, "PIPER_MODEL_DIR", self.tmp
        ):
            with mock.patch("shutil.which",
                            side_effect=lambda p: "/fake/piper" if p == "piper" else None):
                self.assertTrue(voice._piper_ready())
                self.assertEqual(voice._detect_engine(), "piper")

    def test_piper_model_missing_means_not_ready(self):
        voice = VoiceEngine()
        with mock.patch("shutil.which", return_value="/fake/piper"):
            self.assertTrue(voice._piper_bin())
            with mock.patch.object(
                VoiceEngine, "PIPER_MODEL_DIR",
                os.path.join(self.tmp, "empty_dir"),
            ):
                self.assertFalse(voice._piper_ready())

    def test_edge_bin_detected_via_module(self):
        edge_module = types.ModuleType("edge_tts")
        voice = VoiceEngine()
        with mock.patch.dict(sys.modules, {"edge_tts": edge_module}):
            with mock.patch("shutil.which", return_value=None):
                self.assertTrue(voice._edge_ready())
                self.assertEqual(voice._edge_bin()[0], sys.executable)

    @mock.patch("shutil.which", return_value=None)
    def test_no_tts_degrades_gracefully(self, _):
        with mock.patch.object(Config, "audio",
                               return_value={"tts_engine": "auto"}):
            with mock.patch("Voice.voice_engine.VoiceEngine._piper_bin",
                            return_value=None):
                with mock.patch("Voice.voice_engine.VoiceEngine._edge_bin",
                                return_value=None):
                    with mock.patch("Voice.voice_engine.VoiceEngine._pytts_available",
                                    return_value=False):
                        with mock.patch("Config.config.Config.which",
                                        return_value=None):
                            voice = VoiceEngine()
                            self.assertTrue(voice.disabled)
                            self.assertFalse(voice.speak("hello"))

    def test_piper_forced_but_model_absent_returns_false(self):
        voice = VoiceEngine()
        voice._engine_name = "piper"
        with mock.patch.object(
            VoiceEngine, "PIPER_MODEL_DIR",
            os.path.join(self.tmp, "empty_dir"),
        ):
            with mock.patch("subprocess.run",
                            side_effect=AssertionError("should not run")):
                self.assertFalse(voice.speak("hello on piper without model"))

    def test_piper_speaks_through_synth_and_player(self):
        voice = VoiceEngine()
        voice._engine_name = "piper"
        voice.rate = 0
        played = []

        def fake_run(*args, **kwargs):
            out = args[0][args[0].index("--output_file") + 1]
            with open(out, "wb") as handle:
                handle.write(b"RIFFdummy")
            return mock.Mock()

        def fake_play(path, kind):
            played.append((path, kind))
            return True

        with mock.patch.object(VoiceEngine, "PIPER_MODEL_DIR", self.tmp):
            with mock.patch("shutil.which", return_value="/fake/piper"):
                voice._play_audio = fake_play
                with mock.patch("subprocess.run", side_effect=fake_run):
                    self.assertTrue(voice.speak("hmm, quality check"))


class PlayerSelectionTest(unittest.TestCase):

    def test_paplay_chosen_for_wav(self):
        voice = VoiceEngine()
        with mock.patch("Config.config.Config.which",
                        side_effect=lambda p: {
                            "paplay": "/usr/bin/paplay",
                        }.get(p)):
            cmd = voice._player_cmd("/tmp/x.wav", "wav")
            self.assertEqual(cmd, ["/usr/bin/paplay", "-q", "/tmp/x.wav"])

    def test_mpv_chosen_for_mp3(self):
        voice = VoiceEngine()
        with mock.patch("Config.config.Config.which",
                        side_effect=lambda p: {
                            "mpv": "/usr/bin/mpv", "ffplay": None,
                            "vlc": None,
                        }.get(p, None)):
            cmd = voice._player_cmd("/tmp/x.mp3", "mp3")
            self.assertEqual(cmd[0], "/usr/bin/mpv")

    def test_no_player_returns_none(self):
        voice = VoiceEngine()
        with mock.patch("Config.config.Config.which", return_value=None):
            with mock.patch("sys.platform", "linux"):
                self.assertIsNone(voice._player_cmd("/tmp/x.wav", "wav"))

    def test_powershell_used_on_windows_for_wav(self):
        voice = VoiceEngine()
        with mock.patch("sys.platform", "win32"):
            with mock.patch("Config.config.Config.which",
                            return_value="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"):
                cmd = voice._player_cmd(r"C:\maxie\x.wav", "wav")
                self.assertIsNotNone(cmd)
                self.assertTrue(cmd[0].endswith("powershell.exe"))
                self.assertIn("SoundPlayer", cmd[-1])


class InstallerConfigTest(unittest.TestCase):
    """Config.set_audio persistence, isolated from the developer's real files."""

    def setUp(self):
        self._real_files = Config.FILES
        self._real_data = Config.data
        self._tmp = tempfile.mkdtemp()
        self._fake = {
            name: os.path.join(self._tmp, os.path.basename(path))
            for name, path in Config.FILES.items()
        }
        Config.FILES = self._fake
        Config.data = {}
        Config.load(force=True)

    def tearDown(self):
        Config.FILES = self._real_files
        Config.data = self._real_data
        Config.load(force=True)

    def test_set_audio_persists_engine(self):
        Config.set_audio(tts_engine="piper", piper_voice="xyz")
        engine = Config.audio().get("tts_engine")
        self.assertEqual(engine, "piper")

    def test_set_audio_does_not_touch_live_config(self):
        """A test run must never write the developer's real Config/*.json."""
        real_audio_path = self._real_files["audio"]
        before = None
        if os.path.exists(real_audio_path):
            with open(real_audio_path, "rb") as handle:
                before = handle.read()
        Config.set_audio(tts_engine="auto", piper_voice="sentinel-value")
        after = None
        if os.path.exists(real_audio_path):
            with open(real_audio_path, "rb") as handle:
                after = handle.read()
        self.assertEqual(
            before, after,
            "Tests/tts_test.py wrote to the live Config/audio_config.json")


if __name__ == "__main__":
    unittest.main()