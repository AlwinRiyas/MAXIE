import queue
import sounddevice as sd

from Voice.audio_manager import AudioManager


class AudioStream:

    def __init__(self):

        self.sample_rate = 16000

        self.channels = 1

        self.block_size = 1024

        self.audio = AudioManager()

        self.queue = queue.Queue()

        self.stream = None

    def callback(self, indata, frames, time, status):

        if status:
            print(status)

        self.queue.put(indata.copy())

    def start(self):

        device = self.audio.get_best_microphone()

        print(f"\nUsing Microphone: {device}")

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.block_size,
            device=device,
            callback=self.callback
        )

        self.stream.start()

        print("🎤 Audio Stream Started")

    def stop(self):

        if self.stream:

            self.stream.stop()

            self.stream.close()

            print("🛑 Audio Stream Stopped")