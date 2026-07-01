import sounddevice as sd


class AudioManager:

    def __init__(self):

        self.selected_device = None

    def list_microphones(self):

        devices = sd.query_devices()

        microphones = []

        for index, device in enumerate(devices):

            if device["max_input_channels"] > 0:

                microphones.append((index, device["name"]))

        return microphones

    def get_best_microphone(self):

        microphones = self.list_microphones()

        bluetooth_keywords = [
            "buds",
            "headset",
            "airpods",
            "bluetooth",
            "oneplus",
            "sony",
            "jbl",
            "boat",
            "boult",
            "realme"
        ]

        # First preference: Bluetooth headset mic
        for index, name in microphones:

            lower = name.lower()

            if any(word in lower for word in bluetooth_keywords):

                self.selected_device = index

                return index

        # Second preference: Laptop microphone
        for index, name in microphones:

            lower = name.lower()

            if "microphone array" in lower:

                self.selected_device = index

                return index

        # Last available microphone
        if microphones:

            self.selected_device = microphones[0][0]

            return microphones[0][0]

        return None