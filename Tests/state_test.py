import os
import sys
import threading
import time
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Voice.voice_state import (  # noqa: E402
    CAPTURING_STATES,
    SPEAKING_STATES,
    VoiceState,
    can_transition,
    is_capturing,
    is_speaking,
)
from Voice.voice_state_machine import VoiceStateMachine  # noqa: E402


class TransitionTableTest(unittest.TestCase):
    """The state enum must model a real turn and forbid impossible jumps.

    Replaces the deleted `Core/state_manager.py` tests, which asserted only
    that a bare attribute could be assigned any enum value. The live
    `VoiceStateMachine` previously accepted any assignment from any thread, so
    the GUI could show "Thinking..." forever (TD-32).
    """

    def test_states_cover_the_full_turn_lifecycle(self):
        for name in ("IDLE", "WAKING", "LISTENING", "THINKING", "ACTING",
                     "SPEAKING", "COOLDOWN", "ERROR"):
            self.assertTrue(hasattr(VoiceState, name), f"missing {name}")

    def test_capture_and_speak_states_are_disjoint(self):
        self.assertFalse(
            CAPTURING_STATES & SPEAKING_STATES,
            "mic and speaker states must not overlap (echo control)",
        )

    def test_idle_is_reachable_from_every_state(self):
        for state in VoiceState:
            self.assertTrue(
                can_transition(state, VoiceState.IDLE),
                f"{state} must be able to shut down to IDLE",
            )

    def test_error_is_reachable_from_every_state(self):
        for state in VoiceState:
            self.assertTrue(
                can_transition(state, VoiceState.ERROR),
                f"{state} must be able to fail",
            )

    def test_illegal_transitions_are_refused(self):
        self.assertFalse(can_transition(VoiceState.SPEAKING, VoiceState.THINKING))
        self.assertFalse(can_transition(VoiceState.IDLE, VoiceState.COOLDOWN))
        self.assertFalse(can_transition(VoiceState.ACTING, VoiceState.LISTENING))
        self.assertFalse(can_transition(VoiceState.WAKING, VoiceState.SPEAKING))

    def test_playback_is_never_legal_from_a_capturing_state(self):
        """The structural echo guard, expressed as a table invariant.

        MAXIE must not be able to start speaking while the microphone is open:
        doing so makes it transcribe its own reply and re-execute the command
        (TD-04).
        """
        for state in CAPTURING_STATES:
            self.assertFalse(
                can_transition(state, VoiceState.SPEAKING),
                f"{state} holds the mic; playback must be illegal",
            )

    def test_legal_transitions_are_allowed(self):
        self.assertTrue(can_transition(VoiceState.IDLE, VoiceState.LISTENING))
        self.assertTrue(can_transition(VoiceState.LISTENING, VoiceState.THINKING))
        self.assertTrue(can_transition(VoiceState.THINKING, VoiceState.SPEAKING))
        self.assertTrue(can_transition(VoiceState.SPEAKING, VoiceState.COOLDOWN))
        self.assertTrue(
            can_transition(VoiceState.SPEAKING, VoiceState.LISTENING),
            "barge-in must be able to reopen the mic",
        )

    def test_none_is_not_a_transition(self):
        self.assertFalse(can_transition(None, VoiceState.IDLE))
        self.assertFalse(can_transition(VoiceState.IDLE, None))


class StateMachineTest(unittest.TestCase):
    """Behaviour of the machine, including the guards it must enforce."""

    def test_illegal_transition_refused_and_counted(self):
        machine = VoiceStateMachine()
        machine.force(VoiceState.SPEAKING)
        before = machine.rejected

        self.assertFalse(machine.transition(VoiceState.THINKING))
        self.assertEqual(machine.get_state(), VoiceState.SPEAKING)
        self.assertEqual(machine.rejected, before + 1)

    def test_transition_to_same_state_is_a_noop(self):
        machine = VoiceStateMachine()
        self.assertTrue(machine.transition(VoiceState.IDLE))
        self.assertEqual(machine.rejected, 0)

    def test_force_bypasses_the_table(self):
        machine = VoiceStateMachine()
        machine.force(VoiceState.SPEAKING)
        self.assertTrue(machine.force(VoiceState.THINKING))
        self.assertEqual(machine.get_state(), VoiceState.THINKING)

    def test_error_records_and_forces_error(self):
        machine = VoiceStateMachine()
        machine.error("transcription failed")
        self.assertEqual(machine.get_state(), VoiceState.ERROR)
        self.assertEqual(machine.last_error, "transcription failed")
        machine.reset()
        self.assertEqual(machine.get_state(), VoiceState.IDLE)
        self.assertIsNone(machine.last_error)

    def test_listeners_are_notified_with_both_states(self):
        machine = VoiceStateMachine()
        seen = []
        machine.subscribe(lambda prev, cur: seen.append((prev, cur)))
        machine.transition(VoiceState.LISTENING)
        machine.transition(VoiceState.THINKING)
        self.assertEqual(
            seen,
            [(VoiceState.IDLE, VoiceState.LISTENING),
             (VoiceState.LISTENING, VoiceState.THINKING)],
        )

    def test_failing_listener_does_not_break_transitions(self):
        machine = VoiceStateMachine()

        def bad(previous, current):
            raise RuntimeError("listener exploded")

        machine.subscribe(bad)
        machine.subscribe(lambda p, c: None)
        self.assertTrue(machine.transition(VoiceState.LISTENING))
        self.assertEqual(machine.get_state(), VoiceState.LISTENING)

    def test_unsubscribe_stops_notifications(self):
        machine = VoiceStateMachine()
        seen = []
        machine.subscribe(seen.append)
        machine.unsubscribe(seen.append)
        machine.transition(VoiceState.LISTENING)
        self.assertEqual(seen, [])

    def test_duplicate_subscription_fires_once(self):
        machine = VoiceStateMachine()
        seen = []

        def listener(prev, cur):
            seen.append(cur)

        machine.subscribe(listener)
        machine.subscribe(listener)
        machine.transition(VoiceState.LISTENING)
        self.assertEqual(len(seen), 1)


class EchoControlTest(unittest.TestCase):
    """Never capture while MAXIE speaks, and never speak while capturing.

    MAXIE's echo protection depends entirely on the microphone being closed
    during playback. The GUI's auto-listen loop ignored this and re-executed
    MAXIE's own replies (TD-04).
    """

    def test_capture_refused_while_speaking(self):
        machine = VoiceStateMachine()
        machine.force(VoiceState.SPEAKING)
        self.assertFalse(machine.can_capture())
        self.assertFalse(machine.reserve_capture())
        with self.assertRaises(RuntimeError):
            with machine.capture_guard():
                pass

    def test_capture_refused_during_cooldown(self):
        machine = VoiceStateMachine()
        machine.force(VoiceState.SPEAKING)
        machine.force(VoiceState.COOLDOWN)
        self.assertFalse(machine.can_capture())

    def test_playback_refused_while_capturing(self):
        machine = VoiceStateMachine()
        machine.force(VoiceState.LISTENING)
        self.assertFalse(machine.can_play())
        self.assertFalse(machine.reserve_playback())
        with self.assertRaises(RuntimeError):
            with machine.playback_guard():
                pass

    def test_capture_guard_enters_listening(self):
        machine = VoiceStateMachine()
        with machine.capture_guard():
            self.assertEqual(machine.get_state(), VoiceState.LISTENING)
            self.assertTrue(machine.is_capturing())
        self.assertEqual(machine.get_state(), VoiceState.IDLE)

    def test_capture_guard_can_release_into_thinking(self):
        """A real utterance closes the mic but leaves the turn in progress."""
        machine = VoiceStateMachine()
        with machine.capture_guard(release_to=VoiceState.THINKING):
            pass
        self.assertEqual(machine.get_state(), VoiceState.THINKING)

    def test_playback_guard_enters_speaking_then_cools_down(self):
        machine = VoiceStateMachine()
        with machine.playback_guard():
            self.assertEqual(machine.get_state(), VoiceState.SPEAKING)
            self.assertTrue(machine.is_speaking())
        self.assertEqual(machine.get_state(), VoiceState.COOLDOWN)

    def test_capture_guard_releases_lock_on_exception(self):
        machine = VoiceStateMachine()
        with self.assertRaises(ValueError):
            with machine.capture_guard():
                raise ValueError("transcription blew up")
        # The lock must be free again, or every later listen fails.
        self.assertTrue(machine.reserve_capture())
        machine.release_capture()

    def test_concurrent_capture_is_refused(self):
        machine = VoiceStateMachine()
        errors = []
        started = threading.Event()

        def worker():
            try:
                with machine.capture_guard():
                    started.set()
                    time.sleep(0.2)
            except RuntimeError as error:
                errors.append(error)

        first = threading.Thread(target=worker)
        first.start()
        started.wait(timeout=2.0)
        second = threading.Thread(target=worker)
        second.start()
        first.join(timeout=3.0)
        second.join(timeout=3.0)

        self.assertEqual(
            len(errors), 1,
            "a second concurrent capture must be refused (TD-04)",
        )

    def test_concurrent_playback_is_refused(self):
        machine = VoiceStateMachine()
        errors = []
        started = threading.Event()

        def worker():
            try:
                with machine.playback_guard():
                    started.set()
                    time.sleep(0.2)
            except RuntimeError as error:
                errors.append(error)

        first = threading.Thread(target=worker)
        first.start()
        started.wait(timeout=2.0)
        second = threading.Thread(target=worker)
        second.start()
        first.join(timeout=3.0)
        second.join(timeout=3.0)

        self.assertEqual(len(errors), 1)

    def test_is_capturing_and_is_speaking_are_distinct(self):
        machine = VoiceStateMachine()
        machine.force(VoiceState.LISTENING)
        self.assertTrue(machine.is_capturing())
        self.assertFalse(machine.is_speaking())

        machine.force(VoiceState.SPEAKING)
        self.assertFalse(machine.is_capturing())
        self.assertTrue(machine.is_speaking())


class ReservationTest(unittest.TestCase):
    """Check-and-claim must be atomic, or TD-04 is still open.

    Checking `can_capture()` and transitioning afterwards leaves a window in
    which the other side can win. `reserve_*` performs both under one lock, so
    exactly one of capture/playback can ever be granted.
    """

    def test_capture_wins_when_it_claims_first(self):
        machine = VoiceStateMachine()
        self.assertTrue(machine.reserve_capture())
        self.assertFalse(machine.reserve_playback())
        machine.release_capture()

    def test_playback_wins_when_it_claims_first(self):
        machine = VoiceStateMachine()
        self.assertTrue(machine.reserve_playback())
        self.assertFalse(machine.reserve_capture())
        machine.release_playback(VoiceState.IDLE)

    def test_capture_is_not_reclaimable_while_held(self):
        machine = VoiceStateMachine()
        self.assertTrue(machine.reserve_capture())
        self.assertFalse(machine.reserve_capture())
        machine.release_capture()
        self.assertTrue(machine.reserve_capture())
        machine.release_capture()

    def test_release_playback_can_end_the_turn(self):
        machine = VoiceStateMachine()
        machine.reserve_playback()
        machine.release_playback(VoiceState.IDLE)
        self.assertEqual(machine.get_state(), VoiceState.IDLE)

    def test_repeated_release_does_not_raise(self):
        machine = VoiceStateMachine()
        machine.reserve_capture()
        machine.release_capture()
        machine.release_capture()
        self.assertEqual(machine.get_state(), VoiceState.IDLE)


class ModuleHelpersTest(unittest.TestCase):
    def test_is_capturing_helper(self):
        self.assertTrue(is_capturing(VoiceState.LISTENING))
        self.assertTrue(is_capturing(VoiceState.WAKING))
        self.assertFalse(is_capturing(VoiceState.SPEAKING))
        self.assertFalse(is_capturing(VoiceState.IDLE))

    def test_is_speaking_helper(self):
        self.assertTrue(is_speaking(VoiceState.SPEAKING))
        self.assertTrue(is_speaking(VoiceState.COOLDOWN))
        self.assertFalse(is_speaking(VoiceState.LISTENING))

    def test_describe_returns_string(self):
        self.assertEqual(VoiceStateMachine().describe(), "idle")


if __name__ == "__main__":
    unittest.main()
