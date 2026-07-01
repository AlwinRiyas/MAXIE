from Core.event_bus import EventBus


bus = EventBus()


def logger(data):

    print("[LOGGER]", data)


def memory(data):

    print("[MEMORY]", data)


bus.subscribe("command", logger)

bus.subscribe("command", memory)


bus.publish("command", "Open Calculator")