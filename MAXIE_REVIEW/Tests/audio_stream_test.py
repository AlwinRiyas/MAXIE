import unittest

from Voice.audio_manager import AudioManager


class AudioStreamTest(unittest.TestCase):
    """Start/stop the audio stream when hardware is present, otherwise
    degrade gracefully. On headless dev boxes this is skipped."""

    def test_audio_manager_degrades_headless(self):
        manager = AudioManager()
        report = manager.describe()
        self.assertIsInstance(report["available"], bool)
        self.assertIsInstance(report["count"], int)
        self.assertIsInstance(report["microphones"], list)

    @unittest.skipUnless(AudioManager.is_available(), "requires sounddevice")
    def test_stream_start_stop(self):
        from Voice.audio_stream import AudioStream

        stream = AudioStream()
        stream.start()
        stream.stop()
        self.assertIsNone(stream.stream)


if __name__ == "__main__":
    unittest.main()