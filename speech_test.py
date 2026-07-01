from Voice.speech_engine import SpeechEngine

speech = SpeechEngine()

while True:

    text = speech.recognize()

    print()

    print("You Said :", text)

    print()

    if text.lower() == "exit":

        break