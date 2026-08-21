from Voice.voice_manager import VoiceManager


class ConversationEngine:

    def __init__(self, router, voice_engine):

        self.router = router
        self.voice_engine = voice_engine
        self.voice_manager = VoiceManager()

    def is_exit_command(self, command):

        command = command.lower().strip()

        command = command.replace(".", "")
        command = command.replace(",", "")
        command = command.replace("!", "")
        command = command.replace("?", "")

        exit_commands = {
            "exit",
            "quit",
            "close",
            "goodbye",
            "bye",
            "stop",
            "shutdown maxie",
            "close maxie",
            "exit maxie",
            "quit maxie",
            "i want to exit",
            "i want to quit",
            "i am exiting",
            "i'm exiting",
            "i am going to exit",
            "i'm going to exit",
        }

        if command in exit_commands:
            return True

        return False

    def start(self):

        print("\n========== MAXIE VOICE MODE ==========")
        print("Say 'exit' to close MAXIE.\n")

        while True:

            self.voice_manager.waiting()

            command = self.voice_manager.listen()

            if not command:
                continue

            command = command.strip()

            print(f"\nYou : {command}")

            if self.is_exit_command(command):

                self.voice_manager.speaking()

                print("\nMAXIE : Goodbye Alwin.")

                self.voice_engine.speak(
                    "Goodbye Alwin."
                )

                break

            response = self.router.process(command)

            self.voice_manager.speaking()

            print(f"\nMAXIE : {response}")

            self.voice_engine.speak(response)