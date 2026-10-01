import unittest

from Core.event_bus import EventBus


class EventBusTest(unittest.TestCase):

    def setUp(self):
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        received = []
        self.bus.subscribe("command", received.append)
        self.bus.publish("command", "Open Calculator")
        self.assertEqual(received, ["Open Calculator"])

    def test_multiple_listeners(self):
        received = []
        self.bus.subscribe("command", received.append)
        self.bus.subscribe("command", received.append)
        self.bus.publish("command", "data")
        self.assertEqual(received, ["data", "data"])

    def test_publish_no_listeners_is_safe(self):
        # Should not raise even though nothing subscribes.
        self.bus.publish("unknown", "x")

    def test_per_event_routing(self):
        commands = []
        memory = []
        self.bus.subscribe("command", commands.append)
        self.bus.subscribe("memory", memory.append)
        self.bus.publish("command", "cmd")
        self.bus.publish("memory", "mem")
        self.assertEqual(commands, ["cmd"])
        self.assertEqual(memory, ["mem"])


if __name__ == "__main__":
    unittest.main()