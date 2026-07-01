import time

from Voice.audio_stream import AudioStream

stream = AudioStream()

stream.start()

print("Listening for 10 seconds...")

time.sleep(10)

stream.stop()