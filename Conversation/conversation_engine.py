from Voice.voice_manager import VoiceManager


class ConversationEngine:

    def __init__(self, router, voice_engine):

        self.router = router
        self.voice_engine = voice_engine
        self.voice_manager = VoiceManager()

    def start(self):

        print("\n========== MAXIE VOICE MODE ==========")
        print("Say 'exit' to close MAXIE.\n")

        while True:

            command = self.voice_manager.listen()

            if not command:
                continue

            print(f"\nYou : {command}")

            if command.lower() == "exit":

                self.voice_engine.speak("Goodbye Alwin.")

                print("\nMAXIE : Goodbye Alwin.")

                break

            response = self.router.process(command)

            print(f"\nMAXIE : {response}")

            self.voice_engine.speak(response)