from Voice.speech_pipeline import SpeechPipeline


class SpeechEngine:

    def __init__(self):

        self.pipeline = SpeechPipeline()

    def recognize(self):

        return self.pipeline.recognize()