import logging

from Config.config import Config


class AudioManager:
    """Cross-platform microphone discovery/selection.

    Device list comes from the optional ``sounddevice`` package. When it
    is not installed (headless box, CI), all methods degrade to safe
    defaults so MAXIE still starts.
    """

    log = logging.getLogger("MAXIE.audio")

    @staticmethod
    def is_available():
        try:
            import sounddevice  # noqa: F401

            return True
        except Exception:
            return False

    def __init__(self):
        self.selected_device = None

    # ----------------------------------------------------------
    # Listing
    # ----------------------------------------------------------

    def list_microphones(self):
        if not self.is_available():
            return []
        try:
            import sounddevice as sd

            devices = sd.query_devices()
        except Exception as error:
            self.log.warning(f"Couldn't query devices: {error}")
            return []

        microphones = []
        for index, device in enumerate(devices):
            channels = device.get("max_input_channels", 0)
            if channels > 0:
                microphones.append(
                    (index, device.get("name", f"Mic {index}"), channels)
                )
        return microphones

    # ----------------------------------------------------------
    # Selection
    # ----------------------------------------------------------

    def get_best_microphone(self):
        microphones = self.list_microphones()
        if not microphones:
            return None

        # 1. Explicit configuration wins.
        configured = Config.audio().get("microphone_index")
        if configured is not None:
            for index, name, channels in microphones:
                if index == configured:
                    self.selected_device = index
                    return index

        # 2. Configured preferred keywords (default: laptop array).
        keywords = Config.audio().get("preferred_microphone_keywords", [])
        for index, name, channels in microphones:
            lower = name.lower()
            if any(word.lower() in lower for word in keywords):
                self.selected_device = index
                return index

        # 3. Bluetooth headsets (a nicety, not a requirement).
        bluetooth = (
            "buds", "headset", "airpods", "bluetooth", "oneplus",
            "sony", "jbl", "boat", "boult", "realme",
        )
        for index, name, channels in microphones:
            lower = name.lower()
            if any(word in lower for word in bluetooth):
                self.selected_device = index
                return index

        # 4. First available microphone.
        self.selected_device = microphones[0][0]
        return microphones[0][0]

    def selected_name(self):
        microphones = self.list_microphones()
        if self.selected_device is None:
            return None
        for index, name, channels in microphones:
            if index == self.selected_device:
                return name
        return None

    def describe(self):
        """Diagnostic report used by system-info + tests."""
        devices = self.list_microphones()
        selected = self.get_best_microphone()
        return {
            "available": self.is_available(),
            "count": len(devices),
            "microphones": [{"index": i, "name": n} for i, n, c in devices],
            "selected": selected,
            "selected_name": self.selected_name(),
        }