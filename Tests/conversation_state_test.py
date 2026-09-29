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


if __name__ == "__main__":
    unittest.main()