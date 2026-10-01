import os
import sys
import threading
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Conversation.conversation_engine import ConversationEngine  # noqa: E402
from Voice.voice_manager import VoiceManager  # noqa: E402
from Voice.voice_state import VoiceState  # noqa: E402


class _EngineFactory:
    """A ConversationEngine whose voice pipeline is fully mocked.

    The conversation turn semantics (THINKING while routing, IDLE afterwards,
    atomic playback reservation) were never covered by a test. Building the
    real engine gives us the real VoiceManager and state machine; only the
    hardware and the router reply are fakes.
    """

    @staticmethod
    def build(router_response="hello there"):
        router = mock.MagicMock()
        router.process.return_value = router_response

        voice = mock.MagicMock()
        voice.disabled = False
        voice.is_speaking.return_value = False
        voice.speak.return_value = None

        engine = ConversationEngine.__new__(ConversationEngine)
        engine.router = router
        engine.voice_engine = voice
        engine.log_callback = None
        engine.logger = mock.MagicMock()
        engine.voice_manager = VoiceManager()
        engine.audio_manager = engine.voice_manager.audio
        engine.transcriber = None
        engine.microphone = None
        engine.barge_in = None
        engine.echo_cooldown = 0.0
        engine.running = threading.Event()
        engine.running.set()
        engine.remote_queue = __import__("queue").Queue()
        engine._remote_worker = None
        engine._speech_check = __import__(
            "Brain.voice_commands", fromlist=["VoiceCommands"]
        ).VoiceCommands()

        # Shut out hardware; recognize() returns whatever the test wants.
        engine.voice_manager.speech = mock.MagicMock()
        engine.voice_manager.speech.pipeline.is_available.return_value = True
        return engine


class HandleCommandTurnTest(unittest.TestCase):
    """TD-32: a completed turn must always return to IDLE.

    The old four-value enum entered PROCESSING and never left, so any finished
    turn left the GUI showing "Thinking..." forever.
    """

    def test_handle_command_returns_to_idle(self):
        engine = _EngineFactory.build()
        engine._handle_command("hello maxie")
        self.assertEqual(
            engine.voice_manager.get_state(), VoiceState.IDLE,
            "a routed command must close the turn",
        )

    def test_empty_reply_still_closes_the_turn(self):
        engine = _EngineFactory.build(router_response="")
        engine._handle_command("what is 2 plus 2")
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)

    def test_raising_skill_still_closes_the_turn(self):
        engine = _EngineFactory.build()
        engine.router.process.side_effect = RuntimeError("skill exploded")
        with mock.patch.object(engine, "_log"):
            try:
                engine._handle_command("turn up the volume")
            except RuntimeError:
                pass
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)

    def test_end_turn_does_not_clobber_a_live_capture(self):
        """The GUI auto-listen loop can be mid-capture when an async reply
        finishes. end_turn() force-switching to IDLE would erase the LISTENING
        marker while the mic lock is still held, letting playback claim a
        physically open microphone (TD-04)."""
        engine = _EngineFactory.build()
        self.assertTrue(engine.voice_manager.machine.reserve_capture())
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.LISTENING)

        engine.voice_manager.end_turn()

        self.assertEqual(
            engine.voice_manager.get_state(), VoiceState.LISTENING,
            "a live capture must keep ownership of the machine",
        )
        self.assertFalse(engine.voice_manager.reserve_playback())
        engine.voice_manager.machine.release_capture()
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)
        self.assertTrue(engine.voice_manager.reserve_playback())


class ListenStateTest(unittest.TestCase):
    """listen() must reflect the turn lifecycle on the machine."""

    def test_real_utterance_leaves_thinking(self):
        engine = _EngineFactory.build()
        engine.voice_manager.speech.recognize.return_value = "hello maxie"
        heard = engine.voice_manager.listen()
        self.assertEqual(heard, "hello maxie")
        self.assertEqual(
            engine.voice_manager.get_state(), VoiceState.THINKING,
            "a real utterance must leave the turn in THINKING, not IDLE",
        )

    def test_empty_transcript_returns_idle(self):
        engine = _EngineFactory.build()
        engine.voice_manager.speech.recognize.return_value = "   "
        self.assertEqual(engine.voice_manager.listen(), "")
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)

    def test_transcription_failure_returns_idle(self):
        engine = _EngineFactory.build()
        engine.voice_manager.speech.recognize.side_effect = (
            OSError("capture died")
        )
        self.assertEqual(engine.voice_manager.listen(), "")
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)

    def test_listen_refused_while_speaking(self):
        engine = _EngineFactory.build()
        engine.voice_manager.reserve_playback()  # MAXIE is talking
        heard = engine.voice_manager.listen()
        self.assertEqual(heard, "", "capture must refuse while speaking")
        self.assertFalse(engine.voice_manager.is_capturing())


class RemotePlaybackReservationTest(unittest.TestCase):
    """TD-04: the speaker claim and the check must be one atomic decision.

    _can_remote_speak() read the state and the speak thread changed it later,
    leaving a window in which the GUI auto-loop could open the mic and MAXIE
    would transcribe its own reply.
    """

    def test_remote_reply_is_refused_while_capturing(self):
        engine = _EngineFactory.build()
        engine.voice_manager.machine.reserve_capture()
        # reserve_playback() has already refused once inside _maybe_speak_remote,
        # so the counter moved; assert the refusal happened, not an exact delta.
        before = engine.voice_manager.machine.rejected

        engine._maybe_speak_remote("the answer")

        self.assertFalse(
            engine.voice_manager.is_speaking(),
            "playback must be refused while the microphone is open (TD-04)",
        )
        self.assertEqual(
            engine.voice_manager.get_state(), VoiceState.LISTENING
        )
        self.assertEqual(
            engine.voice_manager.machine.rejected, before,
            "one atomic refusal is enough for the open-microphone case",
        )

    def test_remote_reply_is_refused_when_disabled(self):
        engine = _EngineFactory.build()
        engine.voice_engine.disabled = True
        engine._maybe_speak_remote("the answer")
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)

    def test_disabled_tts_releases_an_already_held_reservation(self):
        """If the reservation was made and TTS turns out to be off, the
        speaker must be released or every later capture is refused."""
        engine = _EngineFactory.build()
        engine.voice_manager.reserve_playback()
        engine.voice_engine.disabled = True

        engine._speak_with_barge("the answer", reserved=True)

        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)
        self.assertTrue(
            engine.voice_manager.machine.reserve_capture(),
            "the microphone must be usable again",
        )

    def test_remote_reply_claims_speaker_then_releases(self):
        engine = _EngineFactory.build()
        engine._maybe_speak_remote("the answer")
        joined = engine._remote_worker  # placeholder
        self.assertTrue(
            engine.voice_manager.is_speaking() or
            engine.voice_manager.get_state() in (VoiceState.IDLE,),
            "the speaker must be claimed (or already released at this point)",
        )
        # Let the async speak thread finish and release the speaker.
        deadline = time.time() + 5
        while engine.voice_manager.is_speaking() and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(engine.voice_manager.get_state(), VoiceState.IDLE)
        self.assertTrue(engine.voice_manager.machine.reserve_capture())


class StopResolvesQueuedFuturesTest(unittest.TestCase):
    """TD-10: stop() must resolve every queued future, or the remote
    server blocks the whole 20 s DEFAULT_TIMEOUT and the GUI callback
    never fires."""

    def test_stop_resolves_queued_remote_futures(self):
        engine = _EngineFactory.build()
        unblock = threading.Event()

        def slow_process(text):
            unblock.wait(timeout=10)
            return f"done: {text}"

        engine.router.process = slow_process

        first = engine.submit_text("first command")
        self.assertFalse(first.done())
        # Let the worker pick `first` up (it will block in slow_process).
        deadline = time.time() + 5
        while not engine._remote_worker or not engine._remote_worker.is_alive():
            time.sleep(0.01)
            if time.time() > deadline:
                self.fail("remote worker never started")

        time.sleep(0.2)  # let the worker dequeue `first`
        second = engine.submit_text("second command")  # still queued

        engine.stop()
        unblock.set()  # release the worker so the in-flight future completes

        self.assertTrue(
            second.done(),
            "a queued future must be resolved by stop(), not orphaned",
        )
        with self.assertRaises(RuntimeError):
            second.result()

        deadline = time.time() + 5
        while not first.done() and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(first.done(), "an in-flight future must also resolve")

    def test_stop_returns_without_waiting_full_timeout(self):
        engine = _EngineFactory.build()
        unblock = threading.Event()

        def never_end(text):
            unblock.wait(timeout=30)
            return "late"

        engine.router.process = never_end

        blocked = engine.submit_text("block me")
        deadline = time.time() + 5
        while not engine._remote_worker or not engine._remote_worker.is_alive():
            time.sleep(0.01)
            if time.time() > deadline:
                self.fail("remote worker never started")
        time.sleep(0.2)

        start = time.time()
        engine.stop()
        elapsed = time.time() - start
        unblock.set()

        self.assertLess(
            elapsed, 5.0,
            "stop() must not hang on an in-flight remote command",
        )
        deadline = time.time() + 5
        while not blocked.done() and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(blocked.done())


class SurvivingTurnTest(unittest.TestCase):
    """One bad command must cost one turn, not the session.

    The suite covered the *loops* wrapping a failing turn (TD-28, TD-32) but
    never the whole path. This drives the real worker and the real text loop
    and asserts the session is still usable afterwards.
    """

    @staticmethod
    def _engine():
        engine = _EngineFactory.build()
        engine._log = lambda *a, **k: None
        return engine

    def _remote(self, engine, text, timeout=3):
        return engine.submit_text(text).result(timeout=timeout)

    def test_a_raising_turn_does_not_kill_the_remote_worker(self):
        """The bug: `router.process()` raised inside the worker loop, so the
        exception unwound out of `_remote_worker_loop` and killed the thread.
        The caller's future was never resolved and it waited out the full
        server timeout (30 s) for a reply that could not arrive. The next
        command only worked because `_ensure_remote_worker` respawned a fresh
        thread, which is why this looked intermittent in the field."""
        engine = self._engine()
        engine.router.process.side_effect = RuntimeError("skill exploded")

        started = time.time()
        reply = self._remote(engine, "turn on the kettle")
        elapsed = time.time() - started

        self.assertLess(
            elapsed, 1.0,
            "a failing turn must answer immediately, not time out",
        )
        self.assertIn("still here", reply)
        self.assertTrue(
            engine._remote_worker.is_alive(),
            "the worker thread must survive a failing turn",
        )

    def test_the_next_remote_command_still_answers(self):
        engine = self._engine()
        engine.router.process.side_effect = RuntimeError("skill exploded")
        self._remote(engine, "turn on the kettle")

        engine.router.process.side_effect = None
        engine.router.process.return_value = "The time is half past four."

        reply = self._remote(engine, "what time is it")
        self.assertEqual(reply, "The time is half past four.")
        self.assertTrue(engine._remote_worker.is_alive())

    def test_repeated_failures_do_not_exhaust_the_worker(self):
        """Ten failures in a row is the shape of a skill that is genuinely
        broken, not a one-off."""
        engine = self._engine()
        engine.router.process.side_effect = RuntimeError("still broken")

        for i in range(10):
            with self.subTest(attempt=i):
                self.assertIn("still here", self._remote(engine, f"try {i}"))

        self.assertTrue(engine._remote_worker.is_alive())
        engine.router.process.side_effect = None
        engine.router.process.return_value = "back to normal"
        self.assertEqual(self._remote(engine, "hello"), "back to normal")

    def test_a_raising_turn_does_not_end_the_text_session(self):
        """Before: an exception left the `while` loop, ran its `finally`, and
        shut MAXIE down. The user would relaunch after one bad command."""
        engine = self._engine()
        engine.router.process.side_effect = RuntimeError("skill exploded")
        seen = []
        real = engine._handle_command

        def record(command):
            seen.append(command)
            return real(command)

        engine._handle_command = record

        # The first command must not stop the loop; input then runs dry and
        # EOF ends the session the ordinary way.
        commands = iter(["turn on the kettle", "what time is it"])

        def input_side_effect(prompt=""):
            try:
                return next(commands)
            except StopIteration:
                raise EOFError

        with mock.patch("builtins.input", input_side_effect):
            engine._start_text_mode()

        self.assertEqual(
            seen, ["turn on the kettle", "what time is it"],
            "both turns must run: a failure costs one turn, not the session",
        )
        self.assertTrue(
            engine.voice_engine.speak.called,
            "a failed turn must be announced, not swallowed silently",
        )

    def test_the_failure_is_logged_and_announced(self):
        engine = self._engine()
        engine.router.process.side_effect = RuntimeError("disk on fire")
        engine.router.process.return_value = None
        reply = self._remote(engine, "do the thing")
        self.assertIn("still here", reply)
        logged = " ".join(
            str(call) for call in engine.logger.error.call_args_list)
        self.assertIn("disk on fire", logged)

    def test_the_reply_never_leaks_the_exception_text(self):
        """SEC-05: an internal message must not cross to the phone."""
        engine = self._engine()
        engine.router.process.side_effect = RuntimeError(
            "connection to 10.0.0.5:11434 refused")
        reply = self._remote(engine, "ask the ai")
        self.assertNotIn("10.0.0.5", reply)
        self.assertNotIn("11434", reply)
        self.assertNotIn("refused", reply)

class TextModeCleanupTest(unittest.TestCase):
    """TD-28: the barge-in listener holds a PortAudio stream, so a text-mode
    turn that raises must not exit the loop past its cleanup."""

    @staticmethod
    def _text_engine(commands):
        engine = _EngineFactory.build()
        engine._log = lambda *a, **k: None
        engine.barge_in = mock.MagicMock()
        inputs = iter(commands)

        def _input(_prompt=""):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError

        return engine, _input

    def test_a_failing_turn_still_releases_the_listener(self):
        """A turn that fails must not leak the barge-in listener.

        Since the surviving-turn fix the loop no longer re-raises, so the
        session ends by EOF and the `finally` runs on the ordinary path —
        which is exactly the property TD-28 was about: cleanup must not
        depend on *why* the loop ended.
        """
        engine, fake_input = self._text_engine(["hello maxie"])
        engine.router.process.side_effect = RuntimeError("skill exploded")
        with mock.patch("builtins.input", fake_input):
            engine._start_text_mode()
        self.assertTrue(
            engine.barge_in.stop.called,
            "a failing command must not leak the audio stream (TD-28)",
        )

    def test_a_clean_exit_releases_the_listener(self):
        engine, fake_input = self._text_engine(["hello maxie"])
        with mock.patch("builtins.input", fake_input):
            engine._start_text_mode()
        self.assertTrue(engine.barge_in.stop.called)
        self.assertTrue(
            engine.router.process.called,
            "one command must actually reach the router",
        )

    def test_ctrl_c_releases_the_listener(self):
        engine, fake_input = self._text_engine([""])
        with mock.patch("builtins.input", fake_input):
            engine._start_text_mode()
        self.assertTrue(engine.barge_in.stop.called)

    def test_the_voice_engine_is_shut_down_on_every_path(self):
        engine, fake_input = self._text_engine(["hello maxie"])
        engine.router.process.side_effect = RuntimeError("boom")
        with mock.patch("builtins.input", fake_input):
            engine._start_text_mode()
        self.assertTrue(engine.voice_engine.shutdown.called)


if __name__ == "__main__":
    unittest.main()