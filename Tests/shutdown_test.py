import signal
import threading
import unittest
from unittest import mock

from Core.core_manager import Maxie


def bare_maxie():
    """A Maxie with every movable part replaced by a mock (TD-22/23/25).

    Built via object.__new__ so the heavy subsystem constructor (voice
    hardware, conversation loop) never runs in a headless test.
    """
    inst = object.__new__(Maxie)
    inst.logger = mock.MagicMock()
    inst.shutting_down = False
    inst._shutdown_lock = threading.Lock()
    inst.remote = mock.MagicMock()
    inst.conversation = mock.MagicMock()
    inst.voice_engine = mock.MagicMock()
    return inst


class ShutdownLifecycleTest(unittest.TestCase):
    """TD-22 (isolated teardown errors) and TD-25 (thread-safe flag)."""

    def test_shutdown_tears_down_every_step_once(self):
        inst = bare_maxie()
        inst.shutdown()
        inst.remote.stop.assert_called_once()
        inst.conversation.stop.assert_called_once()
        inst.voice_engine.shutdown.assert_called_once()
        self.assertTrue(inst.shutting_down)

    def test_shutdown_is_idempotent(self):
        inst = bare_maxie()
        inst.shutdown()
        inst.shutdown()
        inst.voice_engine.shutdown.assert_called_once()

    def test_one_teardown_failure_does_not_orphan_the_rest(self):
        inst = bare_maxie()
        inst.remote.stop.side_effect = RuntimeError("remote wedged")
        inst.shutdown()  # must not raise
        inst.conversation.stop.assert_called_once()
        inst.voice_engine.shutdown.assert_called_once()
        inst.logger.error.assert_any_call(
            mock.ANY)  # the failure reached the log

    def test_shutdown_without_remote_skips_gracefully(self):
        inst = bare_maxie()
        inst.remote = None
        inst.shutdown()
        inst.conversation.stop.assert_called_once()
        inst.voice_engine.shutdown.assert_called_once()

    def test_voice_shutdown_failure_still_logs(self):
        inst = bare_maxie()
        inst.voice_engine.shutdown.side_effect = OSError("stream closed")
        inst.shutdown()  # must not raise
        inst.conversation.stop.assert_called_once()


class SignalHandlerDeferralTest(unittest.TestCase):
    """TD-23: the signal handler must not run blocking teardown itself."""

    def test_signal_raises_and_defers_cleanup(self):
        inst = bare_maxie()
        with self.assertRaises(SystemExit):
            inst._handle_signal(signal.SIGTERM, None)
        inst.remote.stop.assert_not_called()
        inst.conversation.stop.assert_not_called()
        inst.voice_engine.shutdown.assert_not_called()
        self.assertFalse(
            inst.shutting_down, "cleanup is deferred to the main thread")


if __name__ == "__main__":
    unittest.main()