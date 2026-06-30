class ConversationEngine:

    def __init__(self, command_engine):

        self.command_engine = command_engine

    def start(self):

        print("\n========== MAXIE COMMAND MODE ==========")

        while True:

            command = input("\nYou : ")

            if command.lower() == "exit":

                print("\nMAXIE : Goodbye, Alwin.")

                break

            response = self.command_engine.execute(command)

            print(f"\nMAXIE : {response}")