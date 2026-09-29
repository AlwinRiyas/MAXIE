import os
import queue
import sys
import threading
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Voice.audio_recorder import AudioRecorder  # noqa: E402


def _make_recorder():
    """AudioRecorder with config-driven fields set, no hardware touched."""
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
    recorder.last_audio = None
    recorder.log = mock.MagicMock()
    recorder.vad = mock.MagicMock()
    recorder.vad.has_ml = True
    recorder.vad.noise_floor = 0.001
    recorder.vad.process_block.return_value = True
    recorder.audio_manager = mock.MagicMock()
    return recorder


class ListenLoopDeadlineTest(unittest.TestCase):
    """TD-03: _listen_loop must always terminate.

    Before the fix, the only termination conditions were "enough blocks
    dequeued" and "silence long enough after speech". If PortAudio stopped
    delivering callbacks -- e.g. a USB headset unplugged mid-sentence --
    `incoming.get` raised Empty on every iteration, `total_blocks` never
    advanced, and the loop never returned. The `finally` at the call site
    never ran and the conversation thread was dead permanently.
    """

    def test_stalled_capture_returns_none_instead_of_hanging(self):
        recorder = _make_recorder()
        incoming = queue.Queue(maxsize=512)  # never fed: simulates a dead device

        started = time.monotonic()
        result = recorder._listen_loop(
            incoming,
            max_total_blocks=10_000_000,   # effectively unbounded
            speech_samples=16000,
            block_seconds=0.032,
            max_total_seconds=0.6,
        )
        elapsed = time.monotonic() - started

        self.assertIsNone(result, "a stalled capture must return None")
        # The configured deadline is 0.6s, but a loaded CI box can stall the
        # GIL for seconds; the regression this guards against is a loop that
        # never returns at all, not one that is a few seconds late.
        self.assertLess(
            elapsed, 5.0,
            "_listen_loop must honour its wall-clock deadline (TD-03)",
        )
        recorder.log.warning.assert_called()

    def test_deadline_derived_from_config_not_hardcoded(self):
        """The budget must come from Config values, not a literal."""
        recorder = _make_recorder()
        recorder.speech_wait_timeout = 7.5
        self.assertAlmostEqual(recorder._total_budget(12.0), 24.5, places=3)

        recorder.speech_wait_timeout = 20.0
        self.assertAlmostEqual(recorder._total_budget(12.0), 37.0, places=3)

        # A non-positive capture limit must not shrink the budget.
        self.assertGreaterEqual(recorder._total_budget(0), 25.0)

    def test_speech_completes_before_deadline_is_unchanged(self):
        """A normal utterance must still be captured, not truncated."""
        recorder = _make_recorder()
        recorder.silence_blocks = 3
        incoming = queue.Queue(maxsize=512)
        import numpy as np

        for _ in range(4):                       # speech
            incoming.put_nowait(np.ones(512, dtype=np.float32) * 0.5)
        for _ in range(5):                       # trailing silence -> finalize
            incoming.put_nowait(np.zeros(512, dtype=np.float32))

        # Speech first, then silence, so the trailing-silence break fires.
        speechy = [True] * 4 + [False] * 5
        recorder.vad.process_block.side_effect = lambda block: speechy.pop(0)

        result = recorder._listen_loop(
            incoming,
            max_total_blocks=10_000_000,
            speech_samples=16000,
            block_seconds=0.032,
            max_total_seconds=10.0,
        )

        self.assertIsNotNone(result, "normal speech must still be captured")
        self.assertGreater(len(result), 512)
        recorder.log.warning.assert_not_called()

    def test_pre_speech_wait_timeout_still_applies(self):
        """The existing speech_wait_timeout path must keep working.

        With silence blocks fed and a non-empty queue, the pre-speech timeout
        breaks out long before the wall-clock deadline.
        """
        recorder = _make_recorder()
        recorder.speech_wait_timeout = 0.3
        incoming = queue.Queue(maxsize=512)
        import numpy as np

        for _ in range(3):
            incoming.put_nowait(np.zeros(512, dtype=np.float32))

        # Every block is non-speech, so only the pre-speech timeout can end it.
        recorder.vad.process_block.side_effect = None
        recorder.vad.process_block.return_value = False

        # Keep the queue topped up so the loop never sees Empty.
        stop = threading.Event()

        def feeder():
            while not stop.is_set():
                try:
                    incoming.put_nowait(np.zeros(512, dtype=np.float32))
                except queue.Full:
                    time.sleep(0.005)

        thread = threading.Thread(target=feeder, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            result = recorder._listen_loop(
                incoming,
                max_total_blocks=10_000_000,
                speech_samples=16000,
                block_seconds=0.032,
                max_total_seconds=30.0,
            )
            elapsed = time.monotonic() - started
        finally:
            stop.set()
            thread.join(timeout=1.0)

        self.assertIsNone(result)
        self.assertLess(elapsed, 3.0, "pre-speech timeout must fire first")
        recorder.log.warning.assert_not_called()


class StreamCleanupTest(unittest.TestCase):
    """TD-31: a stream whose start() fails must still be closed."""

    def test_stream_closed_when_start_fails(self):
        recorder = _make_recorder()
        fake_stream = mock.MagicMock()
        fake_stream.start.side_effect = RuntimeError("device busy")

        with mock.patch("Voice.audio_recorder.AudioManager.is_available",
                        return_value=True), \
                mock.patch("Voice.audio_recorder.Config.audio",
                           return_value={}), \
                mock.patch.dict(sys.modules, {"sounddevice": mock.MagicMock()}):
            sd = sys.modules["sounddevice"]
            sd.InputStream.return_value = fake_stream
            recorder.audio_manager.get_best_microphone.return_value = 0

            result = recorder.record("/tmp/maxie-test.wav")

        self.assertIsNone(result)
        fake_stream.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
