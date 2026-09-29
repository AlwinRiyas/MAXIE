import unittest

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


if __name__ == "__main__":
    unittest.main()