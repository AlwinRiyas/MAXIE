import types
import unittest
from unittest import mock

import numpy as np

from Voice.vad_engine import VADEngine


class VADEngineTest(unittest.TestCase):

    def setUp(self):
        self.vad = VADEngine()
        self.vad.set_energy_threshold(0.005)

    def test_silence_has_no_voice(self):
        silence = np.zeros(16000, dtype=np.float32)
        self.assertFalse(self.vad.has_voice(silence))
        self.assertEqual(self.vad.get_speech_timestamps(silence), [])

    def test_loud_audio_detected_as_speech(self):
        loud = np.full(16000, 0.3, dtype=np.float32)
        self.assertTrue(self.vad.has_voice(loud))
        timestamps = self.vad.get_speech_timestamps(loud)
        self.assertEqual(len(timestamps), 1)
        self.assertGreater(timestamps[0]["end"], timestamps[0]["start"])

    def test_short_clip_returns_empty(self):
        tiny = np.zeros(100, dtype=np.float32)
        self.assertEqual(self.vad.get_speech_timestamps(tiny), [])

    def test_process_block_energy_gate(self):
        loud_block = np.full(512, 0.3, dtype=np.float32)
        quiet_block = np.zeros(512, dtype=np.float32)
        self.assertTrue(self.vad.process_block(loud_block))
        self.assertFalse(self.vad.process_block(quiet_block))

    def test_noise_floor_calibration(self):
        quiet = np.full(512, 0.001, dtype=np.float32)
        self.vad.observe_noise(quiet)
        self.assertIsNotNone(self.vad.noise_floor)
        # After calibration, near-floor blocks are not speech.
        self.assertFalse(self.vad.process_block(np.full(512, 0.0025, np.float32)))
        self.vad.reset_noise()
        self.assertIsNone(self.vad.noise_floor)

    def test_real_room_speech_ratio_accepted(self):
        """TD-05: speech at ~2x ambient RMS must be detected.

        Real rooms show speech/ambient ratios of 1.5-2x, not 3x. A 0.008
        block after a 0.004 floor was previously rejected (needed > 0.012).
        """
        ambient = np.full(512, 0.004, dtype=np.float32)
        self.vad.observe_noise(ambient)
        speech = np.full(512, 0.008, dtype=np.float32)
        self.assertTrue(
            self.vad.process_block(speech),
            "speech at 2x ambient must pass the calibrated gate (TD-05)",
        )

    def test_default_noise_ratio_is_config_derived(self):
        from Config.config import Config

        ratio = float(Config.audio().get("vad_noise_ratio", 1.5))
        self.assertLess(ratio, 3.0, "3x ambient is unreachable in real rooms")
        self.assertGreater(ratio, 1.0)


class VADRetryTest(unittest.TestCase):
    """TD-06: a transient Silero load failure must not latch permanently."""

    def test_transient_failure_is_retried_not_latched(self):
        calls = []

        def flaky_load():
            calls.append("load")
            if len(calls) == 1:
                raise RuntimeError("transient OOM")
            return mock.MagicMock()

        fake_module = types.ModuleType("silero_vad")
        fake_module.load_silero_vad = flaky_load

        vad = VADEngine()
        with mock.patch.dict("sys.modules", {"silero_vad": fake_module}):
            self.assertFalse(vad.has_ml, "first attempt fails")
            self.assertEqual(len(calls), 1)

            vad._last_silero_attempt = 0.0  # skip backoff
            self.assertTrue(
                vad.has_ml,
                "a later attempt must be allowed to succeed (TD-06)",
            )
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()