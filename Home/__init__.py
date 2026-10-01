"""Home automation (ROADMAP 13).

Device registry, backend adapters, and the layer that resolves a spoken
request to one device action. No backend is required: with no hub
configured, every entry point reports that and does nothing.
"""

__all__ = [
    "device_registry",
    "home_adapter",
    "home_assistant",
    "home_automation",
    "hue",
]
