import unittest

from Core.state_manager import AssistantState, StateManager


class StateManagerTest(unittest.TestCase):

    def test_initial_state(self):
        self.assertEqual(StateManager().get_state(), AssistantState.STARTING)

    def test_transitions(self):
        state = StateManager()
        for expected in (
            AssistantState.IDLE,
            AssistantState.LISTENING,
            AssistantState.THINKING,
            AssistantState.SPEAKING,
            AssistantState.IDLE,
        ):
            state.set_state(expected)
            self.assertEqual(state.get_state(), expected)

    def test_enum_values(self):
        self.assertEqual(AssistantState.IDLE.value, "idle")
        self.assertEqual(AssistantState.SHUTDOWN.value, "shutdown")


if __name__ == "__main__":
    unittest.main()