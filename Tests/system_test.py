from Brain.brain_router import BrainRouter
from Brain.command_engine import CommandEngine

router = BrainRouter(CommandEngine())

tests = [
    "Open calculator",
    "Open brave",
    "What is Python?",
    "Remember gym at 6 PM",
    "Time",
    "Date",
    "Weather"
]

for test in tests:

    print("=" * 50)
    print("INPUT :", test)

    try:
        output = router.process(test)
        print("OUTPUT:", output)

    except Exception as e:
        print("ERROR :", e)