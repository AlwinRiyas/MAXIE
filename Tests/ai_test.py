from AI.ai_engine import AIEngine

ai = AIEngine()

while True:

    question = input("\nYou : ")

    if question.lower() == "exit":
        break

    answer = ai.ask(question)

    print("\nMAXIE :")
    print(answer)