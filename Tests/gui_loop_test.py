import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import Ui.gui as gui_module  # noqa: E402


class _StubGUI(gui_module.MaxieGUI):
    """MaxieGUI with the tkinter window replaced by recording stubs.

    The real class was never instantiated by any test: `ui_test.py` only did
    `import Ui.gui`, so all 200+ lines of logic ran unverified. This subclass
    skips _build_window() only; every other method under test is the real one.
    """

    def __init__(self):
        self.maxie = mock.MagicMock()
        self.minimized = False
        self.queue = __import__("queue").Queue()
        self.auto_listening = False
        self._alive = True
        self._talk_lock = threading.Lock()
        self.log_lines = []
        self.status_texts = []
        self.remote_calls = []
        self.root = mock.MagicMock()
        self.status_var = mock.MagicMock()
        self.status_var.set.side_effect = self.status_texts.append

    def _build_window(self):
        pass

    def _log_line(self, line):
        self.log_lines.append(line)

    def _drain(self):
        while True:
            try:
                line = self.queue.get_nowait()
            except Exception:
                break
            self.log_lines.append(line)


class AutoListenTest(unittest.TestCase):
    """TD-04 and TD-15: the GUI auto-listen loop.

    The real loop called `root.winfo_exists()` from a worker thread, never
    slept when no speech was heard (a 100% CPU spin), and never acquired
    `_talk_lock`, so auto-listen and push-to-talk opened two InputStreams on
    one device. MAXIE then transcribed its own reply and re-routed the echo,
    which re-executes mutating commands silently.
    """

    def _make(self, heard_sequence, stop_after=None):
        gui = _StubGUI()
        gui.auto_listening = True
        calls = []

        def listen_once():
            calls.append(time.monotonic())
            index = len(calls) - 1
            if index < len(heard_sequence):
                return heard_sequence[index]
            if stop_after is not None and len(calls) >= stop_after:
                gui.auto_listening = False
            return ""

        gui.maxie.conversation.listen_once.side_effect = listen_once
        self._guis = getattr(self, "_guis", [])
        self._guis.append(gui)
        return gui, calls

    def tearDown(self):
        # A leaky auto-listen daemon keeps calling the submit mock forever and
        # stalls interpreter shutdown with a busy mock call under the GIL.
        for gui in getattr(self, "_guis", []):
            gui.auto_listening = False
        super().tearDown()

    def test_auto_loop_takes_the_talk_lock(self):
        gui, calls = self._make(["hello"], stop_after=2)
        lock_held_while_listening = []

        def listen_once():
            # Stop the loop on the first call so the thread cannot leak into
            # later tests as a daemon hammering the submit mock forever.
            gui.auto_listening = False
            lock_held_while_listening.append(gui._talk_lock.locked())
            return "hello"

        gui.maxie.conversation.listen_once.side_effect = listen_once
        thread = threading.Thread(target=gui._auto_loop, daemon=True)
        thread.start()
        thread.join(timeout=10)

        self.assertFalse(thread.is_alive(), "the auto-listen thread must exit")
        self.assertTrue(
            lock_held_while_listening,
            "_auto_loop must acquire the shared capture lock (TD-04)",
        )
        self.assertTrue(
            all(lock_held_while_listening),
            "the capture lock must be held for the whole listen",
        )

    def test_auto_loop_refuses_to_capture_while_lock_held(self):
        """With push-to-talk holding the lock, auto-listen must skip."""
        gui, calls = self._make([""] * 20)
        gui._talk_lock.acquire()  # simulate _on_talk in progress
        try:
            thread = threading.Thread(target=gui._auto_loop, daemon=True)
            thread.start()
            time.sleep(0.6)
            gui.auto_listening = False
            thread.join(timeout=5)
            self.assertEqual(
                calls, [],
                "auto-listen must not call listen_once while the mic is busy",
            )
        finally:
            gui._talk_lock.release()

    def test_auto_loop_does_not_spin_at_full_cpu(self):
        gui, calls = self._make([""] * 1000)
        thread = threading.Thread(target=gui._auto_loop, daemon=True)
        thread.start()
        time.sleep(0.75)
        gui.auto_listening = False
        thread.join(timeout=5)

        self.assertLess(
            len(calls), 10,
            "auto-listen must sleep between empty listens, not spin (TD-15)",
        )

    def test_auto_loop_never_calls_tkinter_off_thread(self):
        gui, calls = self._make([""] * 50)
        gui.root.winfo_exists.side_effect = AssertionError(
            "winfo_exists() must not be called off the Tk thread"
        )
        thread = threading.Thread(target=gui._auto_loop, daemon=True)
        thread.start()
        time.sleep(0.4)
        gui.auto_listening = False
        thread.join(timeout=5)
        gui.root.winfo_exists.assert_not_called()

    def test_auto_loop_survives_listen_errors(self):
        gui, calls = self._make([])

        def boom():
            raise RuntimeError("sounddevice exploded")

        gui.maxie.conversation.listen_once.side_effect = boom
        thread = threading.Thread(target=gui._auto_loop, daemon=True)
        thread.start()
        time.sleep(0.4)
        gui.auto_listening = False
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "loop must exit after auto_listening")
        gui._drain()
        self.assertTrue(
            any("Auto-listen error" in line for line in gui.log_lines),
            "listen errors must be surfaced, not crash the thread",
        )

    def test_auto_loop_submits_heard_speech(self):
        gui, calls = self._make(["what is the time", "", "stop"], stop_after=3)
        thread = threading.Thread(target=gui._auto_loop, daemon=True)
        thread.start()
        thread.join(timeout=10)
        submitted = [
            call.args[0] for call in
            gui.maxie.conversation.submit_text.call_args_list
        ]
        self.assertIn("what is the time", submitted)
        self.assertIn("stop", submitted)

    def test_alive_flag_stops_the_loop(self):
        gui, calls = self._make([""] * 100)
        gui._alive = False
        gui._auto_loop()
        self.assertEqual(
            calls, [],
            "_alive=False must end the loop before any tkinter call",
        )


class OnCloseTest(unittest.TestCase):
    """The auto-listen thread was left running against a destroyed Tk."""

    def test_on_close_clears_both_flags_and_shuts_down(self):
        gui = _StubGUI()
        gui.auto_listening = True
        gui._on_close()
        self.assertFalse(gui.auto_listening)
        self.assertFalse(gui._alive, "_alive must be cleared so workers exit")
        gui.maxie.shutdown.assert_called_once()
        gui.root.destroy.assert_called_once()


class PollStatusTest(unittest.TestCase):
    def test_poll_status_covers_every_state(self):
        from Voice.voice_state import VoiceState

        gui = _StubGUI()
        gui.maxie.conversation.voice_manager.get_state.return_value = (
            VoiceState.THINKING
        )
        gui._poll_status()
        self.assertEqual(gui.status_texts[-1], "Thinking…")

    def test_poll_status_handles_state_error(self):
        gui = _StubGUI()
        gui.maxie.conversation.voice_manager.get_state.side_effect = (
            RuntimeError("not ready")
        )
        gui._poll_status()
        self.assertEqual(gui.status_texts[-1], "Idle")

    def test_every_state_has_a_label(self):
        """No state may render as a bare 'Idle' fallback."""
        from Voice.voice_state import VoiceState

        seen = set()
        original = gui_module.MaxieGUI._poll_status

        for state in VoiceState:
            gui = _StubGUI()
            gui.maxie.conversation.voice_manager.get_state.return_value = state
            gui._poll_status()
            seen.add(gui.status_texts[-1])

        self.assertEqual(
            len(seen), len(list(VoiceState)),
            "each VoiceState needs its own status label",
        )


if __name__ == "__main__":
    unittest.main()
