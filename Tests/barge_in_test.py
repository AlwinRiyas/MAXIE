import unittest
from unittest import mock

from Brain.voice_commands import VoiceCommands
from Voice.barge_in_listener import BargeInListener


def _make_listener():
    listener = BargeInListener.__new__(BargeInListener)
    listener.transcriber = mock.MagicMock()
    listener.device = 0
    listener.sample_rate = 16000
    listener.block_size = 512
    listener.running = True
    listener.interrupted = False
    listener.stream = mock.MagicMock()
    listener.thread = None
    listener.queue = mock.MagicMock()
    listener.rms_threshold = 0.003
    listener.capture_seconds = 1.0
    listener.max_utterance_seconds = 2.2
    listener.settlement_blocks = 6
    listener.quiet_for_stop = 0.35
    listener.logger = mock.MagicMock()
    return listener


class BargeInStopTest(unittest.TestCase):

    def test_stop_phrases_are_single_source_of_truth(self):
        """TD-30: the listener and the conversation gate must agree."""
        listener_phrases = BargeInListener.STOP_PHRASES
        for phrase in VoiceCommands.STOP_PHRASES:
            self.assertIn(
                phrase, listener_phrases,
                f"stop phrase '{phrase}' missing from the listener",
            )
        self.assertIn("stop it", listener_phrases)

    def _maybe_interrupt(self, text, duration=1.0):
        listener = _make_listener()
        with mock.patch.object(
            listener, "_transcribe", return_value=text
        ):
            samples = int(duration * listener.sample_rate)
            audio = [0.0] * samples
            return listener._maybe_interrupt(audio)

    def test_short_pure_stop_interrupts(self):
        self.assertTrue(self._maybe_interrupt("stop", duration=1.0))
        self.assertTrue(self._maybe_interrupt("be quiet", duration=1.5))

    def test_long_utterance_starting_with_stop_interrupts(self):
        """TD-30: 'stop, actually what time is it' must still interrupt."""
        self.assertTrue(
            self._maybe_interrupt("stop, actually what time is it", 4.0)
        )

    def test_long_utterance_without_stop_does_not_interrupt(self):
        """MAXIE's own continuous speech must not trigger a false stop."""
        self.assertFalse(
            self._maybe_interrupt("the weather tomorrow will be sunny in Chennai", 8.0)
        )

    def test_stop_mid_sentence_without_leading_stop_ignored(self):
        """A reply that happens to contain a later 'stop' is not an interrupt."""
        self.assertFalse(
            self._maybe_interrupt("we really need to stop soon, but more here", 4.0)
        )


class BargeInLifecycleTest(unittest.TestCase):
    """TD-28: the listener must be closeable even on the exception path."""

    def test_stop_after_start_failure_is_safe(self):
        listener = _make_listener()
        # Simulate start() failing halfway: stream never set.
        listener.stream = None
        listener.queue = None
        listener.stop()  # must not raise
        self.assertFalse(listener.running)


if __name__ == "__main__":
    unittest.main()