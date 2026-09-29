import os
import queue
import sys
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Voice.audio_recorder import AudioRecorder
from Voice.microphone_capture import MicrophoneCapture, SoundDeviceStream


class MicrophoneCaptureLifecycleTest(unittest.TestCase):

    def _recorder(self):
        recorder = AudioRecorder.__new__(AudioRecorder)
        recorder.sample_rate = 16000
        recorder.channels = 1
        recorder.block_size = 512
        recorder.max_seconds = 12.0
        recorder.min_silence_ms = 500
        recorder.silence_blocks = 15
        recorder.pre_roll_ms = 220
        recorder.pre_roll_blocks = 6
        recorder.speech_wait_timeout = 0.5
        recorder.blocks_per_second = 16000 / 512
        recorder._agc_target = 0.02
        recorder._agc_max_gain = 8.0
        recorder._agc_gain = 1.0
        recorder.last_audio = None
        recorder.log = mock.MagicMock()
        recorder.vad = mock.MagicMock()
        recorder.vad.has_ml = True
        recorder.vad.noise_floor = 0.001
        recorder.vad.process_block.return_value = True
        recorder.audio_manager = mock.MagicMock()
        return recorder

    def test_open_propagates_backend_error_and_records(self):
        """The MicrophoneCapture must surface an open failure and hold no
        half-open stream."""
        backend = mock.MagicMock()
        backend.open.side_effect = RuntimeError("device busy")

        capture = MicrophoneCapture(16000, 1, 512, device=0, backend=backend)
        with self.assertRaises(RuntimeError):
            capture.open()
        self.assertIsNone(capture.stream)
        backend.open.assert_called_once()

    def test_sounddevice_stream_closed_when_start_fails(self):
        """TD-31: a stream whose start() fails must still be closed. Lives
        in SoundDeviceStream.open, the real backend."""
        fake_stream = mock.MagicMock()
        fake_stream.start.side_effect = RuntimeError("device busy")

        with mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock()}):
            sd = sys.modules["sounddevice"]
            sd.InputStream.return_value = fake_stream
            backend = SoundDeviceStream()
            with self.assertRaises(RuntimeError):
                backend.open(16000, 1, 512, "float32", 0, lambda *a: None)

        fake_stream.close.assert_called_once()

    def test_read_returns_blocks_and_none_when_dry(self):
        backend = mock.MagicMock()
        fake_stream = mock.MagicMock()
        backend.open.return_value = fake_stream

        capture = MicrophoneCapture(16000, 1, 512, device=0, backend=backend)
        capture.open()

        # Feed the callback queue directly (simulate PortAudio delivering).
        block = np.ones(512, dtype=np.float32)
        capture.queue.put_nowait(block.copy())
        got = capture.read(timeout=0.05)
        self.assertIsNotNone(got)
        self.assertEqual(len(got), 512)

        # Dry stream -> None, and stall counter advances.
        self.assertIsNone(capture.read(timeout=0.02))
        self.assertGreater(capture.stall_blocks, 0)

        capture.close()
        backend.close.assert_called()
        self.assertIsNone(capture.stream)

    def test_close_is_idempotent(self):
        backend = mock.MagicMock()
        backend.open.return_value = mock.MagicMock()
        capture = MicrophoneCapture(16000, 1, 512, device=0, backend=backend)
        capture.open()
        capture.close()
        capture.close()  # must not raise
        backend.close.assert_called_once()

    def test_sounddevice_stream_close_stops_then_closes(self):
        fake_stream = mock.MagicMock()
        backend = SoundDeviceStream()
        backend.stream = fake_stream
        backend.close()
        fake_stream.stop.assert_called()
        fake_stream.close.assert_called()
        # Close again must not raise (stream already released by owner).
        backend.close()


class MicrophoneCaptureHotPlugTest(unittest.TestCase):

    def test_recover_reopens_a_stalled_stream(self):
        """ROADMAP 1.3: a device that goes silent is closed and reopened."""
        backend = mock.MagicMock()
        backend.is_available.return_value = True
        first = mock.MagicMock()
        second = mock.MagicMock()
        backend.open.side_effect = [first, second]

        capture = MicrophoneCapture(16000, 1, 512, device=0, backend=backend)
        capture.open()
        capture.stall_threshold = 5
        for _ in range(5):
            self.assertIsNone(capture.read(timeout=0.01))
        self.assertTrue(capture.has_stalled())
        capture.recover()

        self.assertEqual(backend.open.call_count, 2)
        self.assertIs(capture.stream, second)
        self.assertEqual(capture.stall_blocks, 0)

    def test_recover_fails_after_attempts_exhausted(self):
        """Recovery is bounded: a device that refuses to come back reports
        failure instead of spinning forever."""
        backend = mock.MagicMock()
        backend.open.side_effect = [mock.MagicMock(), RuntimeError("gone"), RuntimeError("gone")]

        capture = MicrophoneCapture(16000, 1, 512, device=0, backend=backend)
        capture.open()  # succeeds (first open)
        capture.recovery_attempts = 2

        self.assertFalse(capture.recover())
        # One original + two recovery opens attempted.
        self.assertEqual(backend.open.call_count, 3)


class AdaptiveAgcTest(unittest.TestCase):

    def _recorder(self):
        recorder = AudioRecorder.__new__(AudioRecorder)
        recorder.sample_rate = 16000
        recorder.channels = 1
        recorder.block_size = 512
        recorder._agc_target = 0.02
        recorder._agc_max_gain = 8.0
        recorder._agc_gain = 1.0
        recorder.last_audio = None
        return recorder

    def test_weak_speech_boosted_toward_target(self):
        """ROADMAP 1.4: quiet speech is amplified, not left at 3 sigma."""
        recorder = self._recorder()
        quiet = (np.random.RandomState(0).randn(16000).astype(np.float32) * 0.002)
        out = recorder._apply_agc(quiet.copy())
        in_rms = float(np.sqrt(np.mean(quiet * quiet)))
        out_rms = float(np.sqrt(np.mean(out * out)))

        self.assertGreater(out_rms, in_rms, "weak speech must be boosted")
        self.assertLess(out_rms, 0.5, "AGC must not blast the signal")
        # No hard clipping.
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)

    def test_loud_speech_capped_and_clipped_under_unity(self):
        recorder = self._recorder()
        loud = np.ones(16000, dtype=np.float32) * 0.9
        out = recorder._apply_agc(loud.copy())
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)

    def test_reset_gain_returns_to_unity(self):
        recorder = self._recorder()
        recorder._agc_gain = 3.0
        recorder.reset_gain()
        self.assertEqual(recorder._agc_gain, 1.0)


class RecordingIntegrationTest(unittest.TestCase):
    """record() must still work end-to-end with the MicrophoneCapture."""

    def _recorder(self):
        recorder = AudioRecorder.__new__(AudioRecorder)
        recorder.sample_rate = 16000
        recorder.channels = 1
        recorder.block_size = 512
        recorder.max_seconds = 1.0
        recorder.min_silence_ms = 200
        recorder.silence_blocks = 6
        recorder.pre_roll_ms = 220
        recorder.pre_roll_blocks = 6
        recorder.speech_wait_timeout = 0.2
        recorder.blocks_per_second = 16000 / 512
        recorder._agc_target = 0.02
        recorder._agc_max_gain = 8.0
        recorder._agc_gain = 1.0
        recorder.last_audio = None
        recorder.log = mock.MagicMock()
        recorder.vad = mock.MagicMock()
        recorder.vad.has_ml = True
        recorder.vad.noise_floor = 0.001
        recorder.vad.get_speech_region.return_value = (0, 8000)
        recorder.audio_manager = mock.MagicMock()
        return recorder

    def test_record_uses_microphone_capture_and_writes_wav(self):
        import tempfile

        recorder = self._recorder()
        backend = mock.MagicMock()

        capture = MicrophoneCapture(16000, 1, 512, device=0, backend=backend)

        def fake_open(samplerate, channels, blocksize, dtype, device, callback):
            for _ in range(40):
                callback(np.ones(512, dtype=np.float32) * 0.1, 512, None, None)
            return mock.MagicMock()

        backend.open.side_effect = fake_open
        recorder.vad.process_block.return_value = True
        capture.open()
        recorder._open_capture = mock.MagicMock(return_value=capture)

        with mock.patch("Voice.audio_recorder.MicrophoneCapture.backend_available",
                        return_value=True), \
                mock.patch("Voice.audio_recorder.AudioManager.is_available",
                           return_value=True):
            with tempfile.TemporaryDirectory() as tmp:
                wav = os.path.join(tmp, "out.wav")
                result = recorder.record(wav)
                self.assertEqual(result, wav)
                self.assertGreater(os.path.getsize(wav), 400)  # WAV header + samples

    def test_record_returns_none_when_capture_open_fails(self):
        recorder = self._recorder()
        recorder._open_capture = mock.MagicMock(return_value=None)

        with mock.patch("Voice.audio_recorder.MicrophoneCapture.backend_available",
                        return_value=True), \
                mock.patch("Voice.audio_recorder.AudioManager.is_available",
                           return_value=True):
            self.assertIsNone(recorder.record("/tmp/maxie-should-not-write.wav"))


if __name__ == "__main__":
    unittest.main()