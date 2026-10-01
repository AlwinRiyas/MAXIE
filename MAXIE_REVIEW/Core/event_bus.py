class EventBus:

    def __init__(self):

        self.listeners = {}

    def subscribe(self, event_name, callback):

        if event_name not in self.listeners:

            self.listeners[event_name] = []

        self.listeners[event_name].append(callback)

    def publish(self, event_name, data=None):

        if event_name not in self.listeners:

            return

        for callback in self.listeners[event_name]:

            callback(data)