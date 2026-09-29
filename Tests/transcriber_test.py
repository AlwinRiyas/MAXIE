import types
import unittest
from unittest import mock

from Voice.transcriber import Transcriber


class TranscriberRetryTest(unittest.TestCase):
    """TD-06: a transient Whisper load failure must not latch permanently."""

    def test_transient_failure_is_retried_not_latched(self):
        calls = []

        class FlakyWhisperModel:

            def __init__(self, *args, **kwargs):
                calls.append("instantiate")
                if len(calls) == 1:
                    raise RuntimeError("transient download timeout")
                self._transcribed = False

            def transcribe(self, *args, **kwargs):
                self._transcribed = True
                return iter([]), None

        fake_module = types.ModuleType("faster_whisper")
        fake_module.WhisperModel = FlakyWhisperModel

        transcriber = Transcriber()
        with mock.patch.dict("sys.modules", {"faster_whisper": fake_module}):
            self.assertEqual(transcriber.transcribe("x.wav"), "",
                             "first load fails, transcription returns empty")
            self.assertEqual(len(calls), 1)

            transcriber._last_load_attempt = 0.0  # skip backoff
            self.assertEqual(transcriber.transcribe("x.wav"), "",
                             "second attempt succeeds; text is empty")
            self.assertEqual(len(calls), 2, "model must only be created once")

    def test_available_property_reflects_loaded_model(self):
        transcriber = Transcriber.__new__(Transcriber)
        transcriber.log = mock.MagicMock()
        transcriber.model = None
        transcriber._loaded = False
        transcriber._last_load_attempt = 0.0
        transcriber._retry_seconds = 30.0
        self.assertFalse(transcriber.available)
        transcriber.model = mock.MagicMock()
        transcriber._loaded = True
        self.assertTrue(transcriber.available)


class SharedTranscriberTest(unittest.TestCase):
    """SEC-01 / ROADMAP 5.8: one Whisper model is cached process-wide."""

    def tearDown(self):
        Transcriber._shared = None

    def test_shared_returns_one_instance(self):
        self.assertIs(Transcriber.shared(), Transcriber.shared())

    def test_shared_cached_across_calls(self):
        first = Transcriber.shared()
        second = Transcriber.shared()
        self.assertIs(first, second)
        Transcriber._shared = None
        third = Transcriber.shared()
        self.assertIsNot(second, third, "reset must produce a fresh instance")


if __name__ == "__main__":
    unittest.main()