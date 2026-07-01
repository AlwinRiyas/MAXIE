from Brain.intent_engine import IntentEngine

intent = IntentEngine()

tests = [
    "Open Chrome",
    "Launch Android Studio",
    "Remember my gym",
    "What is SQL Injection",
    "Explain XSS",
    "Time",
    "Weather"
]

for t in tests:
    print(t, "->", intent.classify(t))