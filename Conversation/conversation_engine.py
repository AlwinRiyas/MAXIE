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

            self.voice_manager.waiting()

            print("\n🎤 Waiting for speech...")

            command = self.voice_manager.listen()

            if not command:
                continue

            command = command.strip().lower()

            print(f"\nYou : {command}")

            # Ignore Whisper hallucinations
            if command in [
                "i exit",
                "exit.",
                "i exit.",
                "i'm exit",
                "i'm exiting",
                "..."
            ]:
                continue

            if command == "exit":

                print("\nMAXIE : Goodbye Alwin.")

                self.voice_engine.speak("Goodbye Alwin.")

                break

            response = self.router.process(command)

            self.voice_manager.speaking()

            print(f"\nMAXIE : {response}")

            self.voice_engine.speak(response)